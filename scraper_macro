"""
scraper_macro.py — Indicadores macro Colombia + curva UST
Corre via GitHub Actions → guarda macro_data.json

Formato JSON esperado por index.html:
{
  "colombia": {
    "gdp_annual":    {"value": 2.2,   "source": "WorldBank · 2025"},
    "unemployment":  {"value": 8.8,   "source": "WorldBank · 2024"},
    "inflation":     {"value": 5.68,  "source": "DANE · abr 2026"},
    "inflation_mom": {"value": 0.78,  "source": "DANE · abr 2026"},
    "interest_rate": {"value": 11.25, "source": "BanRep · abr 2026"},
  },
  "ust": {
    "date": "2026-05-23",
    "rates": [{"plazo":"1M","years":0.083,"tir":4.32}, ...]
  },
  "fecha": "2026-05-26",
  "updated": "2026-05-26T14:00:00"
}
"""
import json, requests, re, datetime
from pathlib import Path

HDR = {'User-Agent': 'Mozilla/5.0 (compatible; renta-fija-bot/1.0)'}
NOW = datetime.datetime.utcnow()
TODAY = NOW.date().isoformat()

# ── Fallback ─────────────────────────────────────────────────
FALLBACK_COL = {
    "gdp_annual":    {"value": 2.2,   "source": "DANE · T1 2026"},
    "unemployment":  {"value": 8.8,   "source": "DANE · mar 2026"},
    "inflation":     {"value": 5.68,  "source": "DANE · abr 2026"},
    "inflation_mom": {"value": 0.78,  "source": "DANE · abr 2026"},
    "interest_rate": {"value": 11.25, "source": "BanRep · abr 2026"},
}
FALLBACK_UST = {
    "date": "2026-05-23",
    "rates": [
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
}

# ── 1. World Bank ─────────────────────────────────────────────
def wb(code):
    try:
        data = requests.get(
            f"https://api.worldbank.org/v2/country/COL/indicator/{code}?format=json&mrv=3&per_page=3",
            headers=HDR, timeout=15
        ).json()
        for rec in (data[1] if len(data)>1 else []):
            if rec.get("value") is not None:
                return round(float(rec["value"]), 2), rec.get("date","")
    except Exception as e:
        print(f"WB {code}: {e}")
    return None

# ── 2. BanRep tasa ────────────────────────────────────────────
def banrep_tasa():
    for url in [
        "https://www.banrep.gov.co/es/estadisticas/tasas-de-interes-y-sector-financiero",
        "https://www.banrep.gov.co/es/politica-monetaria",
    ]:
        try:
            text = requests.get(url, headers=HDR, timeout=15).text
            for pat in [
                r'(\d{1,2}[,.]\d{2})\s*%\s*(?:anual|e\.a\.?)',
                r'tasa[^<]{0,100}?(\d{1,2}[,.]\d{2})\s*%',
                r'(\d{1,2}[,.]\d{2})\s*%[^<]{0,50}?(?:política|interés)',
            ]:
                m = re.search(pat, text, re.IGNORECASE)
                if m:
                    val = float(m.group(1).replace(',','.'))
                    if 5 < val < 25:  # sanity check
                        return val
        except Exception as e:
            print(f"BanRep {url}: {e}")
    return None

# ── 3. DANE IPC ───────────────────────────────────────────────
def dane_ipc():
    # Socrata datos.gov.co
    try:
        rec = requests.get(
            "https://www.datos.gov.co/resource/cfw5-qfex.json"
            "?$limit=1&$order=fecha+DESC"
            "&$select=fecha,valor_variacion_anual,valor_variacion_mensual",
            headers={**HDR,"Accept":"application/json"}, timeout=12
        ).json()[0]
        return (round(float(rec["valor_variacion_anual"]),2),
                round(float(rec["valor_variacion_mensual"]),2),
                rec["fecha"][:7])
    except Exception as e:
        print(f"DANE Socrata: {e}")

    # DANE web scraping
    try:
        text = requests.get(
            "https://www.dane.gov.co/index.php/estadisticas-por-tema/precios-y-costos/indice-de-precios-al-consumidor-ipc",
            headers=HDR, timeout=15
        ).text
        ma = re.search(r'anual[^<]{0,80}?(\d+[,.]\d+)\s*%', text, re.IGNORECASE)
        mm = re.search(r'mensual[^<]{0,80}?(\d+[,.]\d+)\s*%', text, re.IGNORECASE)
        if ma:
            return (float(ma.group(1).replace(',','.')),
                    float(mm.group(1).replace(',','.')) if mm else 0.0,
                    TODAY)
    except Exception as e:
        print(f"DANE scrape: {e}")
    return None

# ── 4. US Treasury XML ────────────────────────────────────────
UST_MAP = [
    ("1M","BC_1MONTH",0.083), ("2M","BC_2MONTH",0.167),
    ("3M","BC_3MONTH",0.25),  ("6M","BC_6MONTH",0.5),
    ("1Y","BC_1YEAR",1),      ("2Y","BC_2YEAR",2),
    ("3Y","BC_3YEAR",3),      ("5Y","BC_5YEAR",5),
    ("7Y","BC_7YEAR",7),      ("10Y","BC_10YEAR",10),
    ("20Y","BC_20YEAR",20),   ("30Y","BC_30YEAR",30),
]

def ust():
    today = datetime.date.today()
    for delta in [0,-1]:
        d = today.replace(day=1)
        if delta: d = (d - datetime.timedelta(days=1)).replace(day=1)
        url = (f"https://home.treasury.gov/resource-center/data-chart-center/"
               f"interest-rates/pages/xml?data=daily_treasury_yield_curve"
               f"&field_tdr_date_value={d.strftime('%Y%m')}")
        try:
            text = requests.get(url, headers=HDR, timeout=20).text
            entries = re.findall(r'<entry>(.*?)</entry>', text, re.DOTALL)
            if not entries: continue
            last = entries[-1]
            dm = re.search(r'<NEW_DATE>(.*?)</NEW_DATE>', last)
            date_str = dm.group(1)[:10] if dm else today.isoformat()
            rates = []
            for plazo, field, years in UST_MAP:
                m = re.search(rf'<{field}>(.*?)</{field}>', last)
                if m:
                    try: rates.append({"plazo":plazo,"years":years,"tir":float(m.group(1))})
                    except: pass
            if len(rates) >= 6:
                print(f"UST: {len(rates)} plazos · {date_str}")
                return {"date": date_str, "rates": rates}
        except Exception as e:
            print(f"UST {d.strftime('%Y%m')}: {e}")
    return None

# ── MAIN ──────────────────────────────────────────────────────
def main():
    col = dict(FALLBACK_COL)
    sources = []

    # PIB anual
    r = wb("NY.GDP.MKTP.KD.ZG")
    if r:
        col["gdp_annual"] = {"value": r[0], "source": f"WorldBank · {r[1]}"}
        sources.append("WorldBank GDP")
        print(f"PIB: {r[0]}% ({r[1]})")

    # Desempleo
    r = wb("SL.UEM.TOTL.NE.ZS") or wb("SL.UEM.TOTL.ZS")
    if r:
        col["unemployment"] = {"value": r[0], "source": f"WorldBank · {r[1]}"}
        sources.append("WorldBank Unemp")
        print(f"Desempleo: {r[0]}% ({r[1]})")

    # IPC DANE
    r = dane_ipc()
    if r:
        col["inflation"]     = {"value": r[0], "source": f"DANE · {r[2]}"}
        col["inflation_mom"] = {"value": r[1], "source": f"DANE · {r[2]}"}
        sources.append("DANE IPC")
        print(f"IPC: {r[0]}% MoM: {r[1]}%")

    # BanRep
    r = banrep_tasa()
    if r:
        col["interest_rate"] = {"value": r, "source": f"BanRep · {TODAY}"}
        sources.append("BanRep")
        print(f"BanRep: {r}%")

    # UST
    ust_data = ust() or FALLBACK_UST

    result = {
        "colombia": col,
        "ust":      ust_data,
        "fecha":    TODAY,
        "updated":  NOW.strftime("%Y-%m-%dT%H:%M:%S") + "Z",
        "sources":  sources,
    }

    Path("macro_data.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n✓ macro_data.json guardado · fuentes: {sources}")

if __name__ == "__main__":
    main()
