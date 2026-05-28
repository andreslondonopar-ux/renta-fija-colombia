"""
scraper_ipc_hist.py — Actualiza datos_ipc.json con los ultimos datos de IPC de DANE.

Estrategias (en orden):
  1. API JSON de DANE (cifra_inflacion)
  2. Playwright en pagina DANE buscando links de datos
  3. Trading Economics scraping como fallback
"""
import json, re, sys
from datetime import date, datetime
from pathlib import Path

TODAY = date.today().isoformat()
DATA_FILE = Path("datos_ipc.json")


def load_existing():
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"updated": TODAY, "source": "DANE", "data": [], "pub_dates": {}}


def last_entry(data_list):
    if not data_list:
        return None
    return data_list[-1]


def month_key(y, m):
    return f"{y:04d}-{m:02d}"


def try_dane_api():
    """Intenta obtener ultimo IPC desde API de DANE."""
    import requests
    urls = [
        "https://www.dane.gov.co/services/orientacion-ciudadana/cifra_inflacion",
        "https://www.dane.gov.co/services/orientacion-ciudadana/cifras_inflacion.json",
    ]
    for url in urls:
        try:
            r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200:
                continue
            ct = r.headers.get("content-type", "")
            if "json" in ct or r.text.strip().startswith("{"):
                d = r.json()
                print("DANE API: %s" % str(d)[:200])
                return d
        except Exception as e:
            print("DANE API error: %s" % e)
    return None


def try_trading_economics():
    """Scraping de Trading Economics para inflacion Colombia (anual y mensual)."""
    from playwright.sync_api import sync_playwright

    results = {}
    url = "https://tradingeconomics.com/colombia/inflation-cpi"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            "--no-sandbox", "--disable-setuid-sandbox",
            "--disable-dev-shm-usage", "--disable-gpu",
        ])
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(4000)

            # Cerrar popups
            for sel in ["button:has-text('Accept')", "#onetrust-accept-btn-handler"]:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible(timeout=600):
                        btn.click()
                        page.wait_for_timeout(400)
                        break
                except Exception:
                    pass

            text = page.inner_text("body")
            print("TE IPC page len: %d" % len(text))

            # Buscar valor actual de inflacion mensual
            patterns = [
                r"Inflation\s+Rate\s+MoM[^\n]*\n\s*([\d,.]+)",
                r"MoM[^\n]*\n\s*([\d,.]+)",
                r"([\d]+[,.][\d]+)\s*%\s*\n.*[Mm]onthly",
            ]
            for pat in patterns:
                m = re.search(pat, text, re.IGNORECASE)
                if m:
                    try:
                        val = float(m.group(1).replace(",", ".")) / 100
                        results["mom"] = val
                        print("TE MoM: %.4f" % val)
                        break
                    except Exception:
                        pass

            # Buscar serie historica en tablas
            rows = []
            try:
                tbl_rows = page.locator("table tr").all()
                for row in tbl_rows:
                    rt = row.inner_text().strip()
                    # Buscar filas con formato fecha-valor
                    m2 = re.search(
                        r"(\w+\s+\d{4})\s+([\d,.]+)\s+([\d,.]+)", rt
                    )
                    if m2:
                        rows.append(m2.groups())
            except Exception:
                pass
            if rows:
                print("TE table rows: %d" % len(rows))
                results["rows"] = rows

        except Exception as e:
            print("TE IPC error: %s" % e)
        finally:
            browser.close()

    return results


def try_dane_playwright():
    """Playwright en DANE buscando tabla/CSV de IPC."""
    from playwright.sync_api import sync_playwright
    import requests

    url = "https://www.dane.gov.co/index.php/estadisticas-por-tema/precios-y-costos/indice-de-precios-al-consumidor-ipc"
    found_data = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            "--no-sandbox", "--disable-setuid-sandbox",
            "--disable-dev-shm-usage", "--disable-gpu",
        ])
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)

            # Buscar links de excel/csv
            all_links = page.eval_on_selector_all(
                "a[href]",
                "els => els.map(e => ({href: e.href, text: e.textContent.trim()}))"
            )
            for item in all_links:
                href = item.get("href", "")
                txt = item.get("text", "").lower()
                if any(x in href.lower() for x in [".xlsx", ".xls", ".csv"]):
                    if any(x in txt or x in href.lower() for x in ["ipc", "inflacion", "inflation"]):
                        print("DANE link: %s" % href[:100])
                        found_data.append(href)

        except Exception as e:
            print("DANE playwright error: %s" % e)
        finally:
            browser.close()

    return found_data


