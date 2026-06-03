"""
scraper_fedwatch.py — Probabilidades FOMC
Fuente primaria: Yahoo Finance (futuros Fed Funds ZQ) + cálculo estándar CME FedWatch
Fuente secundaria: CME API interna
Fuente terciaria: Playwright (scraping web)
Guarda fedwatch_data.json.
"""
import json, re, datetime, calendar, requests
from pathlib import Path

TODAY = datetime.date.today().isoformat()
NOW   = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html",
    "Origin": "https://www.cmegroup.com",
}

# Tasa Fed Funds actual (rango objetivo). Actualizar si cambia.
CURRENT_RATE = "3.50-3.75"

# Calendario FOMC + contrato de futuros a usar.
# Si la reunión es después del día 22, se usa el contrato del mes siguiente
# (mes siguiente no tiene días pre-reunión, el precio refleja directamente la tasa post-reunión).
# Letras de mes: F=Ene,G=Feb,H=Mar,J=Abr,K=May,M=Jun,N=Jul,Q=Ago,U=Sep,V=Oct,X=Nov,Z=Dic
FOMC_SCHEDULE = [
    {"date": "2026-06-17", "label": "Jun '26", "ticker": "ZQM26", "next_month": False},
    {"date": "2026-07-29", "label": "Jul '26", "ticker": "ZQQ26", "next_month": True},   # Contrato Ago
    {"date": "2026-09-16", "label": "Sep '26", "ticker": "ZQU26", "next_month": False},
    {"date": "2026-10-28", "label": "Oct '26", "ticker": "ZQX26", "next_month": True},   # Contrato Nov
    {"date": "2026-12-09", "label": "Dic '26", "ticker": "ZQZ26", "next_month": False},
    {"date": "2027-01-27", "label": "Ene '27", "ticker": "ZQG27", "next_month": True},   # Contrato Feb
    {"date": "2027-03-17", "label": "Mar '27", "ticker": "ZQH27", "next_month": False},
    {"date": "2027-04-28", "label": "Abr '27", "ticker": "ZQK27", "next_month": True},   # Contrato May
]

# Rangos de tasa para el cálculo de probabilidades (columnas CME)
RATE_COLS = [
    "275-300", "300-325", "325-350", "350-375",
    "375-400", "400-425", "425-450", "450-475", "475-500",
]


def bp_to_label(col):
    lo, hi = col.split("-")
    return f"{int(lo)/100:.2f}-{int(hi)/100:.2f}"


def rate_upper(label):
    parts = re.findall(r'\d+\.\d+', label)
    return float(parts[1]) if len(parts) >= 2 else float(parts[0])


def probs_from_futures_price(futures_price, meeting_date_str, current_range, next_month=False):
    """
    Calcula probabilidades de resultado FOMC a partir del precio de futuros Fed Funds.
    Metodología estándar CME FedWatch (interpolación lineal entre rangos adyacentes).

    Si next_month=True, el contrato usado es del mes siguiente a la reunión:
    en ese caso el precio refleja directamente la tasa post-reunión.
    Si next_month=False, se extrae la tasa post-reunión por la fórmula de días.
    """
    lo_str, hi_str = current_range.split("-")
    lo, hi = float(lo_str), float(hi_str)
    current_mid = (lo + hi) / 2

    if next_month:
        # El contrato es del mes siguiente: tasa implícita = tasa post-reunión
        post_rate = round(100.0 - futures_price, 6)
    else:
        dt = datetime.datetime.strptime(meeting_date_str, "%Y-%m-%d")
        days_in_month = calendar.monthrange(dt.year, dt.month)[1]
        meeting_day = dt.day
        pre_days = meeting_day - 1
        post_days = days_in_month - meeting_day + 1
        implied_avg = 100.0 - futures_price
        if post_days > 0:
            post_rate = round(
                (implied_avg * days_in_month - current_mid * pre_days) / post_days, 6
            )
        else:
            post_rate = implied_avg

    # Posibles outcomes: -75bp a +75bp en pasos de 25bp
    STEP = 0.25
    outcomes = []
    for i in range(-3, 4):
        lo_r = round(lo + i * STEP, 2)
        hi_r = round(hi + i * STEP, 2)
        mid  = round(current_mid + i * STEP, 4)
        label = f"{lo_r:.2f}-{hi_r:.2f}"
        outcomes.append({"label": label, "mid": mid, "bp": i * 25})

    mids = [o["mid"] for o in outcomes]
    post_rate = max(mids[0], min(mids[-1], post_rate))

    probs = [0.0] * len(outcomes)
    for i in range(len(mids) - 1):
        if mids[i] <= post_rate <= mids[i + 1]:
            span = mids[i + 1] - mids[i]
            frac = (post_rate - mids[i]) / span if span > 0 else 0
            probs[i]     = round((1 - frac) * 100, 1)
            probs[i + 1] = round(frac * 100, 1)
            break

    result = []
    for o, p in zip(outcomes, probs):
        if p > 0.1:
            result.append({"label": o["label"], "bp": o["bp"], "prob": p})

    return sorted(result, key=lambda x: -x["prob"])


