# Kamer26 Site Health Check

Automatisch, extern van de eigen server draaiend, controleert of
[kamer26.nl](https://kamer26.nl) bereikbaar is, correcte HTML teruggeeft, en
of de database (via WooCommerce) nog live queries beantwoordt.

## Hoe werkt dit ook alweer? (kort overzicht)

```
cron-job.org (elke 5 min)
      │  POST-aanroep met token
      ▼
GitHub API  →  start de workflow (workflow_dispatch)
      │
      ▼
GitHub Actions  →  draait healthcheck_cron.py in deze repo
      │
      ├─ check_http()      → statuscode, laadtijd
      ├─ check_html()      → is de pagina compleet?
      └─ check_database()  → live query via /wp-json/wc/store/v1/products
      │
      ▼
Alleen bij statusverandering (gezond↔kapot) → mail via Brevo API
      │
      ▼
state.json wordt teruggecommit naar de repo (zodat de volgende run weet
wat de vorige status was)
```

Draait volledig **los van de eigen server** — als de server plat gaat, blijft
de monitoring werken en krijg je alsnog een mail.

### Waarom via cron-job.org, en niet GitHub's eigen `schedule:`?
GitHub's ingebouwde cron-trigger is "best effort" en bij een interval van
5 minuten worden de meeste geplande runs **overgeslagen of uren vertraagd**
(een bekende, structurele GitHub-beperking, geen bug in deze setup). Daarom
laat een externe, gratis dienst (cron-job.org) de workflow aanroepen via de
GitHub API (`workflow_dispatch`) — dat werkt wél betrouwbaar op tijd.

## Wat wordt er gecheckt?

1. **HTTP-response** — statuscode, TTFB, totale laadtijd (`site_healthcheck.py::check_http`)
2. **HTML-validiteit** — compleet document, geen afgekapte/lege response (`check_html`)
3. **Database** — vraagt `/wp-json/wc/store/v1/products` op; dit endpoint
   doet altijd een live query op MySQL, dus een geldig antwoord bewijst dat
   WordPress + WooCommerce + database end-to-end werken (`check_database`)

## De belangrijkste plekken om terug te vinden

| Wat | Waar |
|---|---|
| Deze repo | `github.com/d-den/kamer26-healthcheck` (public) |
| De 3 secrets (Brevo-key, mailadressen) | Repo → **Settings → Secrets and variables → Actions** |
| De externe trigger (elke 5 min) | Account op **cron-job.org** → job "Trigger healthcheck trigger" |
| Het token waarmee cron-job.org GitHub aanroept | Staat in de "Authorization"-header van die cronjob; **niet** ergens anders bewaard — bij verlies een nieuwe genereren via GitHub → **Settings → Developer settings → Fine-grained tokens** (rechten: alleen `Actions: Read and write` op deze repo) |
| Uitgevoerde runs bekijken | Repo → tabblad **Actions** |
| Huidige status | `state.json` in de repo root |

## Eenmalige setup (als je dit ooit opnieuw moet opzetten)

1. Repo aanmaken op GitHub, **public** (onbeperkt gratis Actions-minuten,
   ook bij een interval van 5 minuten — op private telt elke run mee voor
   het minuten-budget van 2.000/maand gratis).
2. Deze bestanden in de root zetten, inclusief de mapstructuur:
   ```
   .github/workflows/healthcheck.yml
   site_healthcheck.py
   healthcheck_cron.py
   state.json
   README.md
   ```
   (mappen aanmaken kan niet via drag-and-drop upload — gebruik **Add file →
   Create new file** en typ het volledige pad inclusief `/`, of clone de repo
   lokaal en push via git.)
3. Secrets instellen: repo → **Settings → Secrets and variables → Actions
   → New repository secret**
   - `BREVO_API_KEY` — API key uit Brevo (Settings → SMTP & API)
   - `ALERT_FROM_EMAIL` — bijv. `alerts@kamer26.nl` (moet een geverifieerd
     verzendadres/domain in Brevo zijn)
   - `ALERT_TO_EMAIL` — het mailadres dat de alert moet ontvangen
4. Personal Access Token aanmaken (zie tabel hierboven) voor de externe trigger.
5. Cronjob aanmaken op **cron-job.org**:
   - **URL:** `https://api.github.com/repos/d-den/kamer26-healthcheck/actions/workflows/healthcheck.yml/dispatches`
   - **Methode:** POST
   - **Interval:** elke 5 minuten
   - **Headers:** `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`, `Content-Type: application/json`
   - **Body:** `{"ref":"main"}`
   - Notificatie aanzetten bij **"execution of the cronjob fails"** (Notify
     after: 1 failure) — zodat je weet als de trigger zelf haapert (bijv.
     verlopen token), want dan draait de health check niet en blijft de
     stilte anders onopgemerkt.

## Onderhoud / troubleshooting

- **Geen mail ontvangen bij een storing?** Check eerst het tabblad
  **Actions** — draait de workflow überhaupt? Zo niet, check of de cronjob
  op cron-job.org nog actief is en of het token nog geldig is (fine-grained
  tokens verlopen na de ingestelde periode — zet hier een herinnering voor).
- **Workflow faalt op de "Commit updated state"-stap** (`fetch first` /
  rejected push)? Vrijwel altijd een tijdelijke botsing — bijv. omdat je
  zelf net iets in de repo bewerkte terwijl een run bezig was. De ingebouwde
  retry-logica (5 pogingen, met `git pull --rebase`) lost dit meestal vanzelf
  op bij de eerstvolgende run.
- **State handmatig resetten** (bijv. na een false positive): pas
  `state.json` aan naar `{"status": "unknown", "updated_at": null}` en
  commit dat — de eerstvolgende run stuurt dan sowieso een mail, ongeacht
  de vorige status.
- **Token vervangen**: nieuwe fine-grained token aanmaken op GitHub, en de
  `Authorization`-header in de cron-job.org-job bijwerken. De oude token
  intrekken (Settings → Developer settings → Personal access tokens).
- **Andere URL toevoegen checken** (bijv. kamer26.de): kopieer het
  `Run health check`-blok in de workflow, geef het een andere `SITE_URL`
  env var en eventueel een eigen `state-de.json`, en maak een aparte
  cron-job.org-job aan die naar dezelfde `dispatches`-URL post.

## Public vs. private

Nu ingesteld op **public**. Dat betekent dat de repo-naam, code en
Actions-logs (dus ook de check-resultaten per run) voor iedereen met de
link zichtbaar zijn — de secret-*waarden* zelf blijven in beide gevallen
afgeschermd. Wil je dat liever niet, zet de repo dan om naar **private**
via **Settings → General → Danger Zone → Change visibility**. Let dan wel
op het minuten-budget (zie "Eenmalige setup" hierboven) en overweeg het
interval iets op te rekken.
