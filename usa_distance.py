from __future__ import annotations

import json
import logging
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

log = logging.getLogger("copart")

USER_AGENT = "CopartCRMBot/1.0 (wholesale calculator; local use)"
METERS_PER_MILE = 1609.344

# Порты/города вывоза: Нью-Джерси и Хьюстон.
US_EXPORT_PORTS = {
    "new_jersey": {
        "label": "New Jersey (Newark)",
        "query": "Newark, NJ, USA",
        "lat": 40.7357,
        "lon": -74.1724,
    },
    "houston": {
        "label": "Houston, Texas",
        "query": "Houston, TX, USA",
        "lat": 29.7604,
        "lon": -95.3698,
    },
}

_GEO_CACHE: dict[str, tuple[float, float] | None] = {}
_ROUTE_CACHE: dict[str, float | None] = {}
_GOOGLE_MATRIX_CACHE: dict[str, dict[str, float | None]] = {}


def _http_json(url: str, *, timeout: float = 12.0) -> dict | list | None:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        log.warning("API %s: %s", url.split("?")[0], exc)
        return None


def _clean_place(text: str | None) -> str:
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    raw = re.sub(r"\s*[·|].*$", "", raw).strip()
    return raw


US_STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri",
    "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}


def place_query_variants(place: str | None) -> list[str]:
    raw = _clean_place(place)
    if not raw:
        return []
    variants: list[str] = []
    m = re.match(r"^(.+?)\s*\(([A-Z]{2})\)$", raw, re.I)
    if m:
        city = m.group(1).strip()
        st = m.group(2).upper()
        state = US_STATE_NAMES.get(st, st)
        variants.extend(
            [
                f"{city}, {st}, USA",
                f"{city}, {state}, USA",
                f"{city}, {st}",
                f"{city} {state}",
            ]
        )
    else:
        variants.append(f"{raw}, USA")
        variants.append(raw)
    seen: set[str] = set()
    out: list[str] = []
    for item in variants:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def google_maps_api_key() -> str:
    try:
        from config import load_dotenv_once

        load_dotenv_once()
    except Exception:
        pass
    return (
        os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
        or os.getenv("GOOGLE_API_KEY", "").strip()
    )


def google_distance_matrix_miles(origin: str, destinations: list[str]) -> list[float | None] | None:
    """Мили по дороге Google Maps Distance Matrix (как в Google Maps)."""
    key = google_maps_api_key()
    if not key or not origin or not destinations:
        return None
    cache_key = f"{origin.lower()}->{'|'.join(d.lower() for d in destinations)}"
    if cache_key in _GOOGLE_MATRIX_CACHE:
        cached = _GOOGLE_MATRIX_CACHE[cache_key]
        return [cached.get(d) for d in destinations]

    params = urllib.parse.urlencode(
        {
            "origins": origin,
            "destinations": "|".join(destinations),
            "units": "imperial",
            "mode": "driving",
            "key": key,
        }
    )
    data = _http_json(
        f"https://maps.googleapis.com/maps/api/distancematrix/json?{params}",
        timeout=20.0,
    )
    if not isinstance(data, dict):
        return None
    status = str(data.get("status") or "")
    if status != "OK":
        log.warning("Google Distance Matrix status=%s error=%s", status, data.get("error_message"))
        return None
    rows = data.get("rows") or []
    if not rows:
        return None
    elements = rows[0].get("elements") or []
    miles_list: list[float | None] = []
    by_dest: dict[str, float | None] = {}
    for idx, dest in enumerate(destinations):
        el = elements[idx] if idx < len(elements) else {}
        el_status = str(el.get("status") or "")
        if el_status != "OK":
            miles_list.append(None)
            by_dest[dest] = None
            continue
        meters = float((el.get("distance") or {}).get("value") or 0)
        if meters <= 0:
            miles_list.append(None)
            by_dest[dest] = None
            continue
        miles = meters / METERS_PER_MILE
        miles_list.append(miles)
        by_dest[dest] = miles
    _GOOGLE_MATRIX_CACHE[cache_key] = by_dest
    return miles_list


