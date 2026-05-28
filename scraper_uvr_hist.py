"""
scraper_uvr_hist.py — Actualiza datos_uvr.json con los ultimos valores UVR de BanRep.

Estrategias (en orden):
  1. API SERANKUA de BanRep (CSV directo)
  2. Playwright en pagina BanRep buscando link de descarga Excel/CSV
  3. Calculo proyectado (UVR sube con IPC mensual conocido)
"""
import json, re, csv, io
from datetime import date, timedelta
from pathlib import Path

TODAY = date.today().isoformat()
DATA_FILE = Path("datos_uvr.json")


def load_existing():
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"updated": TODAY, "source": "BanRep", "data": {}}


def last_date_in_data(data_dict):
    if not data_dict:
        return None
    return max(data_dict.keys())


def try_serankua_api():
    """
    Intenta descargar UVR via API SERANKUA de BanRep.
    BanRep tiene endpoints para series estadisticas.
    """
    import requests

    endpoints = [
        # URL directa de serie UVR
        "https://totoro.banrep.gov.co/analytics/saw.dll?Download&PortalPath=%2Fshared%2FSeries%20Estadisticas%2F_inicio%2FInicio&Action=Navigate&path=%2Fshared%2FSeries%20Estadisticas%2FUvr%2FUvr&Extension=csv&NQUser=publico&NQPassword=publico123&lang=es",
        # Alternativas
        "https://www.banrep.gov.co/es/estadisticas/indice-uvr?archivo=csv",
    ]

    for url in endpoints:
        try:
            import requests as req
            r = req.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200 and len(r.content) > 500:
                print("SERANKUA OK: %d bytes" % len(r.content))
                return r.text
        except Exception as e:
            print("SERANKUA error: %s" % e)
    return None


def parse_csv_uvr(text):
    """Parsea CSV de BanRep UVR. Formatos posibles: fecha,valor o columnas multiples."""
    entries = {}
    try:
        reader = csv.reader(io.StringIO(text), delimiter=";")
        for row in reader:
            if len(row) < 2:
                # Intentar con coma
                row = row[0].split(",") if row else row
            if len(row) < 2:
                continue
            date_cell = row[0].strip().strip('"')
            val_cell  = row[1].strip().strip('"').replace(",", ".")
            # Formato fecha: DD/MM/YYYY o YYYY-MM-DD
            d = None
            m = re.match(r"(\d{2})/(\d{2})/(\d{4})", date_cell)
            if m:
                d = "%s-%s-%s" % (m.group(3), m.group(2), m.group(1))
            else:
                m = re.match(r"(\d{4})-(\d{2})-(\d{2})", date_cell)
                if m:
                    d = date_cell
            if d and re.match(r"[\d.]+", val_cell):
                try:
                    entries[d] = float(val_cell)
                except Exception:
                    pass
    except Exception as e:
        print("CSV parse error: %s" % e)
    return entries


def try_banrep_playwright():
    """Playwright en BanRep buscando Excel/CSV de UVR."""
    from playwright.sync_api import sync_playwright
    import requests

    url = "https://www.banrep.gov.co/es/estadisticas/indice-uvr"
    found_data = {}

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

            all_links = page.eval_on_selector_all(
                "a[href]",
                "els => els.map(e => ({href: e.href, text: e.textContent.trim()}))"
            )
            dl_links = []
            for item in all_links:
                href = item.get("href", "")
                if any(x in href.lower() for x in [".xlsx", ".xls", ".csv", "download"]):
                    dl_links.append(href)
                    print("UVR link: %s" % href[:100])

            for href in dl_links[:3]:
                try:
                    r = requests.get(href, timeout=30,
                                     headers={"User-Agent": "Mozilla/5.0"})
                    if r.status_code == 200 and len(r.content) > 500:
                        print("Downloaded: %d bytes" % len(r.content))
                        # Intentar parsear como CSV
                        text = r.text
                        entries = parse_csv_uvr(text)
                        if entries:
                            found_data.update(entries)
                            break
                        # Intentar como Excel
                        try:
                            import openpyxl
                            wb = openpyxl.load_workbook(
                                io.BytesIO(r.content), read_only=True)
                            for ws in wb.worksheets:
                                for row in ws.iter_rows(values_only=True):
                                    if len(row) >= 2 and row[0] and row[1]:
                                        d_cell = str(row[0]).strip()
                                        v_cell = str(row[1]).strip()
                                        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", d_cell)
                                        if m:
                                            try:
                                                found_data[d_cell] = float(v_cell)
                                            except Exception:
                                                pass
                        except Exception as xe:
                            print("Excel parse: %s" % xe)
                        break
                except Exception as de:
                    print("Download error: %s" % de)

            # Si no hay links, leer tabla de la pagina
            if not found_data:
                try:
                    rows = page.locator("table tr").all()
                    for row in rows:
                        cells = row.locator("td").all()
                        if len(cells) >= 2:
                            d_cell = cells[0].inner_text().strip()
                            v_cell = cells[1].inner_text().strip().replace(",", ".")
                            m = re.match(r"(\d{2})/(\d{2})/(\d{4})", d_cell)
                            if m:
                                iso = "%s-%s-%s" % (m.group(3), m.group(2), m.group(1))
                                try:
                                    found_data[iso] = float(v_cell)
                                except Exception:
                                    pass
                except Exception as te:
                    print("Table scrape: %s" % te)

        except Exception as e:
            print("BanRep playwright error: %s" % e)
        finally:
            browser.close()

    return found_data


def main():
    print("=== Actualizando datos_uvr.json ===")
    existing = load_existing()
    data_dict = existing.get("data", {})

    last_d = last_date_in_data(data_dict)
    print("Ultima fecha en JSON: %s" % (last_d or "ninguna"))

    new_entries = {}

    # --- Estrategia 1: SERANKUA ---
    csv_text = None
    try:
        csv_text = try_serankua_api()
    except Exception as e:
        print("SERANKUA: %s" % e)

    if csv_text:
        parsed = parse_csv_uvr(csv_text)
        if parsed:
            # Solo entradas mas recientes
            for d, v in parsed.items():
                if last_d is None or d > last_d:
                    new_entries[d] = v
            print("SERANKUA: %d entradas nuevas" % len(new_entries))

    # --- Estrategia 2: Playwright BanRep ---
    if not new_entries:
        try:
            pw_data = try_banrep_playwright()
            for d, v in pw_data.items():
                if last_d is None or d > last_d:
                    new_entries[d] = v
            if new_entries:
                print("Playwright: %d entradas nuevas" % len(new_entries))
        except Exception as e:
            print("Playwright: %s" % e)

    if new_entries:
        data_dict.update(new_entries)
        print("Total nuevas entradas: %d" % len(new_entries))
    else:
        print("Sin nuevas entradas encontradas.")

    existing["data"] = data_dict
    existing["updated"] = TODAY
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
    print("datos_uvr.json guardado -- %d entradas totales" % len(data_dict))


if __name__ == "__main__":
    main()