def parse_month_str(s):
    """Parsea strings de mes como 'Jan 2026', 'enero 2026', '2026-01'."""
    s = s.strip()
    month_map = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        "ene": 1, "abr": 4, "ago": 8, "dic": 12,
    }
    # YYYY-MM format
    m = re.match(r"(\d{4})-(\d{1,2})", s)
    if m:
        return int(m.group(1)), int(m.group(2))
    # "Jan 2026" or "enero 2026"
    m = re.match(r"(\w{3,})\s+(\d{4})", s, re.IGNORECASE)
    if m:
        mon_str = m.group(1)[:3].lower()
        if mon_str in month_map:
            return int(m.group(2)), month_map[mon_str]
    return None, None


def main():
    print("=== Actualizando datos_ipc.json ===")
    existing = load_existing()
    data_list = existing.get("data", [])
    pub_dates = existing.get("pub_dates", {})

    last = last_entry(data_list)
    if last:
        last_y, last_m = last["y"], last["m"]
        print("Ultimo en JSON: %04d-%02d" % (last_y, last_m))
    else:
        last_y, last_m = 0, 0

    new_entries = []

    # --- Estrategia 1: API DANE ---
    dane_result = None
    try:
        dane_result = try_dane_api()
    except Exception as e:
        print("DANE API: %s" % e)

    # La API devuelve un valor puntual; si es mas reciente que el ultimo, lo agrega
    if dane_result and isinstance(dane_result, dict):
        # Intentar extraer year/month/valor del resultado JSON
        # La estructura puede variar; buscamos campos comunes
        for key in ["anio", "year", "vigencia", "periodo"]:
            if key in dane_result:
                try:
                    y = int(str(dane_result[key])[:4])
                    break
                except Exception:
                    pass
        # Si no encontramos estructura util, la API sola no es suficiente

    # --- Estrategia 2: Playwright DANE ---
    try:
        links = try_dane_playwright()
        if links:
            print("DANE playwright: %d links encontrados" % len(links))
    except Exception as e:
        print("DANE playwright: %s" % e)

    # --- Estrategia 3: Trading Economics ---
    te_result = {}
    try:
        te_result = try_trading_economics()
    except Exception as e:
        print("TE: %s" % e)

    # Procesar filas de TE si las hay
    if te_result.get("rows"):
        for row in te_result["rows"]:
            date_str, ann_val, mom_val = row[0], row[1], row[2] if len(row) > 2 else None
            y, m = parse_month_str(date_str)
            if y is None:
                continue
            # Comparar con ultimo
            if y < last_y or (y == last_y and m <= last_m):
                continue
            try:
                mom_pct = float(str(mom_val).replace(",", ".")) / 100
                key = month_key(y, m)
                new_entries.append({"y": y, "m": m, "v": round(mom_pct, 6)})
                print("Nueva entrada TE: %s = %.4f" % (key, mom_pct))
            except Exception:
                pass

    if new_entries:
        # Ordenar y deduplicar
        new_entries.sort(key=lambda x: (x["y"], x["m"]))
        existing_keys = {(e["y"], e["m"]) for e in data_list}
        for e in new_entries:
            if (e["y"], e["m"]) not in existing_keys:
                data_list.append(e)
                existing_keys.add((e["y"], e["m"]))
        print("Nuevas entradas agregadas: %d" % len(new_entries))
    else:
        print("Sin nuevas entradas encontradas.")

    # Guardar
    existing["data"] = data_list
    existing["pub_dates"] = pub_dates
    existing["updated"] = TODAY
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
    print("datos_ipc.json guardado -- %d entradas totales" % len(data_list))


if __name__ == "__main__":
    main()
