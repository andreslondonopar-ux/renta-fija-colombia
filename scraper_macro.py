"""
scraper_macro.py — Indicadores macro Colombia
Usa Playwright para abrir tradingeconomics.com/colombia/indicators
y leer los valores directamente de la página renderizada.
"""
import json, re, datetime
from pathlib import Path

TODAY = datetime.date.today().isoformat()
NOW   = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

FALLBACK = {
    "gdp_annual":    {"value": 2.2,   "source": "DANE · T1 2026"},
    "unemployment":  {"value": 8.8,   "source": "DANE · mar 2026"},
    "inflation":     {"value": 5.68,  "source": "DANE · abr 2026"},
    "inflation_mom": {"value": 0.78,  "source": "DANE · abr 2026"},
    "interest_rate": {"value": 11.25, "source": "BanRep · abr 2026"},
}

# Indicadores que buscamos en la página de TE
# Formato: (key_json, texto_buscar_en_tabla)
INDICATORS = [
    ("interest_rate", "Interest Rate"),
    ("inflation",     "Inflation Rate"),
    ("inflation_mom", "Inflation Rate Mom"),
    ("gdp_annual",    "GDP Annual Growth Rate"),
    ("unemployment",  "Unemployment Rate"),
]

def scrape_te():
    from playwright.sync_api import sync_playwright
    import re

    url = "https://tradingeconomics.com/colombia/indicators"
    result = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            '--no-sandbox', '--disable-setuid-sandbox',
            '--disable-dev-shm-usage', '--disable-gpu',
        ])
        page = browser.new_page(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
        )

        print(f"Abriendo {url}...")
        page.goto(url, wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(3000)  # esperar JS

        # Intentar cerrar cualquier popup/cookie
        for sel in ["button:has-text('Accept')", "button:has-text('Agree')",
                    "[id*='cookie'] button", "[class*='cookie'] button"]:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=1000):
                    btn.click()
                    page.wait_for_timeout(500)
            except:
                pass

        # Leer todo el texto de la tabla de indicadores
        content = page.content()
        text = page.inner_text("body")

        print(f"Página cargada: {len(text)} chars")

        # Buscar cada indicador — la página lista: "Indicator Name | Last | Previous | ..."
        # Patron: nombre seguido de número en las primeras columnas
        for key, name in INDICATORS:
            # Buscar en el texto el nombre del indicador y el valor que sigue
            # TE muestra: "Interest Rate\n11.25\n11.25\n..."
            patterns = [
                rf'{re.escape(name)}\s*\n\s*([\d.]+)',
                rf'{re.escape(name)}[^\n]*\n[^\n]*\n\s*([\d.]+)',
                rf'{re.escape(name)}.*?([\d]+\.[\d]+)(?:\s|%|$)',
            ]
            found = False
            for pat in patterns:
                m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
                if m:
                    try:
                        val = float(m.group(1))
                        if 0 < val < 200:  # sanity check
                            result[key] = {"value": val, "source": f"Trading Economics · {TODAY}"}
                            print(f"  ✓ {name}: {val}")
                            found = True
                            break
                    except:
                        pass
            if not found:
                print(f"  ✗ {name}: no encontrado")

        # Si el texto plano no funcionó, intentar con selectores de tabla
        if len(result) < 3:
            print("Intentando con selectores de tabla...")
            try:
                rows = page.locator("table tr").all()
                for row in rows:
                    row_text = row.inner_text()
                    for key, name in INDICATORS:
                        if key not in result and name.lower() in row_text.lower():
                            # Extraer primer número de la fila
                            nums = re.findall(r'([\d]+\.[\d]+)', row_text)
                            if nums:
                                try:
                                    val = float(nums[0])
                                    if 0 < val < 200:
                                        result[key] = {"value": val, "source": f"Trading Economics · {TODAY}"}
                                        print(f"  ✓ tabla: {name}: {val}")
                                except:
                                    pass
            except Exception as e:
                print(f"  Selector tabla: {e}")

        browser.close()

    return result


def main():
    print(f"=== Scraper Macro Colombia · {TODAY} ===\n")

    col = dict(FALLBACK)
    sources = []

    # Intentar Playwright + Trading Economics
    try:
        scraped = scrape_te()
        if len(scraped) >= 2:
            col.update(scraped)
            sources.append(f"TradingEconomics ({len(scraped)} indicadores)")
            print(f"\n✓ TE: {len(scraped)} indicadores obtenidos")
        else:
            print(f"\n⚠ TE: solo {len(scraped)} indicadores — usando fallback para el resto")
            col.update(scraped)
            if scraped:
                sources.append(f"TradingEconomics ({len(scraped)} indicadores)")
    except Exception as e:
        print(f"\n✗ Playwright falló: {e}")
        sources.append("fallback")

    # Leer macro_data.json existente para preservar UST
    macro_path = Path("macro_data.json")
    existing_ust = None
    if macro_path.exists():
        try:
            existing = json.loads(macro_path.read_text())
            existing_ust = existing.get("ust")
        except:
            pass

    result = {
        "colombia": col,
        "ust":      existing_ust or {"date": TODAY, "rates": []},
        "fecha":    TODAY,
        "updated":  NOW,
        "sources":  sources,
    }

    macro_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n✓ macro_data.json guardado")
    print(f"  Fuentes: {sources}")
    for k, v in col.items():
        print(f"  {k}: {v['value']} ({v['source']})")


if __name__ == "__main__":
    main()
