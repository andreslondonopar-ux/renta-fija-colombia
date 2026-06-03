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


INVESTING_CAL = (
    "https://endpoints.investing.com/pd-instruments/v1/calendars/"
    "economic/events/occurrences"
)
# Categoría investing.com → type en calendar_data
US_CAT_MAP = {
    "inflation":       "cpi_us",
    "employment":      "empleo_us",
    "gdp":             "pib_us",
    "central_banks":   "fomc",
}
# Emojis/etiquetas para las fuentes
US_TYPE_LABEL = {
    "cpi_us":   "CPI EE.UU.",
    "empleo_us":"Empleo EE.UU.",
    "pib_us":   "PIB EE.UU.",
    "fomc":     "FOMC",
}


def fetch_us_events(days_ahead=90):
    """Obtiene eventos económicos de EE.UU. de alta importancia desde Investing.com."""
    today = TODAY
    end   = today + datetime.timedelta(days=days_ahead)
    params = {
        "domain_id":   1,
        "limit":       500,
        "start_date":  f"{today}T00:00:00.000-05:00",
        "end_date":    f"{end}T23:59:59.999-05:00",
        "country_ids": "5",   # US = 5 en Investing.com
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36",
        "Referer":    "https://www.investing.com/economic-calendar/",
        "Origin":     "https://www.investing.com",
    }
    try:
        r = requests.get(INVESTING_CAL, params=params, headers=headers, timeout=20)
        if r.status_code != 200:
            print(f"  Investing.com calendario: HTTP {r.status_code}")
            return []
        data = r.json()
    except Exception as e:
        print(f"  Investing.com calendario: {e}")
        return []

    events_meta = {e["event_id"]: e for e in data.get("events", [])}
    occurrences  = data.get("occurrences", [])

    results = []
    seen = set()  # (date, event_id) para deduplicar

    for occ in occurrences:
        eid  = occ.get("event_id")
        meta = events_meta.get(eid)
        if not meta:
            continue
        if meta.get("importance") != "high":
            continue
        if meta.get("country_id") != 5:
            continue

        category = meta.get("category", "")
        evt_type = US_CAT_MAP.get(category)
        if not evt_type:
            continue

        # Fecha en hora Colombia (UTC-5)
        occ_time = occ.get("occurrence_time", "")
        try:
            dt = datetime.datetime.fromisoformat(occ_time.replace("Z", "+00:00"))
            date_str = (dt - datetime.timedelta(hours=5)).strftime("%Y-%m-%d")
        except Exception:
            continue

        if date_str < str(today):
            continue
        if (date_str, eid) in seen:
            continue
        seen.add((date_str, eid))

        name   = (meta.get("event_translated") or meta.get("short_name") or "").strip()
        period = occ.get("reference_period", "")
        title  = f"{name}{' — ' + period if period else ''}"

        # Descripción con valores
        parts = []
        for key, lbl in [("actual","Act"),("forecast","Prev"),("previous","Ant")]:
            val = occ.get(key)
            if val is not None:
                parts.append(f"{lbl}: {val}")
        desc = " · ".join(parts) if parts else ""

        results.append({
            "date":  date_str,
            "type":  evt_type,
            "title": title,
            "desc":  desc,
            "pais":  "us",
        })

    return results


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
                        if e.get("type") not in ("banrep", "cpi_us", "empleo_us", "pib_us", "fomc")]
    else:
        other_events = []

    # 5. Eventos económicos EE.UU. desde Investing.com
    us_events = fetch_us_events()
    print(f"\n  {len(us_events)} eventos EE.UU. de alta importancia")

    all_events = sorted(other_events + banrep_events + us_events, key=lambda e: e["date"])

    result = {
        "updated": NOW,
        "sources": "JDBR: API SUAMECA BanRep | DANE: calendario oficial | EE.UU.: Investing.com",
        "events":  all_events,
    }
    cal_path.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    print(f"\nOK calendar_data.json actualizado")
    print(f"  {len(banrep_events)} JDBR + {len(us_events)} EE.UU. + {len(other_events)} otros")


if __name__ == "__main__":
    main()
