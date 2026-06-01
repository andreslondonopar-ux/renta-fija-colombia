"""
scraper_fedwatch.py — Probabilidades FOMC via CME FedWatch
Usa la API interna de CME que alimenta el FedWatch Tool.
Guarda fedwatch_data.json.
"""
import json, re, datetime, requests
from pathlib import Path

TODAY = datetime.date.today().isoformat()
NOW   = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html",
    "Origin": "https://www.cmegroup.com",
}

# Columnas de rango de tasa que muestra CME (en puntos base → porcentaje)
RATE_COLS = [
    "275-300", "300-325", "325-350", "350-375",
    "375-400", "400-425", "425-450", "450-475", "475-500",
]

def bp_to_label(col):
    """'350-375' → '3.50-3.75'"""
    lo, hi = col.split("-")
    return f"{int(lo)/100:.2f}-{int(hi)/100:.2f}"


def rate_upper(label):
    """'3.50-3.75' → 3.75"""
    parts = re.findall(r'\d+\.\d+', label)
    return float(parts[1]) if len(parts) >= 2 else float(parts[0])


def try_cme_api():
    """
    Intenta obtener datos via el endpoint interno de CME FedWatch.
    Retorna lista de meetings o None si falla.
    """
    # Endpoint 1: getFedwatchProbabilities (devuelve tabla completa)
    url1 = "https://www.cmegroup.com/CmeWS/mvc/Probabilities/getFedwatchProbabilities"
    try:
        r = requests.get(url1, headers=HEADERS, timeout=15)
        print(f"  API1 status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            print(f"  API1 keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
            meetings = parse_cme_response(data)
            if meetings:
                return meetings
    except Exception as e:
        print(f"  API1 error: {e}")

    # Endpoint 2: formato alternativo
    url2 = "https://www.cmegroup.com/CmeWS/mvc/Probabilities/ConvertedProbabilities/"
    try:
        r = requests.get(url2, headers=HEADERS, timeout=15)
        print(f"  API2 status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            meetings = parse_cme_response(data)
            if meetings:
                return meetings
    except Exception as e:
        print(f"  API2 error: {e}")

    return None


def parse_cme_response(data):
    """Parsea la respuesta JSON de CME en formato estándar."""
    meetings = []

    # Formato 1: lista de reuniones con probs por rango
    if isinstance(data, list):
        for item in data:
            date_str = item.get("meetingDate") or item.get("date") or item.get("eventDate", "")
            if not date_str:
                continue
            # Normalizar fecha
            try:
                if len(date_str) == 8:  # YYYYMMDD
                    dt = datetime.datetime.strptime(date_str, "%Y%m%d")
                else:
                    dt = datetime.datetime.strptime(date_str[:10], "%Y-%m-%d")
            except:
                continue
            if dt.date() < datetime.date.today():
                continue

            probs_raw = item.get("probs") or item.get("probabilities") or item.get("rates") or {}
            probs = []

            if isinstance(probs_raw, dict):
                for col in RATE_COLS:
                    val = probs_raw.get(col, 0)
                    if val and float(val) > 0.05:
                        label = bp_to_label(col)
                        probs.append({"label": label, "bp": 0, "prob": float(val)})
            elif isinstance(probs_raw, list):
                for p in probs_raw:
                    label = p.get("label") or bp_to_label(p.get("range", ""))
                    prob = float(p.get("probability") or p.get("prob") or 0)
                    if prob > 0.05:
                        probs.append({"label": label, "bp": 0, "prob": prob})

            if probs:
                meetings.append({
                    "date": dt.strftime("%Y-%m-%d"),
                    "label": dt.strftime("%b '%y"),
                    "probs": sorted(probs, key=lambda x: -x["prob"])
                })

    # Formato 2: dict con lista de meetings
    elif isinstance(data, dict):
        for key in ["meetings", "data", "probabilities", "events"]:
            if key in data and isinstance(data[key], list):
                return parse_cme_response(data[key])

    return meetings


def try_playwright():
    """Scrape via Playwright como fallback al API."""
    from playwright.sync_api import sync_playwright

    url = "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html"
    meetings = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            '--no-sandbox', '--disable-setuid-sandbox',
            '--disable-dev-shm-usage', '--disable-gpu',
        ])
        ctx = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1440, "height": 900},
        )

        # Interceptar llamadas XHR para capturar los datos
        api_data = []
        def handle_response(response):
            if "Probabilities" in response.url or "fedwatch" in response.url.lower():
                try:
                    body = response.json()
                    api_data.append(body)
                    print(f"  XHR capturado: {response.url}")
                except:
                    pass

        page = ctx.new_page()
        page.on("response", handle_response)

        print(f"  Abriendo {url}...")
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(5000)

        # Intentar parsear XHR capturados
        for body in api_data:
            parsed = parse_cme_response(body)
            if parsed:
                meetings = parsed
                print(f"  ✓ {len(meetings)} reuniones via XHR")
                break

        if not meetings:
            # Leer tabla del DOM
            print("  Intentando leer tabla del DOM...")
            try:
                # Esperar la tabla de probabilidades
                page.wait_for_selector("table", timeout=15000)
                rows = page.locator("table tr").all()
                print(f"  Filas encontradas: {len(rows)}")

                # Buscar cabecera con rangos de tasa
                header_cols = []
                date_pattern = re.compile(
                    r'(\d{1,2}/\d{1,2}/\d{4})', re.I
                )
                pct_pattern = re.compile(r'^(\d+\.?\d*)%$')

                current_meeting = None
                for row in rows:
                    rt = row.inner_text().strip()
                    cells = [c.strip() for c in rt.split('\t') if c.strip()]
                    if not cells:
                        cells = [c.strip() for c in rt.split('\n') if c.strip()]

                    # Detectar fila de cabecera con rangos (275-300, etc.)
                    if any(re.match(r'^\d{3}-\d{3}$', c) for c in cells):
                        header_cols = cells
                        print(f"  Cabecera: {header_cols}")
                        continue

                    # Detectar fila de fecha de reunión
                    dm = date_pattern.search(cells[0]) if cells else None
                    if dm and header_cols:
                        try:
                            dt = datetime.datetime.strptime(dm.group(1), "%m/%d/%Y")
                            if dt.date() >= datetime.date.today():
                                current_meeting = {
                                    "date": dt.strftime("%Y-%m-%d"),
                                    "label": dt.strftime("%b '%y"),
                                    "probs": []
                                }
                                # Parsear probabilidades de la misma fila
                                pct_vals = []
                                for c in cells[1:]:
                                    c2 = c.replace('%', '').strip()
                                    try:
                                        pct_vals.append(float(c2))
                                    except:
                                        pct_vals.append(0.0)

                                for j, col in enumerate(header_cols):
                                    if j < len(pct_vals) and pct_vals[j] > 0.05:
                                        label = bp_to_label(col)
                                        current_meeting["probs"].append({
                                            "label": label, "bp": 0, "prob": pct_vals[j]
                                        })

                                if current_meeting["probs"]:
                                    current_meeting["probs"].sort(key=lambda x: -x["prob"])
                                    meetings.append(current_meeting)
                        except Exception as e:
                            print(f"  Error fila: {e}")
            except Exception as e:
                print(f"  Error DOM: {e}")

        browser.close()

    return meetings


