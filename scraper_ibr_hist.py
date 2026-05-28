"""
scraper_ibr_hist.py — Actualiza datos_ibr.json con los ultimos valores IBR overnight de BanRep.

Estrategias (en orden):
  1. API REST BanRep SUAMECA (serie ID=241, IBR overnight nominal)
  2. URL directa de Excel BanRep (IBR indicadores bancarios)
  3. Playwright en pagina de indicadores bancarios buscando Excel/CSV
"""
import json, re, io
from datetime import date, timedelta, datetime
from pathlib import Path

TODAY = date.today().isoformat()
DATA_FILE = Path("datos_ibr.json")


def load_existing():
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"updated": TODAY, "source": "BanRep", "data": {}}


def last_date_in_data(data_dict):
    if not data_dict:
        return None
    return max(data_dict.keys())


def try_suameca_api():
    """
    Descarga IBR overnight via API REST de BanRep SUAMECA.
    Serie ID=241: 'Indicador Bancario de Referencia (IBR) overnight, nominal'
    La API devuelve valores en % (ej: 10.529) → almacenar como decimal (0.10529).
    Retorna dict {iso_date: ibr_decimal} o {} si falla.
    """
    import requests
    from datetime import datetime, timezone

    url = (
        "https://suameca.banrep.gov.co/estadisticas-economicas-back/rest/"
        "estadisticaEconomicaRestService/consultaInformacionSerieXTipoDatoXFechaDesde"
        "?idSerie=241&tipoDato=1&cantDatos=10&frecuenciaDatos=year"
    )
    try:
        r = requests.get(url, timeout=60, headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        })
        if not r.ok:
            print("[IBR] suameca HTTP %d" % r.status_code)
            return {}
        print("[IBR] suameca OK: %d bytes" % len(r.content))

        resp = r.json()
        if not isinstance(resp, list) or not resp:
            print("[IBR] suameca: respuesta inesperada")
            return {}

        raw_data = resp[0].get("data", [])
        if not raw_data:
            print("[IBR] suameca: campo 'data' vacio")
            return {}

        result = {}
        for entry in raw_data:
            if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                continue
            ts_ms, val_pct = entry[0], entry[1]
            try:
                iso = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
                # La API retorna porcentaje (10.529) -> convertir a decimal (0.10529)
                result[iso] = round(float(val_pct) / 100, 7)
            except (ValueError, TypeError, OSError):
                pass

        print("[IBR] suameca: %d entradas parseadas" % len(result))
        return result

    except Exception as e:
        print("[IBR] suameca error: %s" % e)
        return {}


