#!/usr/bin/env python3
"""
Site health check script.

Checks, in order:
  1. HTTP response  - status code, TTFB, total load time
  2. HTML validity   - is the page complete and well-formed enough to trust
  3. Database check  - hits a DB-backed endpoint (WooCommerce Store API) to
                        confirm WordPress + WooCommerce + MySQL are actually
                        talking to each other, not just serving cached HTML

Usage:
    python3 site_healthcheck.py https://kamer26.nl
    python3 site_healthcheck.py https://kamer26.nl --title "Kamer26"
    python3 site_healthcheck.py https://kamer26.nl --no-db-check

Exit codes (useful for cron/monitoring):
    0 = all checks passed
    1 = one or more checks failed
    2 = script/config error (bad URL, missing dependency, etc.)
"""

import argparse
import sys
import time
from urllib.parse import urljoin

try:
    import requests
except ImportError:
    print("This script needs the 'requests' package: pip install requests")
    sys.exit(2)


TIMEOUT = 15  # seconds, per request


def check_http(url: str) -> dict:
    """Check 1: does the server respond, and how fast."""
    result = {"name": "HTTP response", "passed": False, "details": {}}
    try:
        start = time.perf_counter()
        resp = requests.get(url, timeout=TIMEOUT, allow_redirects=True)
        total_time = time.perf_counter() - start

        ttfb = resp.elapsed.total_seconds()

        result["details"] = {
            "status_code": resp.status_code,
            "ttfb_seconds": round(ttfb, 3),
            "total_seconds": round(total_time, 3),
            "final_url": resp.url,
            "content_length_bytes": len(resp.content),
        }
        result["passed"] = resp.status_code == 200
        result["_response"] = resp  # passed along internally to next checks
    except requests.exceptions.RequestException as e:
        result["details"]["error"] = str(e)
    return result


def check_html(resp, expected_title: str | None) -> dict:
    """Check 2: is the returned HTML actually a complete, valid-looking page."""
    result = {"name": "HTML validity", "passed": False, "details": {}}
    if resp is None:
        result["details"]["error"] = "No response to check (HTTP check failed first)"
        return result

    html = resp.text
    checks = {
        "has_doctype_or_html_tag": "<html" in html.lower(),
        "has_closing_html_tag": "</html>" in html.lower(),
        "has_head_section": "<head" in html.lower() and "</head>" in html.lower(),
        "has_body_section": "<body" in html.lower() and "</body>" in html.lower(),
        "has_title_tag": "<title" in html.lower(),
        "not_suspiciously_short": len(html) > 500,  # a blank/broken page is usually tiny
    }

    if expected_title:
        checks["title_matches_expected"] = expected_title.lower() in html.lower()

    result["details"] = checks
    result["passed"] = all(checks.values())
    return result


def check_database(base_url: str) -> dict:
    """
    Check 3: confirm the database behind the site is actually reachable and
    returning live data, not just that PHP/nginx is up.

    Uses the WooCommerce Store API, which always runs a live product query
    against MySQL - a cached or DB-down site cannot serve this correctly.
    """
    result = {"name": "Database (WooCommerce Store API)", "passed": False, "details": {}}
    api_url = urljoin(base_url, "/wp-json/wc/store/v1/products?per_page=1")

    try:
        resp = requests.get(
            api_url,
            timeout=TIMEOUT,
            headers={"Accept": "application/json"},
        )
        result["details"]["status_code"] = resp.status_code
        result["details"]["endpoint"] = api_url

        if resp.status_code != 200:
            result["details"]["error"] = f"Unexpected status code {resp.status_code}"
            return result

        data = resp.json()
        if not isinstance(data, list):
            result["details"]["error"] = "Response was not a JSON list of products"
            return result

        result["details"]["products_returned"] = len(data)
        if len(data) > 0:
            result["details"]["sample_product"] = {
                "id": data[0].get("id"),
                "name": data[0].get("name"),
            }
            result["passed"] = True
        else:
            # Empty catalog isn't necessarily a DB failure, but it's worth flagging
            result["details"]["warning"] = "Query succeeded but returned zero products"
            result["passed"] = True

    except requests.exceptions.RequestException as e:
        result["details"]["error"] = f"Request failed: {e}"
    except ValueError:
        result["details"]["error"] = "Response was not valid JSON"

    return result


def print_result(result: dict):
    status = "✅ PASS" if result["passed"] else "❌ FAIL"
    print(f"\n{status}  {result['name']}")
    for key, value in result["details"].items():
        if key.startswith("_"):
            continue
        print(f"    {key}: {value}")


def main():
    parser = argparse.ArgumentParser(description="Check site health: HTTP, HTML, and database.")
    parser.add_argument("url", help="Full URL to check, e.g. https://kamer26.nl")
    parser.add_argument("--title", help="Optional: text expected somewhere in the HTML (e.g. site name)", default=None)
    parser.add_argument("--no-db-check", action="store_true", help="Skip the WooCommerce database check")
    args = parser.parse_args()

    url = args.url
    if not url.startswith("http"):
        print("URL must start with http:// or https://")
        sys.exit(2)

    print(f"Running health check for: {url}")

    results = []

    http_result = check_http(url)
    results.append(http_result)
    print_result(http_result)

    resp = http_result.get("_response")
    html_result = check_html(resp, args.title)
    results.append(html_result)
    print_result(html_result)

    if not args.no_db_check:
        db_result = check_database(url)
        results.append(db_result)
        print_result(db_result)

    all_passed = all(r["passed"] for r in results)
    print("\n" + "=" * 40)
    print("ALL CHECKS PASSED" if all_passed else "ONE OR MORE CHECKS FAILED")
    print("=" * 40)

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
