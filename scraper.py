import json, re, requests
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
import xlrd

URL = "https://www.banrep.gov.co/es/sen-boletines-diarios"


def get_excel_url():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(URL, timeout=60000)
        page.wait_for_timeout(6000)
        all_links = page.eval_on_selector_all(
            'a[href]', 'els => els.map(e => ({href: e.href, text: e.textContent}))'
        )
        browser.close()
    sen_links = []
    for item in all_links:
        href = item.get('href', '')
        if re.search(r'sen[-_]\d{4}', href, re.IGNORECASE):
            sen_links.append(href)
        elif '.xls' in href.lower() and 'sen' in href.lower():
            sen_links.append(href)
    return sen_links[0] if sen_links else None


def try_direct_url():
    base = "https://www.banrep.gov.co/sites/default/files/"
    start = datetime.now()
    for delta in range(7):
        d = start - timedelta(days=delta)
        if d.weekday() >= 5:
            continue
        date_str = d.strftime('%Y-%m-%d')
        for template in [
            f"{base}sen-{date_str}.xls",
            f"{base}sen-{date_str}.xlsx",
        ]:
            try:
                r = requests.get(template, timeout=10,
                                 headers={'User-Agent': 'Mozilla/5.0'})
                if r.status_code == 200 and len(r.content) > 1000:
                    print(f"✓ URL directa: {template}")
                    return template, r.content
            except Exception:
                pass
    return None, None


def decode_tfit_date(codigo):
    """
    Decodifica la fecha de vencimiento del código TFIT.
    Formato: TFIT + XX + DD + MM + YY
    Ejemplo: TFIT05270230 -> 27/02/2030
    """
    num = codigo[4:]  # quita 'TFIT'
    if len(num) < 8:
        return None
    dd = num[2:4]
    mm = num[4:6]
    yy = num[6:8]
    try:
        fecha = datetime.strptime(f"{dd}/{mm}/20{yy}", "%d/%m/%Y")
        return fecha
    except ValueError:
        return None


# Mapeo conocido de código TFIT -> nombre legible (se puede expandir)
NOMBRES_TES = {
    "TFIT11240135": "TES TF 24/01/2035",
    "TFIT34130358": "TES TF 13/03/2058",
    "TFIT16280428": "TES TF 28/04/2028",
    "TFIT08031127": "TES TF 03/11/2027",
    "TFIT16281140": "TES TF 28/11/2040",
    "TFIT16180930": "TES TF 18/09/2030",
    "TFIT21280542": "TES TF 28/05/2042",
    "TFIT05220829": "TES TF 22/08/2029",
    "TFIT05270230": "TES TF 27/02/2030",
    "TFIT11090233": "TES TF 09/02/2033",
    "TFIT31261050": "TES TF 26/10/2050",
    "TFIT16090736": "TES TF 09/07/2036",
    "TFIT23250746": "TES TF 25/07/2046",
    "TFIT10260331": "TES TF 26/03/2031",
    "TFIT16300632": "TES TF 30/06/2032",
    "TFIT16181034": "TES TF 18/10/2034",
}


def parse_xls(content):
    wb = xlrd.open_workbook(file_contents=content)
    tes_data = []
    hoy = datetime.now()

    for sheet_name in wb.sheet_names():
        ws = wb.sheet_by_name(sheet_name)
        print(f"  Hoja: {sheet_name} ({ws.nrows} filas)")

        for row_idx in range(ws.nrows):
            row = ws.row_values(row_idx)

            # Buscar código TFIT en columna 1 (índice 1)
            codigo = ''
            for col in range(min(3, len(row))):
                cell_val = str(row[col]).strip()
                if cell_val.startswith('TFIT'):
                    codigo = cell_val
                    break

            if not codigo:
                continue

            # La TIR de cierre está en columna 15 (Equiv.Cierre)
            try:
                tir = float(row[15])
            except (IndexError, ValueError, TypeError):
                continue

            # Filtrar filas sin TIR válida (operaciones de otro tipo)
            if tir <= 0 or tir > 25:
                continue

            # Decodificar fecha de vencimiento
            fecha_vcto = decode_tfit_date(codigo)
            if fecha_vcto is None:
                continue

            # Calcular plazo en años
            plazo = round((fecha_vcto - hoy).days / 365, 2)
            if plazo <= 0:
                continue

            # Nombre legible
            nombre = NOMBRES_TES.get(codigo, f"TES TF {fecha_vcto.strftime('%d/%m/%Y')}")

            tes_data.append({
                'codigo': codigo,
                'name': nombre,
                'tir': round(tir, 4),
                'plazo': plazo,
                'vencimiento': fecha_vcto.strftime('%Y-%m-%d'),
            })

    # Eliminar duplicados (mismo código, quedar con el de mayor TIR válida)
    vistos = {}
    for t in tes_data:
        c = t['codigo']
        if c not in vistos:
            vistos[c] = t

    resultado = sorted(vistos.values(), key=lambda x: x['plazo'])
    return resultado


def main():
    excel_url = get_excel_url()
    content = None
    if not excel_url:
        excel_url, content = try_direct_url()
    if not excel_url:
        print("No se pudo encontrar el Excel del SEN")
        return
    if not content:
        resp = requests.get(excel_url, timeout=60,
                            headers={'User-Agent': 'Mozilla/5.0'})
        if resp.status_code != 200:
            print(f"Error descargando: HTTP {resp.status_code}")
            return
        content = resp.content

    tes_data = parse_xls(content)
    if not tes_data:
        print("No se encontraron datos TES TF")
        return

    # Cargar historial del archivo anterior (máx 5 snapshots = 5 días hábiles)
    history = []
    try:
        import os
        if os.path.exists('datos_curva.json'):
            with open('datos_curva.json', encoding='utf-8') as f_old:
                old = json.load(f_old)
            if old.get('tes') and old.get('fecha'):
                snap = {
                    'fecha': old['fecha'],
                    'tirs': [{'codigo': b['codigo'], 'tir': b['tir'], 'plazo': b['plazo']}
                             for b in old['tes']]
                }
                history = [snap] + old.get('history', [])
    except Exception as e:
        print(f"Aviso historial: {e}")

    result = {
        'fecha': datetime.now().strftime('%Y-%m-%d'),
        'fuente': 'BanRep SEN',
        'tes': tes_data,
        'history': history[:5],
    }
    with open('datos_curva.json', 'w') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"✓ {len(tes_data)} TES guardados en datos_curva.json")
    for t in tes_data:
        print(f"  {t['codigo']} | {t['name']} | TIR: {t['tir']}% | Plazo: {t['plazo']} años")


if __name__ == '__main__':
    main()
