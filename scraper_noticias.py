"""
scraper_noticias.py — Titulares financieros Colombia
Fuentes RSS: La República, Portafolio, Valora Analitik, El Tiempo Economía
Guarda noticias_data.json.
"""
import json, re, datetime, requests
from pathlib import Path
from xml.etree import ElementTree as ET

TODAY = datetime.date.today().isoformat()
NOW   = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

FEEDS = [
    {"source": "La República",    "url": "https://www.larepublica.co/rss/economia"},
    {"source": "La República",    "url": "https://www.larepublica.co/rss/finanzas"},
    {"source": "Portafolio",      "url": "https://portafolio.co/rss/economia.xml"},
    {"source": "Valora Analitik", "url": "https://www.valoraanalitik.com/feed/"},
    {"source": "El Tiempo",       "url": "https://www.eltiempo.com/rss/economia.xml"},
]

# Palabras que DEBEN aparecer en el título para aceptar la noticia
INCLUDE_KW = {
    # Macro & política monetaria
    'economía','económico','económica','pib','inflación','deflación',
    'tasa','tasas','banrep','banco de la república','fed','reserva federal',
    'política monetaria','política fiscal','devaluación','revaluación',
    # Mercados & instrumentos
    'mercado','bolsa','acciones','acción','bono','bonos','tes',
    'divisa','divisas','dólar','trm','eurodólar','yield','spread',
    'renta fija','renta variable','portafolio','índice','índices',
    # Sector financiero
    'banco','bancos','financiero','financiera','finanzas','crédito',
    'cartera','préstamo','deuda','déficit','superávit','presupuesto',
    'fiscal','tributario','tributaria','impuesto','reforma tributaria',
    # Empresas & corporativo
    'empresa','empresas','empresarial','corporativo','compañía','industria',
    'utilidades','ganancias','dividendo','fusión','adquisición','emisión',
    'inversión','inversionistas','accionistas','cotización','oferta pública',
    # Comercio & sector real
    'exportación','importación','comercio','producción','manufactura',
    'empleo','desempleo','salario','salarios','crecimiento','recesión',
    'balanza','reservas internacionales',
    # Energía & commodities (relevante para Colombia)
    'petróleo','ecopetrol','oil','wti','brent','gas natural','minería',
    'café','commodities','materias primas',
    # Entidades clave
    'superfinanciera','minhacienda','dane','banrep','ocde','fmi','bid',
    'moody','fitch','s&p','calificadora',
}

# Palabras que DESCARTAN la noticia aunque aparezca algo financiero
EXCLUDE_KW = {
    'fútbol','futbol','deporte','deportes','selección colombia',
    'farándula','entretenimiento','cine','película','música','artista',
    'actor','actriz','novela','serie','reality','cantante',
    'turismo','viaje','viajes','hotel','receta','gastronomía',
    'salud','medicina','vacuna','pandemia','covid',
    'política','elecciones','congreso','senado','presidente','alcalde',
    'seguridad','crimen','delito','homicidio','violencia',
    'derechos humanos','medio ambiente','clima','temperatura',
}


def is_economic(title: str) -> bool:
    t = title.lower()
    for kw in EXCLUDE_KW:
        if kw in t:
            return False
    for kw in INCLUDE_KW:
        if kw in t:
            return True
    return False

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

DATE_FMTS = [
    "%a, %d %b %Y %H:%M:%S %z",
    "%a, %d %b %Y %H:%M:%S GMT",
    "%a, %d %b %Y %H:%M:%S +0000",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d %H:%M:%S",
]


def strip_html(text):
    text = re.sub(r'<[^>]+>', ' ', text or '')
    for ent, val in [('&amp;','&'),('&lt;','<'),('&gt;','>'),
                     ('&quot;','"'),('&#39;',"'"),('&nbsp;',' '),
                     ('&#8217;',"'"),('&#8216;',"'"),('&#8220;','"'),('&#8221;','"')]:
        text = text.replace(ent, val)
    return re.sub(r'\s+', ' ', text).strip()


def parse_pub(pub_str):
    if not pub_str:
        return NOW
    pub_str = pub_str.strip()
    # Remove timezone names that Python can't parse (e.g. "COT", "EDT")
    pub_clean = re.sub(r'\s+[A-Z]{2,4}$', '', pub_str)
    for fmt in DATE_FMTS:
        try:
            dt = datetime.datetime.strptime(pub_clean, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            continue
    return NOW


def fetch_feed(source, url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        if r.status_code != 200:
            print(f"  {source}: HTTP {r.status_code} — {url.split('/')[-1]}")
            return []
        root = ET.fromstring(r.content)
        items = root.findall('.//item')
        articles = []
        for item in items[:20]:
            title = strip_html(item.findtext('title') or '')
            link  = (item.findtext('link') or '').strip()
            pub   = item.findtext('pubDate') or ''
            desc  = strip_html(item.findtext('description') or '')
            # Trim summary to ~200 chars ending on word boundary
            if len(desc) > 200:
                desc = desc[:200].rsplit(' ', 1)[0] + '…'
            if title and link:
                articles.append({
                    "title":     title,
                    "source":    source,
                    "url":       link,
                    "published": parse_pub(pub),
                    "summary":   desc,
                })
        print(f"  {source}: {len(articles)} artículos")
        return articles
    except Exception as e:
        print(f"  {source}: error — {e}")
        return []


def dedup(articles):
    seen = set()
    result = []
    for a in articles:
        key = re.sub(r'\W+', '', a['title'].lower())[:55]
        if key and key not in seen:
            seen.add(key)
            result.append(a)
    return result


def main():
    print(f"=== Noticias Colombia — {TODAY} ===\n")

    all_arts = []
    seen_urls = set()
    for feed in FEEDS:
        arts = fetch_feed(feed["source"], feed["url"])
        for a in arts:
            if a["url"] not in seen_urls:
                seen_urls.add(a["url"])
                all_arts.append(a)

    # Filtrar: solo noticias económicas/financieras/empresariales
    filtered = [a for a in all_arts if is_economic(a["title"])]
    skipped = len(all_arts) - len(filtered)
    if skipped:
        print(f"  Filtradas {skipped} noticias no económicas de {len(all_arts)} totales")

    # Ordenar por fecha desc
    filtered.sort(key=lambda a: a["published"], reverse=True)
    articles = dedup(filtered)[:9]

    result = {
        "updated":  NOW,
        "date":     TODAY,
        "articles": articles,
    }
    Path("noticias_data.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nOK noticias_data.json — {len(articles)} artículos")
    for a in articles:
        print(f"  [{a['source']:<15}] {a['title'][:65]}")


if __name__ == "__main__":
    main()