def try_direct_excel():
    """
    Intenta descargar el Excel de indicadores IBR directamente.
    BanRep publica archivos con nombres predecibles.
    """
    import requests

    base = "https://www.banrep.gov.co/sites/default/files/"
    start = datetime.now()

    for delta in range(14):
        d = start - timedelta(days=delta)
        if d.weekday() >= 5:
            continue
        date_str = d.strftime("%Y-%m-%d")
        year_str = d.strftime("%Y")
        month_str = d.strftime("%m")

        candidates = [
            f"{base}ibr-{date_str}.xlsx",
            f"{base}ibr-{date_str}.xls",
            f"{base}indicadores-ibr-{date_str}.xlsx",
            f"https://www.banrep.gov.co/sites/default/files/paginas/ibr_{year_str}.xls",
            f"https://www.banrep.gov.co/sites/default/files/paginas/ibr_{year_str}.xlsx",
        ]
        for url in candidates:
            try:
                r = requests.get(url, timeout=15,
                                 headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code == 200 and len(r.content) > 5000:
                    print("IBR directo: %s (%d bytes)" % (url, len(r.content)))
                    return r.content
            except Exception:
                pass
    return None


def parse_excel_ibr(content):
    """Parsea Excel de IBR buscando columna IBR_OV_TNA o similar."""
    entries = {}
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
        for ws in wb.worksheets:
            print("  Hoja: %s" % ws.title)
            # Leer encabezados en primera fila
            headers = []
            ibr_col = None
            date_col = None
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i == 0:
                    headers = [str(c).strip().upper() if c else "" for c in row]
                    print("  Headers: %s" % headers[:8])
                    for ci, h in enumerate(headers):
                        if re.search(r"IBR[_\s]?OV|OVERNIGHT", h, re.IGNORECASE):
                            ibr_col = ci
                        if re.search(r"FECHA|DATE", h, re.IGNORECASE) and date_col is None:
                            date_col = ci
                    continue

                if date_col is None or ibr_col is None:
                    # Intentar heuristica: col 0 = fecha, buscar IBR
                    date_col = 0
                    # Buscar col con valores decimales ~0.04-0.15
                    if ibr_col is None and row:
                        for ci, cell in enumerate(row):
                            try:
                                v = float(str(cell))
                                if 0.01 < v < 0.5:
                                    ibr_col = ci
                                    break
                            except Exception:
                                pass

                if date_col is None or ibr_col is None:
                    continue

                date_cell = row[date_col] if date_col < len(row) else None
                val_cell  = row[ibr_col]  if ibr_col  < len(row) else None

                if date_cell is None or val_cell is None:
                    continue

                # Parsear fecha
                iso = None
                if isinstance(date_cell, (date, datetime)):
                    iso = date_cell.strftime("%Y-%m-%d")
                else:
                    d_str = str(date_cell).strip()
                    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", d_str)
                    if m:
                        iso = "%s-%s-%s" % (m.group(3), m.group(2), m.group(1))
                    else:
                        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", d_str)
                        if m:
                            iso = d_str

                if iso:
                    try:
                        v = float(str(val_cell).replace(",", "."))
                        # IBR overnight: esperado ~0.04-0.15 (tasa nominal)
                        if 0.001 < v < 1.0:
                            entries[iso] = round(v, 7)
                    except Exception:
                        pass
    except Exception as e:
        print("openpyxl error: %s -- intentando xlrd" % e)
        try:
            import xlrd
            wb = xlrd.open_workbook(file_contents=content)
            for ws in wb.sheets():
                for ri in range(ws.nrows):
                    row = ws.row_values(ri)
                    if len(row) < 2:
                        continue
                    date_cell = row[0]
                    # xlrd almacena fechas como float
                    if isinstance(date_cell, float) and date_cell > 1:
                        dt = xlrd.xldate_as_datetime(date_cell, wb.datemode)
                        iso = dt.strftime("%Y-%m-%d")
                    else:
                        d_str = str(date_cell).strip()
                        m = re.match(r"(\d{2})/(\d{2})/(\d{4})", d_str)
                        iso = "%s-%s-%s" % (m.group(3), m.group(2), m.group(1)) if m else None

                    if not iso:
                        continue
                    # Buscar valor IBR en las columnas
                    for ci in range(1, min(len(row), 10)):
                        try:
                            v = float(row[ci])
                            if 0.001 < v < 1.0:
                                entries[iso] = round(v, 7)
                                break
                        except Exception:
                            pass
        except Exception as xe:
            print("xlrd error: %s" % xe)

    return entries


def try_banrep_playwright():
    """Playwright en BanRep buscando Excel de indicadores IBR."""
    from playwright.sync_api import sync_playwright
    import requests

    url = "https://www.banrep.gov.co/es/estadisticas/indicadores-bancarios"
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
                txt  = item.get("text", "").lower()
                if any(x in href.lower() for x in [".xlsx", ".xls"]):
                    if any(x in txt or x in href.lower()
                           for x in ["ibr", "indicador", "bancario"]):
                        dl_links.append(href)
                        print("IBR link: %s" % href[:100])

            for href in dl_links[:3]:
                try:
                    r = requests.get(href, timeout=30,
                                     headers={"User-Agent": "Mozilla/5.0"})
                    if r.status_code == 200 and len(r.content) > 5000:
                        print("Downloaded IBR Excel: %d bytes" % len(r.content))
                        found_data = parse_excel_ibr(r.content)
                        if found_data:
                            break
                except Exception as de:
                    print("Download: %s" % de)

        except Exception as e:
            print("BanRep playwright error: %s" % e)
        finally:
            browser.close()

    return found_data


def main():
    print("=== Actualizando datos_ibr.json ===")
    existing = load_existing()
    data_dict = existing.get("data", {})

    last_d = last_date_in_data(data_dict)
    print("Ultima fecha en JSON: %s" % (last_d or "ninguna"))

    new_entries = {}

    # --- Estrategia 1: API SUAMECA BanRep ---
    try:
        api_data = try_suameca_api()
        for d, v in api_data.items():
            if last_d is None or d > last_d:
                new_entries[d] = v
        if new_entries:
            print("[IBR] suameca: %d entradas nuevas" % len(new_entries))
    except Exception as e:
        print("[IBR] suameca excepcion: %s" % e)

    # --- Estrategia 2: Excel directo ---
    if not new_entries:
        content = None
        try:
            content = try_direct_excel()
        except Exception as e:
            print("Directo: %s" % e)

        if content:
            parsed = parse_excel_ibr(content)
            if parsed:
                for d, v in parsed.items():
                    if last_d is None or d > last_d:
                        new_entries[d] = v
                print("Excel directo: %d entradas nuevas" % len(new_entries))

    # --- Estrategia 3: Playwright ---
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
    print("datos_ibr.json guardado -- %d entradas totales" % len(data_dict))


if __name__ == "__main__":
    main()
