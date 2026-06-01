"""
scraper_fedwatch.py — Probabilidades FOMC via CME FedWatch Tool
Playwright extrae las probabilidades de cada reunión del año.
Guarda fedwatch_data.json.
"""
import json, re, datetime
from pathlib import Path

TODAY = datetime.date.today().isoformat()
NOW   = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# Fallback con datos aproximados (se actualiza con scraping)
FALLBACK = {
    "updated": TODAY,
    "source": "CME FedWatch · ref. may 2026",
    "current_rate": "3.75-4.00",
    "meetings": [
        {"date": "2026-06-17", "label": "Jun '26", "probs": [
            {"label": "3.50-3.75", "bp": -25, "prob": 99.3},
            {"label": "3.75-4.00", "bp":   0, "prob":  0.7},
        ]},
        {"date": "2026-07-29", "label": "Jul '26", "probs": [
            {"label": "3.50-3.75", "bp": -25, "prob": 94.0},
            {"label": "3.75-4.00", "bp":   0, "prob":  5.9},
        ]},
        {"date": "2026-09-16", "label": "Sep '26", "probs": [
            {"label": "3.50-3.75", "bp": -25, "prob": 80.6},
            {"label": "3.75-4.00", "bp":   0, "prob": 18.5},
            {"label": "3.25-3.50", "bp": -50, "prob":  0.9},
        ]},
        {"date": "2026-10-28", "label": "Oct '26", "probs": [
            {"label": "3.50-3.75", "bp": -25, "prob": 66.3},
            {"label": "3.75-4.00", "bp":   0, "prob": 29.5},
            {"label": "3.25-3.50", "bp": -50, "prob":  4.0},
            {"label": "3.00-3.25", "bp": -75, "prob":  0.2},
        ]},
        {"date": "2026-12-09", "label": "Dic '26", "probs": [
            {"label": "3.50-3.75", "bp": -25, "prob": 51.8},
            {"label": "3.75-4.00", "bp":   0, "prob": 37.6},
            {"label": "3.25-3.50", "bp": -50, "prob":  9.6},
            {"label": "3.00-3.25", "bp": -75, "prob":  1.0},
        ]},
        {"date": "2027-01-27", "label": "Ene '27", "probs": [
            {"label": "3.50-3.75", "bp": -25, "prob": 47.6},
            {"label": "3.75-4.00", "bp":   0, "prob": 38.7},
            {"label": "3.25-3.50", "bp": -50, "prob": 11.9},
            {"label": "3.00-3.25", "bp": -75, "prob":  1.7},
            {"label": "2.75-3.00", "bp":-100, "prob":  0.1},
        ]},
    ]
}


def parse_rate_range(text):
    """Extrae rango de tasa como '4.25-4.50' del texto."""
    m = re.search(r'(\d+\.\d+)\s*[-–]\s*(\d+\.\d+)', text)
    return f"{m.group(1)}-{m.group(2)}" if m else text.strip()


