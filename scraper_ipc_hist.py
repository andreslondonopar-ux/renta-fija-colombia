"""
scraper_ipc_hist.py — Actualiza datos_ipc.json con variacion anual del IPC desde BanRep SUAMECA.

Fuente: API SUAMECA BanRep, serie ID=15000 (IPC total, tipoDato=9 = nivel del indice).
Calculo: variacion_anual(t) = (indice_t / indice_{t-12meses}) - 1

Publicacion: 5to dia habil del mes siguiente (DANE, recordatorio del usuario).
Schedule GitHub Actions: dias 8-12 de cada mes (cuando ya esta publicado).
"""
import json
from datetime import date, timedelta
from pathlib import Path

TODAY = date.today().isoformat()
DATA_FILE = Path("datos_ipc.json")

SUAMECA_URL = (
    "https://suameca.banrep.gov.co/estadisticas-economicas-back/rest/"
    "estadisticaEconomicaRestService/consultaInformacionSerieXTipoDatoXFechaDesde"
    "?idSerie=15000&tipoDato=9&cantDatos=12&frecuenciaDatos=year"
)


def load_existing():
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"updated": TODAY, "source": "BanRep SUAMECA", "data": [], "pub_dates": {}}


def nth_business_day(year, month, n):
    """Retorna el n-esimo dia habil del mes (lunes-viernes, sin festivos)."""
    d = date(year, month, 1)
    count = 0
    last_valid = d
    while d.month == month:
        if d.weekday() < 5:
            count += 1
            last_valid = d
            if count == n:
                return d.isoformat()
        d = d + timedelta(days=1)
    return last_valid.isoformat()


def pub_date_for(year, month):
    """IPC del mes M/Y se publica el 5to dia habil del mes M+1."""
    if month == 12:
        return nth_business_day(year + 1, 1, 5)
    return nth_business_day(year, month + 1, 5)


def fetch_suameca():
    """
    Descarga el indice IPC total desde SUAMECA y computa la variacion anual.
    Retorna lista de {y, m, v} ordenada, mas dict pub_dates.
    """
    import requests
    from datetime import datetime, timezone

    r = requests.get(SUAMECA_URL, timeout=60, headers={
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    })
    if not r.ok:
        print("[IPC] suameca HTTP %d" % r.status_code)
        return [], {}

    print("[IPC] suameca OK: %d bytes" % len(r.content))
    resp = r.json()
    if not isinstance(resp, list) or not resp:
        return [], {}

    raw_data = resp[0].get("data", [])
    if not raw_data:
        print("[IPC] suameca: data vacia")
        return [], {}

    # Construir dict {YYYY-MM: index_value}
    idx = {}
    for entry in raw_data:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        ts_ms, val = entry[0], entry[1]
        ym = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).strftime("%Y-%m")
        idx[ym] = float(val)

    # Calcular variacion anual
    result = []
    pub_dates = {}
    for ym in sorted(idx):
        y, m = int(ym[:4]), int(ym[5:7])
        prev_ym = "%d-%02d" % (y - 1, m)
        if prev_ym not in idx:
            continue
        ann_var = round(idx[ym] / idx[prev_ym] - 1, 4)
        result.append({"y": y, "m": m, "v": ann_var})
        pub_dates[ym] = pub_date_for(y, m)

    print("[IPC] suameca: %d entradas de variacion anual calculadas" % len(result))
    return result, pub_dates


def main():
    print("=== Actualizando datos_ipc.json ===")
    existing = load_existing()
    old_data = existing.get("data", [])

    new_data, new_pub_dates = [], {}
    try:
        new_data, new_pub_dates = fetch_suameca()
    except Exception as e:
        print("[IPC] error: %s" % e)

    if new_data and len(new_data) >= len(old_data):
        existing["data"] = new_data
        existing["pub_dates"] = {**existing.get("pub_dates", {}), **new_pub_dates}
        existing["source"] = "BanRep SUAMECA / DANE (serie 15000, var. anual calculada)"
        existing["updated"] = TODAY
        print("[IPC] %d entradas guardadas" % len(new_data))
    elif not new_data:
        print("[IPC] sin datos nuevos, manteniendo existentes (%d)" % len(old_data))
    else:
        print("[IPC] API devolvio menos datos (%d vs %d), sin cambios" % (len(new_data), len(old_data)))

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
    print("datos_ipc.json guardado")


if __name__ == "__main__":
    main()
