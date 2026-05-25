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
    print(f"Links SEN encontrados: {len(sen_links)}")
    for l in sen_links[:3]:
        print(f"  {l}")
    return sen_links[0] if sen_links else None

def try_direct_url():
    base = "https://www.banrep.gov.co/sites/default/files/paginas/"
    # Start from yesterday — BanRep publishes after market close
    start = datetime.now() - timedelta(days=1)
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
            except:
                pass
    return None, None

def parse_xls(content):
    wb = xlrd.open_workbook(file_contents=content)
    tes_data = []
    for sheet_name in wb.sheet_names():
        ws = wb.sheet_by_name(sheet_name)
        print(f"  Hoja: {sheet_name} ({ws.nrows} filas)")
        for row_idx in range(ws.nrows):
            row = ws.row_values(row_idx)
            label = ''
            for col in range(min(3, len(row))):
                cell_val = str(row[col]).strip()
                if 'TES TF' in cell_val.upper():
                    label = cell_val
                    break
            if not label:
                continue
            tir = None
            for cell in row[1:]:
                try:
                    v = float(cell)
                    if 5 < v < 25:
                        tir = round(v, 4)
                        break
                    elif 0.05 < v < 0.25:
                        tir = round(v * 100, 4)
                        break
                except (TypeError, ValueError):
                    pass
            if not tir:
                continue
            year_match = re.search(r'20(\d{2})', label)
            if not year_match:
                continue
            year = int('20' + year_match.group(1))
            plazo = round((year - datetime.now().year) + 0.5, 2)
            if plazo <= 0:
                continue
            tes_data.append({'name': f"TES TF {year}", 'tir': tir, 'plazo': plazo})
    tes_data.sort(key=lambda x: x['plazo'])
    return tes_data

def main():
    excel_url = get_excel_url()
    content = None

    if not excel_url:
        print("No encontrado en página, probando URL directa...")
        excel_url, content = try_direct_url()

    if not excel_url:
        print("No se pudo encontrar el Excel del SEN")
        return

    if not content:
        print(f"Descargando: {excel_url}")
        resp = requests.get(excel_url, timeout=60,
                            headers={'User-Agent': 'Mozilla/5.0'})
        if resp.status_code != 200:
            print(f"Error HTTP {resp.status_code}")
            return
        content = resp.content

    print(f"Descargado: {len(content)//1024} KB")
    tes_data = parse_xls(content)

    if not tes_data:
        print("No se encontraron datos TES TF")
        return

    result = {
        'fecha': datetime.now().strftime('%Y-%m-%d'),
        'fuente': 'BanRep SEN',
        'tes': tes_data
    }
    with open('datos_curva.json', 'w') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"✓ {len(tes_data)} TES guardados")
    for t in tes_data:
        print(f"  {t['name']}: {t['tir']}% ({t['plazo']}a)")

if __name__ == '__main__':
    main()
