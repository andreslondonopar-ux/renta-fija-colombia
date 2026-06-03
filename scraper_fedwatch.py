"""
scraper_fedwatch.py — Probabilidades FOMC
Fuente: Investing.com Fed Rate Monitor (datos CME Group)
URL: https://www.investing.com/central-banks/fed-rate-monitor

Estructura de la página: una <table> por reunión FOMC con columnas
  Target Rate | Current Probability% | Previous Day | Previous Week
Las fechas de cada reunión están en el DOM adyacente a cada tabla.
"""
import json, re, datetime
from pathlib import Path

TODAY = datetime.date.today().isoformat()
NOW   = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

CURRENT_RATE_FALLBACK = "3.50-3.75"

MONTHS_EN = {
    'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
    'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12,
}

# JavaScript que extrae todas las tablas FOMC con su fecha de reunión
_TABLE_JS = r"""() => {
    function txt(el){ return (el.innerText||el.textContent||'').trim(); }

    const meetings = [];

    for (const tbl of document.querySelectorAll('table')) {
        const firstTh = tbl.querySelector('th');
        if (!firstTh || !txt(firstTh).includes('Target Rate')) continue;

        // Buscar fecha de reunión en el árbol DOM cercano
        let dateFound = null;

        // 1) Subir por ancestros
        let el = tbl;
        for (let i = 0; i < 8; i++) {
            el = el.parentElement;
            if (!el) break;
            const t = txt(el).slice(0, 600);
            const m = t.match(/(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+\d{1,2},?\s+\d{4}/i);
            if (m) { dateFound = m[0]; break; }
        }

        // 2) Hermanos anteriores en cada nivel
        if (!dateFound) {
            let ancestor = tbl.parentElement;
            for (let lvl = 0; lvl < 5 && ancestor; lvl++) {
                let sib = ancestor.previousElementSibling;
                for (let s = 0; s < 6 && sib; s++) {
                    const t = txt(sib).slice(0, 300);
                    const m = t.match(/(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+\d{1,2},?\s+\d{4}/i);
                    if (m) { dateFound = m[0]; break; }
                    sib = sib.previousElementSibling;
                }
                if (dateFound) break;
                ancestor = ancestor.parentElement;
            }
        }

        const rows = [...tbl.querySelectorAll('tbody tr')].map(r =>
            [...r.querySelectorAll('td')].map(c => txt(c))
        );
        if (rows.length > 0) {
            meetings.push({ date: dateFound, rows });
        }
    }

    return meetings;
}"""


# ── Helpers ────────────────────────────────────────────────────────────────────

def parse_date_en(s):
    if not s:
        return None
    m = re.search(
        r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\.?\s+(\d{1,2}),?\s+(\d{4})',
        s, re.I,
    )
    if not m:
        return None
    mo = MONTHS_EN[m.group(1).lower()[:3]]
    return f"{m.group(3)}-{mo:02d}-{int(m.group(2)):02d}"


def parse_rate_range(s):
    """'3.25 - 3.50' o '3.25-3.50' → ('3.25-3.50', 3.50)"""
    m = re.match(r'\s*(\d+\.\d+)\s*[-–—]\s*(\d+\.\d+)\s*', s)
    if not m:
        return None, None
    lo, hi = float(m.group(1)), float(m.group(2))
    return f"{lo:.2f}-{hi:.2f}", hi


def parse_pct(s):
    """'99.4%' o '?' o '' → float"""
    if not s:
        return 0.0
    m = re.search(r'(\d+\.?\d*)', s)
    return float(m.group(1)) if m else 0.0


def rate_upper(label):
    parts = re.findall(r'\d+\.\d+', label)
    return float(parts[1]) if len(parts) >= 2 else float(parts[0])


