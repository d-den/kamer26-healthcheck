# Kamer26 Site Health Check

Automatisch, extern van de eigen server draaiend, controleert of
[kamer26.nl](https://kamer26.nl) bereikbaar is, correcte HTML teruggeeft, en
of de database (via WooCommerce) nog live queries beantwoordt. Draait als
GitHub Actions workflow, dus onafhankelijk van de server die gemonitord
wordt.

## Wat wordt er gecheckt?

1. **HTTP-response** — statuscode, TTFB, totale laadtijd (`site_healthcheck.py::check_http`)
2. **HTML-validiteit** — compleet document, geen afgekapte/lege response (`check_html`)
3. **Database** — vraagt `/wp-json/wc/store/v1/products` op; dit endpoint
   doet altijd een live query op MySQL, dus een geldig antwoord bewijst dat
   WordPress + WooCommerce + database end-to-end werken (`check_database`)

## Hoe het werkt

- `.github/workflows/healthcheck.yml` draait elke 5 minuten (`cron: */5 * * * *`)
  op een schone GitHub-machine.
- `healthcheck_cron.py` voert de checks uit, vergelijkt de uitkomst met de
  vorige run (opgeslagen in `state.json`), en mailt via Brevo **alleen bij
  een statusverandering** (gezond → kapot, of kapot → gezond) — dus geen
  mail-spam zolang een probleem aanhoudt.
- Na elke run wordt `state.json` teruggecommit naar de repo, zodat de
  volgende (weggegooide) machine weet wat de vorige status was.

## Eenmalige setup

1. Repo aanmaken op GitHub (deze is bewust **public** — kost dan onbeperkt
   gratis Actions-minuten; kan later altijd naar private, zie onderaan).
2. Deze bestanden in de root zetten, inclusief de mapstructuur:
   ```
   .github/workflows/healthcheck.yml
   site_healthcheck.py
   healthcheck_cron.py
   state.json
   ```
3. Secrets instellen: repo → **Settings → Secrets and variables → Actions
   → New repository secret**
   - `BREVO_API_KEY` — API key uit Brevo (Settings → SMTP & API)
   - `ALERT_FROM_EMAIL` — bijv. `alerts@kamer26.nl` (moet een geverifieerd
     verzendadres/domain in Brevo zijn)
   - `ALERT_TO_EMAIL` — het mailadres dat de alert moet ontvangen
4. Workflow direct testen: tabblad **Actions → Kamer26 Site Health Check →
   Run workflow** (rechtsboven).

## Onderhoud / troubleshooting

- **Geen mail ontvangen bij een storing?** Check eerst het tabblad
  **Actions** — als de run zelf faalt (bijv. door een typefout in een
  secret), zie je dat daar in de logs.
- **State handmatig resetten** (bijv. na een false positive): pas
  `state.json` aan naar `{"status": "unknown", "updated_at": null}` en
  commit dat — de eerstvolgende run stuurt dan sowieso een mail, ongeacht
  de vorige status.
- **Interval aanpassen**: wijzig de cron-regel in
  `.github/workflows/healthcheck.yml`. Let op: onder 15 minuten is alleen
  zinvol/gratis op een **public** repo — op private telt elke run mee voor
  het minuten-budget (2.000 gratis/maand; bij elke 5 min ≈ 8.640
  runs/maand, dus dan al snel over de grens).
- **Andere URL toevoegen checken** (bijv. kamer26.de): kopieer het
  `Run health check`-blok in de workflow, geef het een andere `SITE_URL`
  env var en eventueel een eigen `state-de.json`.

## Public vs. private

Nu ingesteld op **public**. Dat betekent dat de repo-naam, code en
Actions-logs (dus ook de check-resultaten per run) voor iedereen met de
link zichtbaar zijn — de secret-*waarden* zelf blijven in beide gevallen
afgeschermd. Wil je dat liever niet, zet de repo dan om naar **private**
via **Settings → General → Danger Zone → Change visibility**, en overweeg
dan het interval iets op te rekken (zie hierboven) om binnen de gratis
minuten te blijven.
