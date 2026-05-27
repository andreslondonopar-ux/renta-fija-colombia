"""
scraper_ust.py — Curva de rendimientos US Treasury
Corre via GitHub Actions → guarda ust_data.json

Fuentes en cascada:
1. US Treasury XML feed (home.treasury.gov) — datos diarios, más recientes
2. FiscalData API (api.fiscaldata.treasury.gov) — datos mensuales promedio, backup
"""
import json, requests, re, datetime
from pathlib import Path

HDR = {'User-Agent': 'Mozilla/5.0 (compatible; renta-fija-bot/1.0)'}
TODAY = datetime.date.today().isoformat()

# Mapa de plazos: (label_display, años, campo_XML, tipo_FiscalData)
UST_MAP = [
    ("1M",  0.083, "BC_1MONTH",  "Treasury Bills"),
    ("3M",  0.25,  "BC_3MONTH",  "Treasury Bills"),
    ("6M",  0.5,   "BC_6MONTH",  "Treasury Bills"),
    ("1Y",  1,     "BC_1YEAR",   "Treasury Notes"),
    ("2Y",  2,     "BC_2YEAR",   "Treasury Notes"),
    ("3Y",  3,     "BC_3YEAR",   "Treasury Notes"),
    ("5Y",  5,     "BC_5YEAR",   "Treasury Notes"),
    ("7Y",  7,     "BC_7YEAR",   "Treasury Notes"),
    ("10Y", 10,    "BC_10YEAR",  "Treasury Notes"),
    ("20Y", 20,    "BC_20YEAR",  "Treasury Bonds"),
    ("30Y", 30,    "BC_30YEAR",  "Treasury Bonds"),
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


# ── Fuente 1: Treasury XML feed (datos diarios) ───────────────
def fetch_xml():
    today = datetime.date.today()
    for delta in [0, -1, -2]:  # intenta mes actual y 2 meses atrás
        d = today.replace(day=1)
        for _ in range(abs(delta)):
            d = (d - datetime.timedelta(days=1)).replace(day=1)
        yyyymm = d.strftime("%Y%m")
        url = (
            f"https://home.treasury.gov/resource-center/data-chart-center/"
            f"interest-rates/pages/xml?data=daily_treasury_yield_curve"
            f"&field_tdr_date_value={yyyymm}"
        )
        try:
            r = requests.get(url, headers=HDR, timeout=25)
            if not r.ok:
                print(f"XML {yyyymm}: HTTP {r.status_code}")
                continue
            text = r.text
            entries = re.findall(r'<entry>(.*?)</entry>', text, re.DOTALL)
            if not entries:
                print(f"XML {yyyymm}: sin entries")
                continue
            # Tomar el último entry (más reciente)
            last = entries[-1]
            dm = re.search(r'<NEW_DATE>(.*?)</NEW_DATE>', last)
            date_str = dm.group(1)[:10] if dm else today.isoformat()
            rates = []
            for plazo, years, field, _ in UST_MAP:
                m = re.search(rf'<{field}>(.*?)</{field}>', last)
                if m:
                    try:
                        val = float(m.group(1))
                        if 0 < val < 25:
                            rates.append({"plazo": plazo, "years": years, "tir": val})
                    except:
                        pass
            if len(rates) >= 7:
                print(f"✓ XML: {len(rates)} plazos · {date_str}")
                return {"date": date_str, "rates": rates, "source": "US Treasury XML"}
            else:
                print(f"XML {yyyymm}: solo {len(rates)} plazos, insuficiente")
        except Exception as e:
            print(f"XML {yyyymm}: {e}")
    return None


# ── Fuente 2: FiscalData API (datos mensuales promedio) ───────
# https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/avg_interest_rates
# Nota: estos son promedios mensuales, no tasas spot — usar como backup
def fetch_fiscaldata():
    """
    Alternativa: usar la API de FiscalData para tasas promedio.
    Los campos son avg_interest_rate_amt por security_type_desc y record_date.
    """
    try:
        url = (
            "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
            "/v2/accounting/od/avg_interest_rates"
            "?fields=record_date,security_desc,avg_interest_rate_amt"
            "&filter=record_date:gte:2026-01-01"
            "&sort=-record_date"
            "&page[size]=50"
            "&format=json"
        )
        r = requests.get(url, headers=HDR, timeout=20)
        if not r.ok:
            print(f"FiscalData: HTTP {r.status_code}")
            return None
        data = r.json().get("data", [])
        if not data:
            print("FiscalData: sin datos")
            return None

        # Tomar la fecha más reciente
        latest_date = data[0]["record_date"]
        latest = [d for d in data if d["record_date"] == latest_date]
        print(f"FiscalData: {len(latest)} registros · {latest_date}")

        # Mapear security_desc → plazos aproximados
        # Los tipos disponibles son: Treasury Bills, Treasury Notes, Treasury Bonds, TIPS, etc.
        # Esto da un promedio, no la curva spot exacta
        type_map = {
            "Treasury Bills":  [("3M", 0.25), ("6M", 0.5)],
            "Treasury Notes":  [("2Y", 2), ("5Y", 5), ("10Y", 10)],
            "Treasury Bonds":  [("30Y", 30)],
        }
        rates = []
        for rec in latest:
            desc = rec.get("security_desc","")
            rate = rec.get("avg_interest_rate_amt")
            if not rate: continue
            try: rate = float(rate)
            except: continue
            for desc_key, plazos in type_map.items():
                if desc_key.lower() in desc.lower():
                    for plazo, years in plazos:
                        if not any(r["plazo"]==plazo for r in rates):
                            rates.append({"plazo":plazo,"years":years,"tir":rate})

        if len(rates) >= 4:
            return {"date": latest_date, "rates": rates, "source": "FiscalData API (promedios mensuales)"}
    except Exception as e:
        print(f"FiscalData: {e}")
    return None


# ── MAIN ─────────────────────────────────────────────────────
def main():
    result = fetch_xml()

    if not result:
        print("XML falló, intentando FiscalData...")
        result = fetch_fiscaldata()

    if not result:
        print("Ambas fuentes fallaron, usando fallback")
        result = {
            "date": TODAY,
            "rates": FALLBACK,
            "source": "fallback"
        }

    result["updated"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    # Actualizar también macro_data.json si existe (para compatibilidad)
    macro_path = Path("macro_data.json")
    if macro_path.exists():
        try:
            macro = json.loads(macro_path.read_text())
            macro["ust"] = result
            macro_path.write_text(json.dumps(macro, ensure_ascii=False, indent=2))
            print("✓ macro_data.json actualizado con UST")
        except Exception as e:
            print(f"macro_data.json: {e}")

    # También guardar archivo independiente
    Path("ust_data.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n✓ ust_data.json: {len(result['rates'])} plazos · {result['date']} · {result['source']}")
    for r in result["rates"]:
        print(f"  {r['plazo']:4s}: {r['tir']:.2f}%")


if __name__ == "__main__":
    main()