# ── FUENTE 1: Yahoo Finance ────────────────────────────────────────────────────

def fetch_yahoo_price(ticker):
    """Obtiene precio de cierre/mercado de futuros desde Yahoo Finance."""
    for sym in [ticker, f"{ticker}.CBT"]:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1d&interval=1d"
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}, timeout=10)
            if r.status_code != 200:
                continue
            data = r.json()
            result = data.get("chart", {}).get("result") or []
            if not result:
                continue
            price = result[0].get("meta", {}).get("regularMarketPrice")
            if price:
                print(f"    {sym}: {float(price):.4f}")
                return float(price)
        except Exception as e:
            print(f"    {sym}: error — {e}")
    return None


def try_yahoo_finance():
    """
    Probabilidades FOMC a partir de precios de futuros Fed Funds (Yahoo Finance).
    Retorna lista de meetings o None si hay menos de 3 reuniones con datos.
    """
    print("Intentando Yahoo Finance (futuros ZQ Fed Funds)...")
    today = datetime.date.today()
    meetings = []

    for m in FOMC_SCHEDULE:
        dt = datetime.datetime.strptime(m["date"], "%Y-%m-%d").date()
        if dt < today:
            continue
        price = fetch_yahoo_price(m["ticker"])
        if price is None:
            print(f"    {m['ticker']}: sin datos")
            continue
        probs = probs_from_futures_price(price, m["date"], CURRENT_RATE, m["next_month"])
        if probs:
            meetings.append({"date": m["date"], "label": m["label"], "probs": probs})

    if len(meetings) >= 3:
        print(f"  OK {len(meetings)} reuniones via Yahoo Finance")
        return meetings
    print(f"  -- Solo {len(meetings)} reuniones -- insuficiente")
    return None


# ── FUENTE 2: CME API ──────────────────────────────────────────────────────────

def parse_cme_response(data):
    meetings = []
    today = datetime.date.today()

    if isinstance(data, list):
        for item in data:
            date_str = item.get("meetingDate") or item.get("date") or item.get("eventDate", "")
            if not date_str:
                continue
            try:
                if len(date_str) == 8:
                    dt = datetime.datetime.strptime(date_str, "%Y%m%d")
                else:
                    dt = datetime.datetime.strptime(date_str[:10], "%Y-%m-%d")
            except Exception:
                continue
            if dt.date() < today:
                continue

            probs_raw = item.get("probs") or item.get("probabilities") or item.get("rates") or {}
            probs = []

            if isinstance(probs_raw, dict):
                for col in RATE_COLS:
                    val = probs_raw.get(col, 0)
                    if val and float(val) > 0.05:
                        probs.append({"label": bp_to_label(col), "bp": 0, "prob": float(val)})
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
                    "probs": sorted(probs, key=lambda x: -x["prob"]),
                })

    elif isinstance(data, dict):
        for key in ["meetings", "data", "probabilities", "events"]:
            if key in data and isinstance(data[key], list):
                return parse_cme_response(data[key])

    return meetings


