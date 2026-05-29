"""
scraper_ust.py — Curva de rendimientos US Treasury
Fuentes:
1. Treasury XML feed (año completo) — field_tdr_date_value=YYYY
2. Treasury CSV directo 
3. FiscalData API — backup
"""
import json, requests, re, datetime
from pathlib import Path

HDR = {'User-Agent': 'Mozilla/5.0 (compatible; renta-fija-bot/1.0)'}
TODAY = datetime.date.today().isoformat()
YEAR  = datetime.date.today().year

UST_MAP = [
    ("1M",  0.083, "BC_1MONTH"),
    ("2M",  0.167, "BC_1_5MONTH"),   # 1.5 month, added Feb 2025
    ("3M",  0.25,  "BC_3MONTH"),
    ("4M",  0.333, "BC_4MONTH"),
    ("6M",  0.5,   "BC_6MONTH"),
    ("1Y",  1,     "BC_1YEAR"),
    ("2Y",  2,     "BC_2YEAR"),
    ("3Y",  3,     "BC_3YEAR"),
    ("5Y",  5,     "BC_5YEAR"),
    ("7Y",  7,     "BC_7YEAR"),
    ("10Y", 10,    "BC_10YEAR"),
    ("20Y", 20,    "BC_20YEAR"),
    ("30Y", 30,    "BC_30YEAR"),
]

FALLBACK = [
    {"plazo":"1M","years":0.083,"tir":4.32},
    {"plazo":"3M","years":0.25, "tir":4.28},
    {"plazo":"6M","years":0.5,  "tir":4.20},
    {"plazo":"1Y","years":1,    "tir":4.05},
    {"plazo":"2Y","years":2,    "tir":3.92},
    {"plazo":"3Y","years":3,    "tir":3.88},
    {"plazo":"5Y","years":5,    "tir":3.95},
    {"plazo":"7Y","years":7,    "tir":4.10},
    {"plazo":"10Y","years":10,  "tir":4.25},
    {"plazo":"20Y","years":20,  "tir":4.68},
    {"plazo":"30Y","years":30,  "tir":4.72},
]


def parse_xml_entry(entry_text):
    """Parse a single XML entry — handles d: namespace prefix"""
    rates = []
    for plazo, years, field in UST_MAP:
        # Match both <d:FIELD> and <FIELD> variants
        m = re.search(rf'<(?:d:)?{field}[^>]*>([\d.]+)</(?:d:)?{field}>', entry_text)
        if m:
            try:
                val = float(m.group(1))
                if 0 < val < 25:
                    rates.append({"plazo": plazo, "years": years, "tir": val})
            except:
                pass
    return rates


def fetch_xml_year(year):
    """Fetch full year XML and return latest entry"""
    url = (f"https://home.treasury.gov/resource-center/data-chart-center/"
           f"interest-rates/pages/xml"
           f"?data=daily_treasury_yield_curve&field_tdr_date_value={year}")
    print(f"  Trying XML year {year}: {url}")
    try:
        r = requests.get(url, headers=HDR, timeout=30)
        print(f"  HTTP {r.status_code}, size={len(r.text)}")
        if not r.ok:
            return None

        text = r.text
        # Find all entries — try both with and without namespace
        entries = re.findall(r'<entry>(.*?)</entry>', text, re.DOTALL)
        if not entries:
            entries = re.findall(r'<m:properties>(.*?)</m:properties>', text, re.DOTALL)
        if not entries:
            print(f"  No entries found. First 500 chars: {text[:500]}")
            return None

        print(f"  Found {len(entries)} entries")
        last = entries[-1]

        # Extract date
        dm = re.search(r'<(?:d:)?NEW_DATE[^>]*>(.*?)</(?:d:)?NEW_DATE>', last)
        date_str = dm.group(1)[:10] if dm else TODAY

        rates = parse_xml_entry(last)
        print(f"  Parsed {len(rates)} rates for {date_str}")
        if len(rates) >= 7:
            return {"date": date_str, "rates": rates, "source": "US Treasury XML"}
    except Exception as e:
        print(f"  Exception: {e}")
    return None


def fetch_csv():
    """Fetch CSV version — simpler format, no XML parsing issues"""
    url = (f"https://home.treasury.gov/resource-center/data-chart-center/"
           f"interest-rates/TextView?type=daily_treasury_yield_curve"
           f"&field_tdr_date_value={YEAR}")
    # The CSV download URL
    csv_url = (f"https://home.treasury.gov/resource-center/data-chart-center/"
               f"interest-rates/pages/xml"
               f"?data=daily_treasury_yield_curve&field_tdr_date_value={YEAR}&format=csv")
    # Actually the direct CSV is:
    direct_csv = (f"https://home.treasury.gov/system/files/276/yield-curve-rates-"
                  f"{YEAR}.csv")
    print(f"  Trying CSV: {direct_csv}")
    try:
        r = requests.get(direct_csv, headers=HDR, timeout=20)
        print(f"  HTTP {r.status_code}")
        if not r.ok:
            return None
        lines = [l for l in r.text.strip().split('\n') if l.strip()]
        if len(lines) < 2:
            return None
        header = lines[0].split(',')
        last = lines[-1].split(',')
        print(f"  CSV headers: {header[:5]}...")
        date_str = last[0].strip()
        
        col_map = {
            "1 Mo": ("1M", 0.083), "2 Mo": ("2M", 0.167), "3 Mo": ("3M", 0.25),
            "4 Mo": ("4M", 0.333), "6 Mo": ("6M", 0.5),
            "1 Yr": ("1Y", 1), "2 Yr": ("2Y", 2), "3 Yr": ("3Y", 3),
            "5 Yr": ("5Y", 5), "7 Yr": ("7Y", 7), "10 Yr": ("10Y", 10),
            "20 Yr": ("20Y", 20), "30 Yr": ("30Y", 30),
        }
        rates = []
        for i, h in enumerate(header):
            h = h.strip()
            if h in col_map and i < len(last):
                try:
                    val = float(last[i].strip())
                    plazo, years = col_map[h]
                    if 0 < val < 25:
                        rates.append({"plazo": plazo, "years": years, "tir": val})
                except:
                    pass
        if len(rates) >= 7:
            print(f"  CSV: {len(rates)} rates for {date_str}")
            return {"date": date_str, "rates": rates, "source": "US Treasury CSV"}
    except Exception as e:
        print(f"  CSV exception: {e}")
    return None


