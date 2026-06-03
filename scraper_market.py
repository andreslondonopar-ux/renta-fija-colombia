"""
scraper_market.py — Precios de mercado para el ticker
Fuente: Yahoo Finance (directo, sin proxy — servidor GitHub Actions)
Guarda market_data.json.
"""
import json, datetime, requests
from pathlib import Path

NOW = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

SYMBOLS = [
    # ── FX Colombia + LatAm ──────────────────────────────────────
    {"sym": "USDCOP=X",  "n": "USD/COP",  "dec": 0},
    {"sym": "EURUSD=X",  "n": "EUR/USD",  "dec": 4},
    {"sym": "USDBRL=X",  "n": "USD/BRL",  "dec": 4},
    {"sym": "USDMXN=X",  "n": "USD/MXN",  "dec": 4},
    {"sym": "DX-Y.NYB",  "n": "DXY",      "dec": 2},
    # ── Commodities Colombia ──────────────────────────────────────
    {"sym": "CL=F",      "n": "WTI",      "dec": 2, "suf": " USD"},
    {"sym": "BZ=F",      "n": "Brent",    "dec": 2, "suf": " USD"},
    {"sym": "KC=F",      "n": "Café",     "dec": 2, "suf": " USD"},
    {"sym": "GC=F",      "n": "Oro",      "dec": 0, "suf": " USD"},
    {"sym": "HG=F",      "n": "Cobre",    "dec": 3, "suf": " USD"},
    # ── Índices globales ──────────────────────────────────────────
    {"sym": "^GSPC",     "n": "S&P 500",  "dec": 0},
    {"sym": "^IXIC",     "n": "Nasdaq",   "dec": 0},
    {"sym": "^DJI",      "n": "DOW",      "dec": 0},
    {"sym": "^VIX",      "n": "VIX",      "dec": 2},
    # ── Tasas (clave para renta fija) ─────────────────────────────
    {"sym": "^IRX",      "n": "UST 3M",   "dec": 2, "suf": "%"},
    {"sym": "^FVX",      "n": "UST 5Y",   "dec": 2, "suf": "%"},
    {"sym": "^TNX",      "n": "UST 10Y",  "dec": 2, "suf": "%"},
    {"sym": "^TYX",      "n": "UST 30Y",  "dec": 2, "suf": "%"},
    # ── Crypto ───────────────────────────────────────────────────
    {"sym": "BTC-USD",   "n": "BTC",      "dec": 0, "suf": " USD"},
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def fetch_quote(sym):
    for base in ["query1", "query2"]:
        url = (f"https://{base}.finance.yahoo.com/v8/finance/chart/"
               f"{sym}?interval=1d&range=1d")
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code != 200:
                continue
            meta = r.json()["chart"]["result"][0]["meta"]
            price = meta.get("regularMarketPrice")
            prev  = (meta.get("regularMarketPreviousClose")
                     or meta.get("chartPreviousClose"))
            if price is None:
                continue
            return float(price), float(prev) if prev else None
        except Exception:
            continue
    return None, None


def fmt_price(price, dec):
    if dec == 0:
        return f"{price:,.0f}".replace(",", ".")
    s = f"{price:.{dec}f}"
    # Colombian locale: thousands sep = . decimal sep = ,
    parts = s.split(".")
    int_part = f"{int(parts[0]):,}".replace(",", ".")
    return f"{int_part},{parts[1]}" if len(parts) > 1 else int_part


def main():
    print(f"=== Market Data — {NOW} ===\n")
    items = []

    for cfg in SYMBOLS:
        price, prev = fetch_quote(cfg["sym"])
        if price is None:
            print(f"  SKIP {cfg['sym']}")
            continue

        up      = price >= (prev or price)
        chg_pct = ((price - prev) / prev * 100) if prev else 0.0
        chg_str = ('+' if up else '') + f"{chg_pct:.2f}%"
        val_str = fmt_price(price, cfg["dec"]) + cfg.get("suf", "")

        print(f"  {cfg['n']:10s}  {val_str:>14}  {chg_str}")
        items.append({"n": cfg["n"], "v": val_str, "up": up, "c": chg_str})

    if len(items) < 4:
        print("\nMenos de 4 símbolos — no se actualiza market_data.json")
        return

    result = {"updated": NOW, "items": items}
    Path("market_data.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nOK market_data.json — {len(items)} activos")


if __name__ == "__main__":
    main()
