#!/usr/bin/env python3
"""
Cron wrapper around site_healthcheck.py — designed to run in GitHub Actions.

- Runs all health checks against SITE_URL.
- Sends an email via the Brevo transactional API ONLY when the status
  CHANGES (healthy -> failing, or failing -> healthy), to avoid alert spam.
- State (state.json) lives in the repo itself; the GitHub Actions workflow
  commits it back after each run so state persists between runs even
  though each run happens on a fresh, throwaway machine.

Config is read from environment variables (set as GitHub Secrets in the
workflow). For local testing, a `.env` file in the same folder is also
supported as a fallback.

Required env vars / secrets:
    BREVO_API_KEY
    ALERT_FROM_EMAIL
    ALERT_FROM_NAME     (optional, defaults to "Site Monitoring")
    ALERT_TO_EMAIL
    SITE_URL
    NTFY_TOPIC          (optional — if set, also sends a push notification
                          via ntfy.sh in addition to the email)
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from site_healthcheck import check_http, check_html, check_database  # noqa: E402

SCRIPT_DIR = Path(__file__).parent
STATE_FILE = SCRIPT_DIR / "state.json"
ENV_FILE = SCRIPT_DIR / ".env"


def load_env() -> dict:
    """
    Prefer real environment variables (GitHub Actions secrets).
    Fall back to a local .env file for testing on your own machine.
    """
    keys = ["BREVO_API_KEY", "ALERT_FROM_EMAIL", "ALERT_FROM_NAME", "ALERT_TO_EMAIL", "SITE_URL", "NTFY_TOPIC"]
    env = {k: os.environ[k] for k in keys if k in os.environ}

    if len(env) < len(keys) and ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env.setdefault(key.strip(), value.strip())

    missing = [k for k in ["BREVO_API_KEY", "ALERT_FROM_EMAIL", "ALERT_TO_EMAIL", "SITE_URL"] if k not in env]
    if missing:
        print(f"Missing required config: {', '.join(missing)}")
        sys.exit(2)

    return env


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {"status": "unknown"}


def save_state(status: str):
    STATE_FILE.write_text(json.dumps({
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2) + "\n")


def send_alert_email(env: dict, subject: str, html_body: str):
    resp = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={
            "api-key": env["BREVO_API_KEY"],
            "Content-Type": "application/json",
        },
        json={
            "sender": {"name": env.get("ALERT_FROM_NAME", "Site Monitoring"),
                       "email": env["ALERT_FROM_EMAIL"]},
            "to": [{"email": env["ALERT_TO_EMAIL"]}],
            "subject": subject,
            "htmlContent": html_body,
        },
        timeout=15,
    )
    if resp.status_code >= 300:
        print(f"Failed to send alert email: {resp.status_code} {resp.text}")
    else:
        print("Alert email sent.")


def send_ntfy_alert(topic: str, title: str, message: str, priority: str = "default"):
    """
    Send a push notification via ntfy.sh. Silently skipped if no topic is
    configured (NTFY_TOPIC not set) — email remains the primary alert.

    HTTP headers only support Latin-1, so the title is stripped of any
    characters (e.g. emoji) that can't be encoded that way. The body has
    no such restriction and is sent as UTF-8.
    """
    safe_title = title.encode("latin-1", errors="ignore").decode("latin-1").strip()
    if not safe_title:
        safe_title = "Site health check"

    try:
        resp = requests.post(
            f"https://ntfy.sh/{topic}",
            data=message.encode("utf-8"),
            headers={
                "Title": safe_title,
                "Priority": priority,  # "urgent" for failures, "default" for recovery
            },
            timeout=10,
        )
        if resp.status_code >= 300:
            print(f"Failed to send ntfy notification: {resp.status_code} {resp.text}")
        else:
            print("Ntfy notification sent.")
    except requests.exceptions.RequestException as e:
        print(f"Failed to send ntfy notification: {e}")


def run_checks(site_url: str):
    results = []
    http_result = check_http(site_url)
    results.append(http_result)

    resp = http_result.get("_response")
    results.append(check_html(resp, expected_title=None))

    results.append(check_database(site_url))
    return results


def format_results_html(results, site_url: str) -> str:
    rows = ""
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        color = "#2e7d32" if r["passed"] else "#c62828"
        detail_lines = "<br>".join(
            f"{k}: {v}" for k, v in r["details"].items() if not k.startswith("_")
        )
        rows += (
            f"<p><strong style='color:{color}'>[{status}]</strong> {r['name']}"
            f"<br><small>{detail_lines}</small></p>"
        )
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"<h3>Health check for {site_url}</h3><p>{timestamp}</p>{rows}"


def main():
    env = load_env()
    site_url = env["SITE_URL"]

    results = run_checks(site_url)
    all_passed = all(r["passed"] for r in results)
    current_status = "pass" if all_passed else "fail"

    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"[{status}] {r['name']}")

    previous = load_state()
    previous_status = previous.get("status")

    if current_status != previous_status:
        if current_status == "fail":
            subject = f"\U0001F534 {site_url} health check FAILED"
            ntfy_title = f"FAILED: {site_url}"
            failed_checks = ", ".join(r["name"] for r in results if not r["passed"])
            ntfy_message = f"Failed: {failed_checks}"
            ntfy_priority = "urgent"
        else:
            subject = f"\u2705 {site_url} health check recovered"
            ntfy_title = f"Recovered: {site_url}"
            ntfy_message = "All checks passing again."
            ntfy_priority = "default"

        send_alert_email(env, subject, format_results_html(results, site_url))

        ntfy_topic = env.get("NTFY_TOPIC")
        if ntfy_topic:
            send_ntfy_alert(ntfy_topic, ntfy_title, ntfy_message, ntfy_priority)
    else:
        print(f"No status change ({current_status}) - no email sent.")

    save_state(current_status)
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