def fetch_fiscaldata():
    """FiscalData API — promedio mensual, solo como backup"""
    print("  Trying FiscalData API...")
    try:
        url = (
            "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
            "/v2/accounting/od/avg_interest_rates"
            "?fields=record_date,security_desc,avg_interest_rate_amt"
            f"&filter=record_date:gte:{YEAR}-01-01"
            "&sort=-record_date&page[size]=50&format=json"
        )
        r = requests.get(url, headers=HDR, timeout=20)
        if not r.ok:
            print(f"  FiscalData HTTP {r.status_code}")
            return None
        data = r.json().get("data", [])
        if not data:
            return None

        latest_date = data[0]["record_date"]
        latest = [d for d in data if d["record_date"] == latest_date]
        print(f"  FiscalData: {len(latest)} registros · {latest_date}")

        # Map security types to approximate maturities
        desc_to_rates = {}
        for rec in latest:
            desc = rec.get("security_desc","")
            rate = rec.get("avg_interest_rate_amt")
            if not rate: continue
            try: desc_to_rates[desc] = float(rate)
            except: continue

        print(f"  Descriptions: {list(desc_to_rates.keys())}")

        # Build approximate yield curve from available types
        rates = []
        bills = desc_to_rates.get("Treasury Bills")
        notes = desc_to_rates.get("Treasury Notes")
        bonds = desc_to_rates.get("Treasury Bonds")

        if bills:
            rates += [{"plazo":"3M","years":0.25,"tir":bills},
                      {"plazo":"6M","years":0.5,"tir":bills}]
        if notes:
            rates += [{"plazo":"2Y","years":2,"tir":notes},
                      {"plazo":"5Y","years":5,"tir":notes},
                      {"plazo":"10Y","years":10,"tir":notes}]
        if bonds:
            rates += [{"plazo":"30Y","years":30,"tir":bonds}]

        if len(rates) >= 4:
            return {"date": latest_date, "rates": rates,
                    "source": "FiscalData API (promedios mensuales — no spot rates)"}
    except Exception as e:
        print(f"  FiscalData exception: {e}")
    return None


def main():
    print(f"=== Scraper UST · {TODAY} ===\n")

    # Fuente 1: XML año actual
    print("Fuente 1: Treasury XML año actual")
    result = fetch_xml_year(YEAR)

    # Fuente 2: XML año anterior (por si el actual aún no tiene datos)
    if not result:
        print(f"\nFuente 2: Treasury XML año {YEAR-1}")
        result = fetch_xml_year(YEAR - 1)

    # Fuente 3: CSV directo
    if not result:
        print("\nFuente 3: Treasury CSV")
        result = fetch_csv()

    # Fuente 4: FiscalData (promedios, no spot)
    if not result:
        print("\nFuente 4: FiscalData API")
        result = fetch_fiscaldata()

    # Fallback
    if not result:
        print("\nTodas las fuentes fallaron — usando fallback")
        result = {"date": TODAY, "rates": FALLBACK, "source": "fallback"}

    result["updated"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Actualizar macro_data.json
    macro_path = Path("macro_data.json")
    if macro_path.exists():
        try:
            macro = json.loads(macro_path.read_text())
            macro["ust"] = result
            macro_path.write_text(json.dumps(macro, ensure_ascii=False, indent=2))
            print("✓ macro_data.json actualizado")
        except Exception as e:
            print(f"macro_data.json error: {e}")

    # Cargar historial del archivo anterior (máx 5 snapshots = 5 días hábiles)
    ust_history = []
    try:
        if ust_path.exists():
            old_ust = json.loads(ust_path.read_text())
            if old_ust.get('rates') and old_ust.get('date'):
                snap = {
                    'date': old_ust['date'],
                    'rates': [{'plazo': r['plazo'], 'years': r['years'], 'tir': r['tir']}
                              for r in old_ust['rates']]
                }
                ust_history = [snap] + old_ust.get('history', [])
    except Exception as e:
        print(f"Aviso historial UST: {e}")
    result['history'] = ust_history[:5]

    Path("ust_data.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n✓ ust_data.json: {len(result['rates'])} plazos · {result['date']} · {result['source']}")
    for r in result["rates"]:
        print(f"  {r['plazo']:4s}: {r['tir']:.2f}%")


if __name__ == "__main__":
    main()