def current_rate_from_meetings(meetings):
    """
    Infiere la tasa actual: la más probable en el primer meeting ES donde está el Fed hoy.
    (No la más alta — el Fed no está necesariamente en el rango superior del espectro.)
    """
    if not meetings:
        return "3.50-3.75"
    first = meetings[0]["probs"]
    return max(first, key=lambda p: p["prob"])["label"]


def main():
    print(f"=== CME FedWatch · {TODAY} ===\n")

    meetings = []

    # 1. Intentar API directa
    print("Intentando API CME directa...")
    meetings = try_cme_api() or []

    # 2. Fallback: Playwright
    if not meetings:
        print("\nAPI no disponible. Usando Playwright...")
        try:
            meetings = try_playwright() or []
        except Exception as e:
            print(f"Playwright error: {e}")

    if not meetings:
        print("\n✗ No se obtuvieron datos de CME FedWatch.")
        # Si ya existe fedwatch_data.json, no lo sobreescribir
        if Path("fedwatch_data.json").exists():
            print("  Manteniendo fedwatch_data.json existente.")
            return
        print("  No hay datos previos — no se generará archivo.")
        return

    # Filtrar solo reuniones futuras
    meetings = [m for m in meetings if m["date"] >= TODAY and m["probs"]][:8]

    current_rate = current_rate_from_meetings(meetings)
    cur_upper = rate_upper(current_rate)

    # Calcular bp de cada outcome relativo a la tasa actual
    for m in meetings:
        for p in m["probs"]:
            p["bp"] = round((rate_upper(p["label"]) - cur_upper) * 100)

    result = {
        "updated": NOW,
        "source": f"CME FedWatch · {TODAY}",
        "current_rate": current_rate,
        "meetings": meetings,
    }

    Path("fedwatch_data.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2)
    )
    print(f"\n✓ fedwatch_data.json guardado · {len(meetings)} reuniones")
    for m in meetings[:4]:
        top = m["probs"][0]
        print(f"  {m['label']} · {m['date']} → {top['label']} ({top['prob']:.1f}%)")


if __name__ == "__main__":
    main()