def google_miles_via_chrome(place: str) -> dict[str, float] | None:
    """Мили NJ/Houston через вкладку Google Maps в вашем Chrome."""
    variants = place_query_variants(place)
    if not variants:
        return None
    dests = {key: port["query"] for key, port in US_EXPORT_PORTS.items()}
    try:
        from config import load_settings
        from scraper import get_scrape_service

        settings = load_settings(require_telegram=False, require_searches=False)
        service = get_scrape_service(settings.headless)
    except Exception as exc:
        log.warning("Chrome для Google Maps недоступен: %s", exc)
        return None
    for origin in variants[:2]:
        try:
            result = service.fetch_google_miles(origin, dests)
        except Exception as exc:
            log.warning("Google Maps Chrome «%s»: %s", origin, exc)
            continue
        if not result:
            continue
        if any(result.get(key) in (None, 0) for key in dests):
            continue
        out = {key: float(result[key]) for key in dests}
        log.info(
            "Google Maps (Chrome) «%s» → NJ %.1f mi / Houston %.1f mi",
            origin,
            out["new_jersey"],
            out["houston"],
        )
        return out
    return None


def openrouteservice_api_key() -> str:
    try:
        from config import load_dotenv_once

        load_dotenv_once()
    except Exception:
        pass
    return (
        os.getenv("OPENROUTESERVICE_API_KEY", "").strip()
        or os.getenv("ORS_API_KEY", "").strip()
    )


