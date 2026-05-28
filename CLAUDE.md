# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Renta Fija Colombia** is a financial data pipeline + static dashboard project for Colombian fixed income markets. Three Python scrapers pull data from external sources on a daily schedule (GitHub Actions), save results as JSON files, and those JSON files are consumed client-side by static HTML dashboards.

## Running the Scrapers Locally

No package manager setup is needed — install dependencies directly:

```bash
pip install requests xlrd playwright
python -m playwright install chromium
```

Then run any scraper individually:

```bash
python scraper.py        # TES bond yield curve from BanRep SEN (Excel download)
python scraper_macro.py  # Colombian macro indicators from Trading Economics
python scraper_ust.py    # US Treasury yield curve from Treasury XML/CSV API
```

Each scraper writes its output JSON and exits. No test suite exists.

## Data Flow

```
BanRep SEN (Excel)    → scraper.py        → datos_curva.json
Trading Economics     → scraper_macro.py  → macro_data.json  (Colombia block)
US Treasury XML/CSV   → scraper_ust.py    → ust_data.json + macro_data.json (ust block)
```

The HTML dashboards (`index.html`, `rf_*.html`, `portafolio.html`) load these JSON files client-side at runtime — there is no build step for the frontend.

## Automation (GitHub Actions)

Three workflows in `.github/workflows/`:

| Workflow | Schedule (UTC) | Script | Output |
|---|---|---|---|
| `actualizar_curva.yml` | Mon–Fri 22:00 | `scraper.py` | `datos_curva.json` |
| `actualizar_macro.yml` | Mon–Fri 14:00 & 22:00 | `scraper_macro.py` | `macro_data.json` |
| `actualizar_ust.yml` | Mon–Fri 22:00 | `scraper_ust.py` | `ust_data.json`, `macro_data.json` |

Each workflow commits and pushes only when the output file actually changed (`git diff --staged --quiet`). All three can also be triggered manually via `workflow_dispatch`.

## Key Scraper Details

### scraper.py
- Uses Playwright (headless Chromium) to locate the Excel download link on BanRep SEN, with a 7-day direct-URL fallback.
- Decodes TFIT bond codes (e.g. `TFIT05270230` → maturity 27/02/2030) via a hard-coded mapping dict.
- Filters bonds: valid TIR 0–25%, maturity in the future, deduplicates by keeping highest yield per code.

### scraper_macro.py
- Uses Playwright to scrape Trading Economics' Colombia indicators page.
- Looks for 6 indicators: `interest_rate`, `inflation`, `inflation_mom`, `gdp_annual`, `unemployment`, `trade_balance`.
- Falls back to hard-coded DANE/BanRep values if scraping fails.
- Preserves the existing UST block in `macro_data.json` when updating only macro data.

### scraper_ust.py
- Four cascading sources: US Treasury XML (current year) → XML (prior year) → direct CSV → FiscalData API → hard-coded fallback.
- Writes results to both `ust_data.json` (standalone) and the `ust` block of `macro_data.json`.

## JSON Output Schema

**`datos_curva.json`** — array of TES bonds:
```json
[{ "codigo": "TFIT10040524", "name": "TES 2024", "tir": 7.45, "plazo": 0.25, "vencimiento": "04/05/2024" }]
```

**`macro_data.json`** — combined macro + UST:
```json
{
  "colombia": { "interest_rate": ..., "inflation": ..., "gdp_annual": ..., ... },
  "ust": [{ "plazo": "1M", "years": 0.083, "tir": 3.72 }, ...],
  "fecha": "2026-05-27", "updated": "...", "sources": {...}
}
```

**`ust_data.json`** — array of 13 UST tenors (1M–30Y): same structure as `macro_data.json`'s `ust` block.

## HTML Dashboards

Five static dashboards with inline CSS/JS (no framework, no bundler):
- `index.html` — homepage with macro indicators and links to calculators
- `rf_tasa_fija.html` — fixed-rate TES analysis
- `rf_ibr.html` — IBR-indexed bonds
- `rf_ipc.html` — IPC-indexed bonds
- `rf_uvr.html` — UVR-indexed bonds
- `portafolio.html` — portfolio management tool

All dashboards share a dark navy theme (`#0a0e1a`) and load JSON data directly via `fetch()` calls.