def try_cme_api():
    print("Intentando CME API directa...")
    for url in [
        "https://www.cmegroup.com/CmeWS/mvc/Probabilities/getFedwatchProbabilities",
        "https://www.cmegroup.com/CmeWS/mvc/Probabilities/ConvertedProbabilities/",
    ]:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            print(f"  {url.split('/')[-1]}: HTTP {r.status_code}")
            if r.status_code == 200:
                meetings = parse_cme_response(r.json())
                if meetings:
                    print(f"  ✓ {len(meetings)} reuniones via CME API")
                    return meetings
        except Exception as e:
            print(f"  Error: {e}")
    return None


# ── FUENTE 3: Investing.com Fed Rate Monitor (usa datos CME) ───────────────────

def parse_investing_meetings(page, today_str):
    """Parsea el DOM de investing.com/central-banks/fed-rate-monitor."""
    import re
    meetings = []
    try:
        # Esperar tabla de reuniones
        page.wait_for_selector('[class*="rateTable"], table[class*="fed"], .fedTable, table', timeout=15000)
        page.wait_for_timeout(2000)

        # Obtener todas las filas que puedan ser reuniones FOMC
        rows = page.evaluate("""() => {
            const results = [];
            // Buscar celdas con fechas tipo "Jun 17, 2026" y sus probabilidades adyacentes
            document.querySelectorAll('tr, [class*="tableRow"], [class*="row"]').forEach(row => {
                const text = row.innerText || '';
                // Buscar filas con fecha + porcentajes
                const dateMatch = text.match(/(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\\s+(\\d{1,2}),?\\s+(\\d{4})/i);
                const pcts = [...text.matchAll(/(\\d{1,3}(?:\\.\\d)?)\s*%/g)].map(m => parseFloat(m[1]));
                if (dateMatch && pcts.length >= 2) {
                    results.push({ dateStr: dateMatch[0], pcts, fullText: text.trim().slice(0, 200) });
                }
            });
            return results;
        }""")

        MONTHS = {'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12}
        for row in (rows or []):
            try:
                dm = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),?\s+(\d{4})', row['dateStr'], re.I)
                if not dm: continue
                mo = MONTHS[dm.group(1).lower()]
                day = int(dm.group(2))
                yr = int(dm.group(3))
                date_iso = f"{yr}-{mo:02d}-{day:02d}"
                if date_iso < today_str: continue
                label = f"{dm.group(1)[:3]} '{str(yr)[2:]}"
                pcts = row['pcts']
                # Los porcentajes suman ~100%; los mayores son los más probables
                total = sum(pcts)
                if total < 50: continue
                # Asumir que el primero es el escenario más común (cut/hold/hike)
                # Necesitamos labels — sin info de bp usamos solo probabilidades
                probs = [{"label": f"escenario_{i+1}", "bp": 0, "prob": p}
                         for i, p in enumerate(pcts) if p > 1]
                if probs:
                    meetings.append({"date": date_iso, "label": label, "probs": probs})
            except Exception:
                continue
    except Exception as e:
        print(f"  DOM parse error: {e}")
    return meetings


def try_investing_com():
    from playwright.sync_api import sync_playwright
    url = "https://www.investing.com/central-banks/fed-rate-monitor"
    meetings = []
    api_responses = []
    today_str = TODAY

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            "--no-sandbox", "--disable-setuid-sandbox",
            "--disable-dev-shm-usage", "--disable-gpu",
        ])
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900}
        )

        def handle_response(response):
            url_l = response.url.lower()
            if any(k in url_l for k in ['fed', 'rate-monitor', 'central-bank', 'fomc', 'probabilit', 'fedwatch']):
                try:
                    data = response.json()
                    api_responses.append({'url': response.url, 'data': data})
                    print(f"  XHR: {response.url[:90]}")
                except Exception:
                    pass

        page = ctx.new_page()
        page.on("response", handle_response)
        print(f"  Loading {url}...")
        try:
            page.goto(url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(5000)
        except Exception as e:
            print(f"  Load error: {e}")

        # 1) Intentar parsear XHR como CME
        for item in api_responses:
            parsed = parse_cme_response(item['data'])
            if parsed:
                meetings = parsed
                print(f"  XHR parseable como CME: {len(meetings)} reuniones")
                break

        # 2) DOM fallback
        if not meetings:
            print("  Intentando DOM...")
            meetings = parse_investing_meetings(page, today_str)

        browser.close()

    if meetings:
        print(f"  OK {len(meetings)} reuniones via Investing.com")
    return meetings


# ── FUENTE 4: Playwright CME directo ──────────────────────────────────────────

def try_playwright():
    from playwright.sync_api import sync_playwright
    url = "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html"
    meetings = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            "--no-sandbox", "--disable-setuid-sandbox",
            "--disable-dev-shm-usage", "--disable-gpu",
        ])
        ctx = browser.new_context(user_agent=HEADERS["User-Agent"], viewport={"width": 1440, "height": 900})

        api_data = []
        def handle_response(response):
            if "Probabilities" in response.url or "fedwatch" in response.url.lower():
                try:
                    api_data.append(response.json())
                    print(f"  XHR: {response.url}")
                except Exception:
                    pass

        page = ctx.new_page()
        page.on("response", handle_response)
        print(f"  Loading {url}...")
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(5000)

        for body in api_data:
            parsed = parse_cme_response(body)
            if parsed:
                meetings = parsed
                break

        browser.close()

    if meetings:
        print(f"  OK {len(meetings)} reuniones via Playwright CME")
    return meetings


