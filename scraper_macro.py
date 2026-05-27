"""
scraper_macro.py — Indicadores macro Colombia via Trading Economics
Playwright abre tradingeconomics.com/colombia/indicators y lee la tabla.
"""
import json, re, datetime
from pathlib import Path

TODAY = datetime.date.today().isoformat()
NOW   = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

FALLBACK = {
    "interest_rate": {"value": 11.25, "source": "BanRep · fallback"},
    "inflation":     {"value": 5.68,  "source": "DANE · fallback"},
    "inflation_mom": {"value": 0.78,  "source": "DANE · fallback"},
    "gdp_annual":    {"value": 2.2,   "source": "DANE · fallback"},
    "unemployment":  {"value": 8.8,   "source": "DANE · fallback"},
    "trade_balance": {"value": -1200, "source": "DANE · fallback"},
}

# Indicadores a buscar — (key, texto exacto en TE, es_porcentaje)
INDICATORS = [
    ("interest_rate", "Interest Rate",          True),
    ("inflation",     "Inflation Rate",         True),
    ("inflation_mom", "Inflation Rate Mom",     True),
    ("gdp_annual",    "GDP Annual Growth Rate", True),
    ("unemployment",  "Unemployment Rate",      True),
    ("trade_balance", "Balance of Trade",       False),
]

def scrape_te():
    from playwright.sync_api import sync_playwright

    url = "https://tradingeconomics.com/colombia/indicators"
    result = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            '--no-sandbox','--disable-setuid-sandbox',
            '--disable-dev-shm-usage','--disable-gpu',
        ])
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width":1280,"height":900},
        )
        page = ctx.new_page()

        print(f"Abriendo {url}...")
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(4000)

        # Cerrar popups de cookies/consent
        for sel in [
            "button:has-text('Accept')", "button:has-text('I Accept')",
            "button:has-text('Agree')", "[id*='cookie'] button",
            "[class*='consent'] button", "#onetrust-accept-btn-handler",
        ]:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=800):
                    btn.click()
                    page.wait_for_timeout(500)
                    break
            except: pass

        # Esperar tabla
        try:
            page.wait_for_selector("table", timeout=10000)
        except:
            print("  No se encontró tabla, usando texto completo")

        text = page.inner_text("body")
        print(f"  Texto: {len(text)} chars")

        # Estrategia 1: leer filas de tabla con locator
        try:
            rows = page.locator("table tr").all()
            print(f"  Filas en tabla: {len(rows)}")
            for row in rows:
                try:
                    row_text = row.inner_text()
                    cells = row_text.strip().split('\t')
                    if len(cells) < 2: cells = row_text.strip().split('\n')
                    if len(cells) < 2: continue

                    indicator_cell = cells[0].strip()
                    value_cell = cells[1].strip() if len(cells) > 1 else ''

                    for key, name, is_pct in INDICATORS:
                        if key in result: continue
                        if name.lower() in indicator_cell.lower():
                            # Extraer número de value_cell
                            num = re.search(r'-?[\d,]+\.?\d*', value_cell.replace(',','.'))
                            if num:
                                try:
                                    val = float(num.group().replace(',',''))
                                    result[key] = {"value": val, "source": f"Trading Economics · {TODAY}"}
                                    print(f"  ✓ tabla: {name} = {val}")
                                except: pass
                except: continue
        except Exception as e:
            print(f"  Error leyendo tabla: {e}")

        # Estrategia 2: regex sobre texto completo
        for key, name, is_pct in INDICATORS:
            if key in result: continue
            patterns = [
                rf'{re.escape(name)}\s*\n\s*(-?[\d,.]+)',
                rf'{re.escape(name)}[^\n]{{0,30}}\n\s*(-?[\d,.]+)',
            ]
            for pat in patterns:
                m = re.search(pat, text, re.IGNORECASE|re.MULTILINE)
                if m:
                    try:
                        val = float(m.group(1).replace(',','.'))
                        result[key] = {"value": val, "source": f"Trading Economics · {TODAY}"}
                        print(f"  ✓ regex: {name} = {val}")
                        break
                    except: pass

        browser.close()

    return result


def main():
    print(f"=== Macro Colombia · {TODAY} ===\n")

    col = dict(FALLBACK)
    sources = []

    try:
        scraped = scrape_te()
        if scraped:
            col.update(scraped)
            sources.append(f"TradingEconomics ({len(scraped)} indicadores)")
            print(f"\n✓ Scraped: {len(scraped)} indicadores")
        else:
            print("\n✗ Sin datos de TE — usando fallback")
            sources.append("fallback")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        sources.append("fallback")

    # Preservar UST existente
    macro_path = Path("macro_data.json")
    existing_ust = None
    if macro_path.exists():
        try:
            existing_ust = json.loads(macro_path.read_text()).get("ust")
        except: pass

    result = {
        "colombia": col,
        "ust":      existing_ust or {"date": TODAY, "rates": []},
        "fecha":    TODAY,
        "updated":  NOW,
        "sources":  sources,
    }

    macro_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n✓ macro_data.json guardado · {sources}")
    for k, v in col.items():
        print(f"  {k}: {v['value']} ({v['source']})")


if __name__ == "__main__":
    main()