def _http_json_post(url: str, payload: dict, *, headers: dict | None = None, timeout: float = 20.0) -> dict | list | None:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
            **(headers or {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        log.warning("API POST %s: %s", url.split("?")[0], exc)
        return None


def openrouteservice_matrix_miles(origin: tuple[float, float], destinations: list[tuple[float, float]]) -> list[float | None] | None:
    """Мили по дороге OpenRouteService Matrix (аналог Google Distance Matrix)."""
    key = openrouteservice_api_key()
    if not key or not destinations:
        return None
    locations = [[origin[1], origin[0]]] + [[d[1], d[0]] for d in destinations]
    data = _http_json_post(
        "https://api.openrouteservice.org/v2/matrix/driving-car",
        {
            "locations": locations,
            "sources": [0],
            "destinations": list(range(1, len(locations))),
            "metrics": ["distance"],
            "units": "m",
        },
        headers={"Authorization": key},
        timeout=25.0,
    )
    if not isinstance(data, dict):
        return None
    distances = data.get("distances")
    if not isinstance(distances, list) or not distances:
        log.warning("OpenRouteService matrix: нет distances (%s)", data.get("error") or data.get("message"))
        return None
    row = distances[0] if isinstance(distances[0], list) else distances
    out: list[float | None] = []
    for meters in row:
        if meters is None or float(meters) <= 0:
            out.append(None)
        else:
            out.append(float(meters) / METERS_PER_MILE)
    return out if len(out) == len(destinations) else None


def osrm_table_miles(origin: tuple[float, float], destinations: list[tuple[float, float]]) -> list[float | None] | None:
    """Мили по дороге OSRM Table API (бесплатно, как Distance Matrix)."""
    if not destinations:
        return None
    coords = [f"{origin[1]},{origin[0]}"] + [f"{d[1]},{d[0]}" for d in destinations]
    path = ";".join(coords)
    dest_idx = ";".join(str(i) for i in range(1, len(coords)))
    urls = [
        f"https://router.project-osrm.org/table/v1/driving/{path}?sources=0&destinations={dest_idx}&annotations=distance",
        f"https://routing.openstreetmap.de/routed-car/table/v1/driving/{path}?sources=0&destinations={dest_idx}&annotations=distance",
    ]
    for url in urls:
        data = _http_json(url, timeout=20.0)
        if not isinstance(data, dict) or data.get("code") != "Ok":
            continue
        distances = data.get("distances")
        if not isinstance(distances, list) or not distances:
            continue
        row = distances[0]
        if not isinstance(row, list) or len(row) < len(destinations):
            continue
        out: list[float | None] = []
        for meters in row[: len(destinations)]:
            if meters is None or float(meters) <= 0:
                out.append(None)
            else:
                out.append(float(meters) / METERS_PER_MILE)
        if any(m is not None for m in out):
            return out
    return None


def driving_miles_to_export_ports(place: str) -> tuple[dict[str, float], str] | None:
    """
    Площадка → NJ и Houston по дороге.
    Порядок: Google Distance Matrix → OpenRouteService → OSRM Table.
    Без Chrome.
    """
    variants = place_query_variants(place)
    if not variants:
        return None
    dest_keys = list(US_EXPORT_PORTS.keys())
    dest_queries = [US_EXPORT_PORTS[k]["query"] for k in dest_keys]
    dest_coords = [(float(US_EXPORT_PORTS[k]["lat"]), float(US_EXPORT_PORTS[k]["lon"])) for k in dest_keys]

    # 1) Google Distance Matrix (если есть ключ)
    for origin in variants:
        miles = google_distance_matrix_miles(origin, dest_queries)
        if miles and all(m is not None for m in miles):
            result = {key: float(miles[i]) for i, key in enumerate(dest_keys)}
            log.info(
                "Google Distance Matrix «%s» → NJ %.1f mi / Houston %.1f mi",
                origin,
                result["new_jersey"],
                result["houston"],
            )
            return result, "google_maps"

    # 2–3) Геокод + OpenRouteService / OSRM matrix
    origin_ll = geocode(place)
    if not origin_ll:
        return None

    if openrouteservice_api_key():
        miles = openrouteservice_matrix_miles(origin_ll, dest_coords)
        if miles and all(m is not None for m in miles):
            result = {key: float(miles[i]) for i, key in enumerate(dest_keys)}
            log.info(
                "OpenRouteService «%s» → NJ %.1f mi / Houston %.1f mi",
                place,
                result["new_jersey"],
                result["houston"],
            )
            return result, "openrouteservice"

    miles = osrm_table_miles(origin_ll, dest_coords)
    if miles and any(m is not None for m in miles):
        result: dict[str, float] = {}
        for i, key in enumerate(dest_keys):
            if miles[i] is not None:
                result[key] = float(miles[i])
            else:
                # точечный fallback на route API
                one = osrm_driving_miles(origin_ll, dest_coords[i])
                if one is None:
                    return None
                result[key] = float(one)
        log.info(
            "OSRM Table «%s» → NJ %.1f mi / Houston %.1f mi",
            place,
            result["new_jersey"],
            result["houston"],
        )
        return result, "osrm"

    # По одному маршруту OSRM
    result = {}
    for key, dest in zip(dest_keys, dest_coords):
        one = osrm_driving_miles(origin_ll, dest)
        if one is None:
            air = haversine_miles(origin_ll[0], origin_ll[1], dest[0], dest[1]) * 1.25
            result[key] = air
        else:
            result[key] = float(one)
    if result:
        log.info(
            "OSRM/haversine «%s» → NJ %.1f mi / Houston %.1f mi",
            place,
            result["new_jersey"],
            result["houston"],
        )
        return result, "osrm"
    return None


def google_miles_to_export_ports(place: str, *, allow_chrome: bool = False) -> dict[str, float] | None:
    """Совместимость: мили до портов только через API (Chrome по умолчанию выключен)."""
    got = driving_miles_to_export_ports(place)
    if got:
        return got[0]
    if allow_chrome:
        return google_miles_via_chrome(place)
    return None


GOOGLE_MAPS_MILES_SCRIPT = r"""() => {
  const parse = (text) => {
    if (!text) return null;
    let m = String(text).match(/([\d\s,.]+)\s*(?:mi|miles|миль|мили|милю)\b/i);
    if (m) {
      const n = parseFloat(m[1].replace(/[\s,]/g, ""));
      return Number.isFinite(n) && n > 0 ? n : null;
    }
    m = String(text).match(/([\d\s,.]+)\s*km\b/i);
    if (m) {
      const n = parseFloat(m[1].replace(/[\s,]/g, ""));
      return Number.isFinite(n) && n > 0 ? n / 1.609344 : null;
    }
    return null;
  };
  const nodes = Array.from(document.querySelectorAll("[aria-label], div, span, button"));
  for (const el of nodes.slice(0, 400)) {
    const label = el.getAttribute && el.getAttribute("aria-label");
    const hit = parse(label) || parse(el.textContent);
    if (hit && hit < 8000) return hit;
  }
  return parse(document.body ? document.body.innerText : "");
}"""


def read_google_maps_driving_miles(page: Any, origin: str, destination: str) -> float | None:
    """Открывает маршрут Google Maps и читает мили (driving)."""
    origin = _clean_place(origin)
    destination = _clean_place(destination)
    if not origin or not destination:
        return None
    url = (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={urllib.parse.quote(origin)}"
        f"&destination={urllib.parse.quote(destination)}"
        "&travelmode=driving"
    )
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    except Exception as exc:
        log.warning("Google Maps goto: %s", exc)
        return None
    try:
        for sel in (
            "button:has-text('Accept all')",
            "button:has-text('Accept All')",
            "button:has-text('I agree')",
            "button:has-text('Принять все')",
        ):
            btn = page.locator(sel)
            if btn.count() and btn.first.is_visible():
                btn.first.click(timeout=2000)
                page.wait_for_timeout(800)
                break
    except Exception:
        pass
    miles = None
    for _ in range(18):
        page.wait_for_timeout(700)
        try:
            miles = page.evaluate(GOOGLE_MAPS_MILES_SCRIPT)
        except Exception:
            miles = None
        if miles and float(miles) > 0:
            return round(float(miles), 1)
    return None


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.7613
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def geocode_open_meteo(place: str) -> tuple[float, float] | None:
    q = urllib.parse.quote(place)
    data = _http_json(
        f"https://geocoding-api.open-meteo.com/v1/search?name={q}&count=8&language=en&format=json"
    )
    if not isinstance(data, dict):
        return None
    results = data.get("results") or []
    if not results:
        return None
    us = [row for row in results if str(row.get("country_code") or "").upper() == "US"]
    candidates = us or results
    st = None
    m = re.search(r",\s*([A-Z]{2})\b", place.upper())
    if m:
        st = m.group(1)
        state_name = US_STATE_NAMES.get(st, "").lower()
        for row in candidates:
            admin = str(row.get("admin1") or "").lower()
            if st and (admin == state_name or admin == st.lower() or st.lower() in admin):
                return float(row["latitude"]), float(row["longitude"])
    pick = candidates[0]
    return float(pick["latitude"]), float(pick["longitude"])


def geocode_nominatim(place: str) -> tuple[float, float] | None:
    q = urllib.parse.quote(place if "USA" in place.upper() else f"{place}, USA")
    time.sleep(1.05)
    data = _http_json(
        f"https://nominatim.openstreetmap.org/search?q={q}&format=json&limit=5&countrycodes=us",
        timeout=15.0,
    )
    if not isinstance(data, list) or not data:
        return None
    row = data[0]
    return float(row["lat"]), float(row["lon"])


def geocode_photon(place: str) -> tuple[float, float] | None:
    q = urllib.parse.quote(place)
    data = _http_json(
        f"https://photon.komoot.io/api/?q={q}&limit=8&lang=en&osm_tag=place",
        timeout=12.0,
    )
    if not isinstance(data, dict):
        return None
    for feat in data.get("features") or []:
        props = feat.get("properties") or {}
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        country = str(props.get("country") or props.get("countrycode") or "").upper()
        if country and country not in {"US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"}:
            continue
        lon, lat = float(coords[0]), float(coords[1])
        return lat, lon
    return None


def geocode(place: str | None) -> tuple[float, float] | None:
    variants = place_query_variants(place)
    if not variants:
        return None
    cache_key = variants[0].lower()
    if cache_key in _GEO_CACHE:
        return _GEO_CACHE[cache_key]
    point = None
    for q in variants:
        for fn in (geocode_open_meteo, geocode_nominatim, geocode_photon):
            try:
                point = fn(q)
            except Exception as exc:
                log.warning("geocode %s via %s: %s", q, fn.__name__, exc)
                point = None
            if point:
                log.info("Геокод «%s» → %s (via %s)", q, point, fn.__name__)
                _GEO_CACHE[cache_key] = point
                return point
    _GEO_CACHE[cache_key] = None
    return None


def osrm_driving_miles(origin: tuple[float, float], dest: tuple[float, float]) -> float | None:
    cache_key = f"{origin[0]:.5f},{origin[1]:.5f}->{dest[0]:.5f},{dest[1]:.5f}"
    if cache_key in _ROUTE_CACHE:
        return _ROUTE_CACHE[cache_key]
    path = f"{origin[1]},{origin[0]};{dest[1]},{dest[0]}"
    urls = [
        f"https://router.project-osrm.org/route/v1/driving/{path}?overview=false&alternatives=false",
        f"https://routing.openstreetmap.de/routed-car/route/v1/driving/{path}?overview=false",
    ]
    for url in urls:
        data = _http_json(url, timeout=15.0)
        if not isinstance(data, dict) or data.get("code") != "Ok":
            continue
        routes = data.get("routes") or []
        if not routes:
            continue
        meters = float(routes[0].get("distance") or 0)
        if meters <= 0:
            continue
        miles = meters / METERS_PER_MILE
        _ROUTE_CACHE[cache_key] = miles
        return miles
    _ROUTE_CACHE[cache_key] = None
    return None


def distance_miles(origin: tuple[float, float], dest: tuple[float, float]) -> tuple[float, str]:
    road = osrm_driving_miles(origin, dest)
    if road is not None:
        return road, "osrm"
    air = haversine_miles(origin[0], origin[1], dest[0], dest[1])
    return air * 1.25, "haversine"


def resolve_us_inland(
    location: str | None,
    ship_from: str | None = None,
    *,
    allow_chrome_maps: bool = False,
) -> dict[str, Any]:
    """
    Мили от «Местоположение» до New Jersey и Houston.
    Google Distance Matrix → OpenRouteService → OSRM (без Chrome).
    inland = мили × $1.
    """
    place = _clean_place(location) or _clean_place(ship_from)
    options: list[dict[str, Any]] = []
    origin = None
    source = "unknown"

    got = driving_miles_to_export_ports(place) if place else None
    if not got and place and _clean_place(ship_from) and _clean_place(ship_from) != place:
        got = driving_miles_to_export_ports(ship_from)
        if got:
            place = _clean_place(ship_from)

    if got:
        miles_map, source = got
        for key, port in US_EXPORT_PORTS.items():
            if key not in miles_map:
                continue
            options.append(
                {
                    "us_port": key,
                    "us_port_label": port["label"],
                    "miles": round(float(miles_map[key]), 1),
                    "source": source,
                }
            )
        origin = geocode(place)
    elif allow_chrome_maps and place:
        chrome = google_miles_via_chrome(place)
        if chrome:
            source = "google_maps_chrome"
            for key, port in US_EXPORT_PORTS.items():
                if key not in chrome:
                    continue
                options.append(
                    {
                        "us_port": key,
                        "us_port_label": port["label"],
                        "miles": round(float(chrome[key]), 1),
                        "source": source,
                    }
                )

    if not options or all(o["miles"] <= 0 for o in options):
        return {
            "ok": False,
            "error": "Не удалось получить мили по API (Google / OpenRouteService / OSRM)",
            "location": place,
            "origin": None,
            "options": options,
            "us_port": None,
            "us_port_label": None,
            "inland_miles": None,
            "inland_usd": None,
            "miles_to_new_jersey": next((o["miles"] for o in options if o["us_port"] == "new_jersey"), None),
            "miles_to_houston": next((o["miles"] for o in options if o["us_port"] == "houston"), None),
            "distance_source": None,
            "rate_usd_per_mile": 1.0,
        }

    best = min(options, key=lambda row: row["miles"])
    miles = float(best["miles"])
    cost = round(miles)
    return {
        "ok": True,
        "location": place,
        "origin": {"lat": origin[0], "lon": origin[1]} if origin else None,
        "options": options,
        "us_port": best["us_port"],
        "us_port_label": best["us_port_label"],
        "inland_miles": miles,
        "inland_usd": float(cost),
        "miles_to_new_jersey": next(o["miles"] for o in options if o["us_port"] == "new_jersey"),
        "miles_to_houston": next(o["miles"] for o in options if o["us_port"] == "houston"),
        "distance_source": best["source"],
        "rate_usd_per_mile": 1.0,
    }
