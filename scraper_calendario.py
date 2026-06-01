"""
scraper_calendario.py - Fechas JDBR BanRep via API SUAMECA
Extrae fechas de reuniones de politica monetaria y actualiza calendar_data.json
preservando los eventos DANE/EME/TES existentes.

Logica: SUAMECA publica la fecha en que la tasa TOMA EFECTO (1 dia habil
despues de la reunion). Restamos 1 dia habil (saltando festivos y fines de
semana colombianos) para obtener la fecha de reunion.
"""
import json, datetime, requests
from pathlib import Path

TODAY = datetime.date.today()
NOW   = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

BASE = ("https://suameca.banrep.gov.co/estadisticas-economicas-back/"
        "rest/estadisticaEconomicaRestService")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":    "https://suameca.banrep.gov.co/",
}


def fetch_holidays(year):
    """Devuelve conjunto de fechas festivas colombianas del anno."""
    try:
        r = requests.get(
            f"{BASE}/buscarFestivosXAnnio",
            params={"annio": year}, headers=HEADERS, timeout=10
        )
        if r.ok:
            data = r.json()
            # API retorna lista de strings "YYYY-MM-DD"
            if data and isinstance(data[0], str):
                holidays = {str(d)[:10] for d in data}
            else:
                holidays = {str(item.get("fecha", ""))[:10] for item in data if item.get("fecha")}
            print(f"  Festivos {year}: {len(holidays)} dias")
            return holidays
    except Exception as e:
        print(f"  Error festivos {year}: {e}")
    return set()


def prev_business_day(date, holidays):
    """Retrocede 1 dia habil (lunes-viernes, sin festivos)."""
    d = date - datetime.timedelta(days=1)
    while d.weekday() >= 5 or str(d) in holidays:
        d -= datetime.timedelta(days=1)
    return d


def fetch_tasa_dates(year, month):
    """Retorna fechas efectivas de TASA_INTERVENCION_BR para un mes dado."""
    try:
        r = requests.get(
            f"{BASE}/listarCompromisosXCategoriaYearMonth",
            params={"annio": year, "mes": month},
            headers=HEADERS, timeout=15
        )
        if not r.ok:
            return []
        dates = []
        for item in r.json():
            if item.get("idCompromiso", "") == "TASA_INTERVENCION_BR":
                fc = item.get("fechaCompleta", "")
                if fc:
                    dates.append(str(fc)[:10])
        return list(set(dates))
    except Exception as e:
        print(f"  Error {year}-{month:02d}: {e}")
        return []


def main():
    print(f"=== Calendario JDBR BanRep - {TODAY} ===\n")

    # 1. Festivos 2026 y 2027
    holidays = fetch_holidays(2026) | fetch_holidays(2027)

    # 2. Recolectar fechas efectivas TASA_INTERVENCION para proximos 14 meses
    effective_dates = set()
    d = TODAY.replace(day=1)
    for _ in range(14):
        yr, mo = d.year, d.month
        dates = fetch_tasa_dates(yr, mo)
        effective_dates.update(dates)
        print(f"  {yr}-{mo:02d}: {sorted(dates)}")
        if mo == 12:
            d = d.replace(year=yr + 1, month=1)
        else:
            d = d.replace(month=mo + 1)

    # 3. Filtrar fechas futuras y calcular fechas de reunion
    banrep_events = []
    seen = set()
    for eff_str in sorted(effective_dates):
        eff = datetime.date.fromisoformat(eff_str)
        if eff < TODAY:
            continue
        meeting = prev_business_day(eff, holidays)
        meeting_str = str(meeting)
        if meeting_str in seen:
            continue
        seen.add(meeting_str)
        banrep_events.append({
            "date":  meeting_str,
            "type":  "banrep",
            "title": "JDBR - BanRep",
            "desc":  f"Decision tasa de intervencion (efectiva {eff_str})"
        })
        print(f"  Reunion: {meeting_str} -> efectiva {eff_str}")

    if not banrep_events:
        print("Sin fechas JDBR futuras. Manteniendo calendar_data.json existente.")
        return

    # 4. Cargar calendar_data.json y reemplazar solo eventos banrep
    cal_path = Path("calendar_data.json")
    if cal_path.exists():
        existing = json.loads(cal_path.read_text(encoding="utf-8"))
        other_events = [e for e in existing.get("events", [])
                        if e.get("type") != "banrep"]
    else:
        other_events = []

    all_events = sorted(other_events + banrep_events, key=lambda e: e["date"])

    result = {
        "updated": NOW,
        "sources": "JDBR: API SUAMECA BanRep | DANE: calendario oficial",
        "events":  all_events,
    }
    cal_path.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    print(f"\nOK calendar_data.json actualizado")
    print(f"  {len(banrep_events)} reuniones JDBR + {len(other_events)} eventos DANE/EME")


if __name__ == "__main__":
    main()
