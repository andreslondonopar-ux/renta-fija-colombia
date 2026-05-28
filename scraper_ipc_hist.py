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
import holidays as _holidays

_CO_HOLIDAYS = _holidays.Colombia()

TODAY = date.today().isoformat()
DATA_FILE = Path("datos_ipc.json")

SUAMECA_URL = (
    "https://suameca.banrep.gov.co/estadisticas-economicas-back/rest/"
    "estadisticaEconomicaRestService/consultaInformacionSerieXTipoDatoXFechaDesde"
    "?idSerie=15000&tipoDato=20&cantDatos=12&frecuenciaDatos=year"
)


def load_existing():
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"updated": TODAY, "source": "BanRep SUAMECA", "data": [], "pub_dates": {}}


def nth_business_day_co(year, month, n):
    """n-esimo dia habil del mes segun calendario Colombia (holidays.Colombia)."""
    d = date(year, month, 1)
    count = 0
    while True:
        if d.weekday() < 5 and d not in _CO_HOLIDAYS:
            count += 1
            if count == n:
                return d.isoformat()
        d += timedelta(days=1)
        if d.month != month and d.day > 6:
            break
    return None


def pub_date_for(year, month):
    """IPC del mes M/Y se publica el 5to dia habil de M+1 (DANE)."""
    pub_y, pub_m = (year + 1, 1) if month == 12 else (year, month + 1)
    return nth_business_day_co(pub_y, pub_m, 5)


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

    # tipoDato=20 entrega variacion anual directamente en % (ej: 5.68)
    # Convertir a decimal (0.0568) y construir lista
    result = []
    pub_dates = {}
    for entry in raw_data:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        ts_ms, val_pct = entry[0], entry[1]
        ym = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).strftime("%Y-%m")
        y, m = int(ym[:4]), int(ym[5:7])
        result.append({"y": y, "m": m, "v": round(float(val_pct) / 100, 4)})
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