def detect_current_rate(tables_data):
    """Detecta la tasa actual como el rango más probable en la reunión más próxima."""
    if not tables_data:
        return CURRENT_RATE_FALLBACK
    best_prob, best_label = 0.0, CURRENT_RATE_FALLBACK
    for row in tables_data[0].get('rows', []):
        if len(row) < 2:
            continue
        label, _ = parse_rate_range(row[0])
        prob = parse_pct(row[1])
        if label and prob > best_prob:
            best_prob, best_label = prob, label
    return best_label


def meetings_from_tables(tables_data, current_rate):
    current_upper = rate_upper(current_rate)
    meetings = []
    seen_dates = set()

    for item in tables_data:
        date_iso = parse_date_en(item.get('date', ''))
        if not date_iso or date_iso < TODAY or date_iso in seen_dates:
            continue
        seen_dates.add(date_iso)

        probs = []
        for row in item['rows']:
            if len(row) < 2:
                continue
            label, hi = parse_rate_range(row[0])
            if not label:
                continue
            prob = parse_pct(row[1])
            if prob < 0.1:
                continue
            bp = round((hi - current_upper) * 100)
            probs.append({"label": label, "bp": bp, "prob": prob})

        if probs:
            dt = datetime.datetime.strptime(date_iso, "%Y-%m-%d")
            meetings.append({
                "date":  date_iso,
                "label": f"{dt.strftime('%b')} '{dt.strftime('%y')}",
                "probs": sorted(probs, key=lambda x: -x["prob"]),
            })

    return meetings


# ── Scraper Playwright ─────────────────────────────────────────────────────────

def scrape():
    from playwright.sync_api import sync_playwright

    URL = "https://www.investing.com/central-banks/fed-rate-monitor"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            "--no-sandbox", "--disable-setuid-sandbox",
            "--disable-dev-shm-usage", "--disable-gpu",
        ])
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        page = ctx.new_page()
        print(f"  GET {URL}")
        try:
            page.goto(URL, wait_until="load", timeout=60000)
            page.wait_for_timeout(5000)
        except Exception as e:
            print(f"  Timeout/error (continuando con DOM disponible): {e}")

        tables_data = page.evaluate(_TABLE_JS)
        browser.close()

    print(f"  Tablas FOMC encontradas: {len(tables_data)}")
    if not tables_data:
        return []

    current_rate = detect_current_rate(tables_data)
    print(f"  Tasa actual detectada: {current_rate}")

    meetings = meetings_from_tables(tables_data, current_rate)
    return meetings, current_rate


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print(f"=== FedWatch — Investing.com — {TODAY} ===\n")

    meetings = []
    current_rate = CURRENT_RATE_FALLBACK
    out = Path("fedwatch_data.json")

    try:
        result = scrape()
        if result:
            meetings, current_rate = result
    except Exception as e:
        print(f"Error: {e}")
        import traceback; traceback.print_exc()

    if not meetings:
        print("\n-- Sin datos. Preservando archivo existente.")
        if out.exists():
            try:
                existing = json.loads(out.read_text())
                src = existing.get("source", "")
                if "(sin actualización)" not in src:
                    existing["source"] = src + " (sin actualización)"
                existing["updated"] = NOW
                out.write_text(json.dumps(existing, ensure_ascii=False, indent=2))
            except Exception:
                pass
        else:
            out.write_text(json.dumps({
                "updated":      NOW,
                "source":       f"Investing.com Fed Rate Monitor — {TODAY} (sin datos)",
                "current_rate": current_rate,
                "meetings":     [],
            }, ensure_ascii=False, indent=2))
        return

    meetings = [m for m in meetings if m["date"] >= TODAY and m["probs"]][:8]

    result = {
        "updated":      NOW,
        "source":       f"Investing.com Fed Rate Monitor — {TODAY}",
        "current_rate": current_rate,
        "meetings":     meetings,
    }
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2))

    print(f"\nOK fedwatch_data.json — {len(meetings)} reuniones — tasa actual {current_rate}")
    for m in meetings[:5]:
        top = m["probs"][0]
        print(f"  {m['label']} {m['date']} => {top['label']} ({top['prob']:.1f}% | {top['bp']:+d}bp)")


if __name__ == "__main__":
    main()