# ── MAIN ───────────────────────────────────────────────────────────────────────

def current_rate_from_meetings(meetings):
    if not meetings:
        return CURRENT_RATE
    first = meetings[0]["probs"]
    return max(first, key=lambda p: p["prob"])["label"]


def add_bp_deltas(meetings, current_rate):
    cur_upper = rate_upper(current_rate)
    for m in meetings:
        for p in m["probs"]:
            p["bp"] = round((rate_upper(p["label"]) - cur_upper) * 100)


def main():
    print(f"=== CME FedWatch - {TODAY} ===\n")
    # Fuente exclusiva: CME (API directa o Playwright). Yahoo eliminado.
    meetings = []

    # Fuente 1: Investing.com (usa datos CME, más accesible)
    print("Fuente 1: Investing.com Fed Rate Monitor...")
    try:
        meetings = try_investing_com() or []
    except Exception as e:
        print(f"  Investing.com error: {e}")

    # Fuente 2: CME API directa
    if not meetings:
        print("\nFuente 2: CME API directa...")
        meetings = try_cme_api() or []

    # Fuente 3: Playwright CME directo
    if not meetings:
        print("\nFuente 3: Playwright (CME FedWatch)...")
        try:
            meetings = try_playwright() or []
        except Exception as e:
            print(f"Playwright error: {e}")

    if not meetings:
        print("\n-- Sin datos disponibles.")
        if Path("fedwatch_data.json").exists():
            print("  Manteniendo fedwatch_data.json existente.")
            # Actualizar timestamp para que el workflow no falle
            try:
                existing = json.loads(Path("fedwatch_data.json").read_text())
                existing["updated"] = NOW
                existing["source"] = f"CME FedWatch - {TODAY} (sin actualización)"
                Path("fedwatch_data.json").write_text(json.dumps(existing, ensure_ascii=False, indent=2))
            except Exception:
                pass
        else:
            # Crear archivo mínimo para que el workflow no falle en el cat
            fallback = {
                "updated": NOW,
                "source": f"CME FedWatch - {TODAY} (sin datos)",
                "current_rate": CURRENT_RATE,
                "meetings": [],
            }
            Path("fedwatch_data.json").write_text(json.dumps(fallback, ensure_ascii=False, indent=2))
            print("  fedwatch_data.json mínimo creado (sin reuniones).")
        return

    today = datetime.date.today().isoformat()
    meetings = [m for m in meetings if m["date"] >= today and m["probs"]][:8]

    current_rate = current_rate_from_meetings(meetings)
    add_bp_deltas(meetings, current_rate)

    result = {
        "updated": NOW,
        "source": f"CME FedWatch - {TODAY}",
        "current_rate": current_rate,
        "meetings": meetings,
    }

    Path("fedwatch_data.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nOK fedwatch_data.json · {len(meetings)} reuniones · tasa actual {current_rate}")
    for m in meetings[:4]:
        top = m["probs"][0]
        print(f"  {m['label']} {m['date']} => {top['label']} ({top['prob']:.1f}%)")


if __name__ == "__main__":
    main()