def scrape_fedwatch():
    from playwright.sync_api import sync_playwright

    url = "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html"
    meetings = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            '--no-sandbox', '--disable-setuid-sandbox',
            '--disable-dev-shm-usage', '--disable-gpu',
        ])
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.new_page()

        print(f"Abriendo {url}...")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        # Cerrar popups
        for sel in [
            "button:has-text('Accept')", "button:has-text('I Accept')",
            "#onetrust-accept-btn-handler", "[class*='consent'] button",
        ]:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=800):
                    btn.click()
                    page.wait_for_timeout(500)
                    break
            except: pass

        page.wait_for_timeout(4000)

        # Intentar obtener datos de la API interna que usa la página
        # CME FedWatch carga datos via XHR — interceptar o leer del DOM
        text = page.inner_text("body")
        print(f"  Texto: {len(text)} chars")

        # Buscar patrones de probabilidades en el texto extraído
        # El tool muestra porcentajes junto a rangos de tasa
        # Estrategia: leer tabla de probabilidades por reunión

        # Intentar con locator de la tabla principal
        try:
            # Buscar celdas con porcentajes y rangos de tasa
            rows = page.locator("table tr, [class*='probability'] [class*='row'], [class*='meeting']").all()
            print(f"  Elementos encontrados: {len(rows)}")
            for row in rows[:50]:
                try:
                    rt = row.inner_text()
                    if '%' in rt and ('25' in rt or '50' in rt or '75' in rt):
                        print(f"  Row: {rt[:120]}")
                except: continue
        except Exception as e:
            print(f"  Error locator: {e}")

        # Parsear desde el texto completo — buscar bloques de reuniones
        # Formato típico: "Jun 18, 2026\n4.25-4.50%\n35.0%\n4.00-4.25%\n58.0%..."
        lines = [l.strip() for l in text.split('\n') if l.strip()]

        # Buscar fechas de reunión y probabilidades asociadas
        date_pattern = re.compile(
            r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}', re.I
        )
        pct_pattern  = re.compile(r'^(\d+\.?\d*)%$')
        rate_pattern = re.compile(r'^\d+\.\d+\s*[-–]\s*\d+\.\d+%?$')

        current_meeting = None
        for i, line in enumerate(lines):
            dm = date_pattern.search(line)
            if dm:
                # Nueva reunión detectada
                try:
                    dt = datetime.datetime.strptime(
                        re.sub(r',', '', dm.group()), "%b %d %Y"
                    )
                    current_meeting = {
                        "date": dt.strftime("%Y-%m-%d"),
                        "label": dt.strftime("%b '%y"),
                        "probs": []
                    }
                    meetings.append(current_meeting)
                except: pass
                continue

            if current_meeting and rate_pattern.match(line):
                # Siguiente línea debería ser el porcentaje
                rate_str = parse_rate_range(line)
                if i + 1 < len(lines):
                    pm = pct_pattern.match(lines[i + 1])
                    if pm:
                        current_meeting["probs"].append({
                            "label": rate_str,
                            "bp": 0,
                            "prob": float(pm.group(1))
                        })

        browser.close()

    # Calcular bp relativo para cada reunión (respecto al rango más alto = sin cambio)
    for m in meetings:
        if m["probs"]:
            rates = [p["label"] for p in m["probs"]]
            # El rango más alto de tasa = tasa actual implícita
            def rate_mid(r):
                nums = re.findall(r'\d+\.\d+', r)
                return float(nums[1]) if len(nums) >= 2 else (float(nums[0]) if nums else 0)
            max_rate = max(rate_mid(r) for r in rates)
            for p in m["probs"]:
                diff = round((rate_mid(p["label"]) - max_rate) * 100)
                # Redondear a múltiplos de 25bp
                p["bp"] = round(diff / 25) * 25

    return meetings


def main():
    print(f"=== FedWatch · {TODAY} ===\n")

    result = dict(FALLBACK)
    meetings = []

    try:
        meetings = scrape_fedwatch()
        if meetings and len(meetings) >= 2:
            # Filtrar solo reuniones futuras con probabilidades
            future = [
                m for m in meetings
                if m["date"] >= TODAY and m["probs"]
            ]
            if future:
                result["meetings"] = future[:5]
                result["source"]   = f"CME FedWatch · {TODAY}"
                result["updated"]  = NOW
                # Tasa actual = rango más alto de la primera reunión
                first_probs = future[0]["probs"]
                rates = [p["label"] for p in first_probs]
                def rate_mid(r):
                    nums = re.findall(r'\d+\.\d+', r)
                    return (float(nums[0]) + float(nums[1])) / 2 if len(nums) >= 2 else 0
                result["current_rate"] = max(rates, key=rate_mid)
                print(f"✓ {len(future)} reuniones scraped")
                for m in future[:3]:
                    print(f"  {m['label']} · {m['date']} → {[(p['label'], p['prob']) for p in m['probs'][:3]]}")
            else:
                print("✗ Sin reuniones futuras con datos")
        else:
            print(f"✗ Solo {len(meetings)} reuniones — usando fallback")
    except Exception as e:
        print(f"✗ Error: {e}")

    Path("fedwatch_data.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2)
    )
    print(f"\n✓ fedwatch_data.json guardado · {result['source']}")


if __name__ == "__main__":
    main()
