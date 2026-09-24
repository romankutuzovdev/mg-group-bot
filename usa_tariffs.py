"""Доставка США из прайса «Ценообразование США.xlsx» (вкладки Copart / IAAI + море B2B)."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent / "data" / "usa_inland_tariffs.json"

US_STATE_ABBR = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
    "DC": "District of Columbia",
}
STATE_NAME_TO_ABBR = {v.lower(): k for k, v in US_STATE_ABBR.items()}

SIZE_ALIASES = {
    "regular": "regular",
    "regular_large": "regular",
    "large": "regular",
    "reg": "regular",
    "oversize": "oversize",
    "oversized": "oversize",
    "moto": "moto",
    "motorcycle": "moto",
    "bike": "moto",
}


def normalize_size(vehicle_size: str | None) -> str:
    raw = str(vehicle_size or "").strip().lower().replace(" ", "_").replace("-", "_")
    return SIZE_ALIASES.get(raw, "regular")


def size_from_dismantle_type(dismantle_type: str | None) -> str:
    """Тип разбора / кузов → ключ прайса regular|oversize|moto."""
    raw = str(dismantle_type or "").strip().lower().replace(" ", "_").replace("-", "_")
    if raw in {"moto", "motorcycle", "bike", "atv"}:
        return "moto"
    if raw in {
        "bus",
        "truck",
        "pickup",
        "frame_suv",
        "van",
        "sprinter",
        "oversize",
        "oversized",
    }:
        return "oversize"
    return "regular"


def normalize_auction(auction: str | None) -> str:
    a = str(auction or "").strip().lower()
    if "copart" in a:
        return "copart"
    if "iaai" in a or "iAAI".lower() in a:
        return "iaai"
    return "iaai"


@lru_cache(maxsize=1)
def _load() -> dict:
    if not DATA_PATH.exists():
        return {"copart": [], "iaai": [], "ocean": {}, "ports": {}, "size_labels": {}}
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def _norm_text(value: str) -> str:
    s = str(value or "").upper()
    s = s.replace("&", " AND ")
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_location_query(location: str | None) -> tuple[str, str | None]:
    """'Flint (MI)' / 'Houston, TX' / 'ACE - Perris - California' → (city, state_abbr|None)."""
    raw = str(location or "").strip()
    if not raw:
        return "", None
    state = None
    city = raw
    m = re.search(r"\(([A-Za-z]{2})\)\s*$", raw)
    if m:
        state = m.group(1).upper()
        city = raw[: m.start()].strip(" ,.-")
    else:
        m = re.search(r",\s*([A-Za-z]{2})\s*$", raw)
        if m:
            state = m.group(1).upper()
            city = raw[: m.start()].strip(" ,.-")
        else:
            parts = [p.strip() for p in re.split(r"\s+-\s+", raw) if p.strip()]
            if len(parts) >= 2:
                city = parts[0]
                maybe_state = parts[1]
                if len(maybe_state) == 2 and maybe_state.upper() in US_STATE_ABBR:
                    state = maybe_state.upper()
                elif maybe_state.lower() in STATE_NAME_TO_ABBR:
                    state = STATE_NAME_TO_ABBR[maybe_state.lower()]
    # убрать хвосты вроде IAAI / Copart
    city = re.sub(r"\s+(?:IAAI|COPART)\s*$", "", city, flags=re.I).strip()
    return city, state


def _yard_state_abbr(yard: dict) -> str | None:
    st = str(yard.get("state") or "").strip()
    if not st:
        return None
    if len(st) == 2 and st.upper() in US_STATE_ABBR:
        return st.upper()
    return STATE_NAME_TO_ABBR.get(st.lower())


def _score_yard(yard: dict, city_q: str, state_q: str | None) -> float:
    city_n = _norm_text(yard.get("city") or "")
    q = _norm_text(city_q)
    if not q or not city_n:
        return -1.0
    score = 0.0
    if city_n == q:
        score = 100.0
    elif city_n.startswith(q + " ") or q.startswith(city_n + " "):
        score = 85.0
    elif q in city_n or city_n in q:
        score = 70.0
    else:
        # токены: "Fort Worth" vs "Fort Worth North"
        qt = set(q.split())
        ct = set(city_n.split())
        if qt and qt.issubset(ct):
            score = 75.0
        elif ct and ct.issubset(qt):
            score = 72.0
        else:
            return -1.0
    y_state = _yard_state_abbr(yard)
    if state_q and y_state:
        if y_state == state_q:
            score += 20.0
        else:
            score -= 40.0
    return score


def find_yard(location: str | None, auction: str | None = "iaai") -> dict | None:
    data = _load()
    platform = normalize_auction(auction)
    yards = list(data.get(platform) or [])
    city_q, state_q = parse_location_query(location)
    if not city_q:
        return None
    best = None
    best_score = -1.0
    for yard in yards:
        sc = _score_yard(yard, city_q, state_q)
        if sc > best_score:
            best_score = sc
            best = yard
    if best is None or best_score < 70:
        # запасной поиск по другой площадке
        other = "copart" if platform == "iaai" else "iaai"
        for yard in data.get(other) or []:
            sc = _score_yard(yard, city_q, state_q)
            if sc > best_score:
                best_score = sc
                best = yard
                platform = other
        if best is None or best_score < 70:
            return None
        best = {**best, "matched_auction": platform}
    else:
        best = {**best, "matched_auction": platform}
    return best


def ocean_usd(
    us_port: str | None,
    vehicle_size: str | None,
    destination: str = "klaipeda",
) -> float | None:
    data = _load()
    size = normalize_size(vehicle_size)
    dest = str(destination or "klaipeda").strip().lower()
    if dest not in ("klaipeda", "poti"):
        dest = "klaipeda"
    port = str(us_port or "").strip().lower().replace(" ", "_").replace("-", "_")
    if port in {"new_york", "newark", "norfolk", "ny"}:
        port = "new_york_norfolk"
    bucket = (data.get("ocean") or {}).get(dest) or {}
    rates = bucket.get(port) or {}
    if size == "regular":
        # Regular / Large в UI — одна опция; если есть large, берём regular (как в inland)
        val = rates.get("regular")
        if val is None:
            val = rates.get("large")
        return None if val is None else float(val)
    val = rates.get(size)
    return None if val is None else float(val)


def lookup_usa_delivery(
    location: str | None,
    vehicle_size: str | None,
    auction: str | None = "iaai",
    ocean_destination: str = "klaipeda",
) -> dict | None:
    """Цена суши по площадке+размеру и порт вывоза; море — по порту из B2B."""
    yard = find_yard(location, auction=auction)
    if not yard:
        return None
    size = normalize_size(vehicle_size)
    port_key = yard.get("primary_port")
    port_prices = (yard.get("ports") or {}).get(port_key) or {}
    inland = port_prices.get(size)
    if inland is None:
        return None
    data = _load()
    labels = data.get("size_labels") or {}
    port_labels = data.get("ports") or {}
    dest = str(ocean_destination or "klaipeda").strip().lower() or "klaipeda"
    if dest not in ("klaipeda", "poti"):
        dest = "klaipeda"
    ocean = ocean_usd(port_key, size, dest)
    ocean_bucket = ((data.get("ocean") or {}).get(dest) or {}).get(port_key) or {}
    size_keys = ("regular", "oversize", "moto")
    inland_by_size = {
        key: (None if port_prices.get(key) is None else float(port_prices[key]))
        for key in size_keys
    }
    ocean_by_size = {}
    for key in size_keys:
        if key == "regular":
            val = ocean_bucket.get("regular")
            if val is None:
                val = ocean_bucket.get("large")
        else:
            val = ocean_bucket.get(key)
        ocean_by_size[key] = None if val is None else float(val)
    return {
        "matched_location": yard.get("location"),
        "matched_auction": yard.get("matched_auction") or normalize_auction(auction),
        "city": yard.get("city"),
        "state": yard.get("state"),
        "us_port": port_key,
        "us_port_label": yard.get("primary_port_label") or port_labels.get(port_key) or port_key,
        "vehicle_size": size,
        "vehicle_size_label": labels.get(size) or size,
        "inland_usd": float(inland),
        "ocean_usd": float(ocean or 0),
        "ocean_destination": dest,
        "tariff_source": "usa_inland_tariffs",
        "price_sheet": {
            "yard": yard.get("location"),
            "auction": yard.get("matched_auction") or normalize_auction(auction),
            "us_port": port_key,
            "us_port_label": yard.get("primary_port_label") or port_labels.get(port_key) or port_key,
            "ocean_destination": dest,
            "selected_size": size,
            "size_labels": {key: labels.get(key) or key for key in size_keys},
            "inland_by_size": inland_by_size,
            "ocean_by_size": ocean_by_size,
            "selected_inland_usd": float(inland),
            "selected_ocean_usd": float(ocean or 0),
        },
    }


def resolve_inland_from_tariff(
    location: str | None,
    *,
    auction: str | None = None,
    vehicle_size: str | None = None,
    dismantle_type: str | None = None,
    ocean_destination: str = "klaipeda",
) -> dict | None:
    """Inland из прайса всех площадок Copart/IAAI (вместо миль)."""
    size = vehicle_size or size_from_dismantle_type(dismantle_type)
    return lookup_usa_delivery(
        location,
        size,
        auction=auction or "iaai",
        ocean_destination=ocean_destination,
    )


def list_all_yards() -> dict:
    """Все локации из прайса: copart + iaai."""
    data = _load()
    return {
        "source": data.get("source"),
        "sizes": data.get("sizes") or ["regular", "oversize", "moto"],
        "size_labels": data.get("size_labels") or {},
        "ports": data.get("ports") or {},
        "copart": list(data.get("copart") or []),
        "iaai": list(data.get("iaai") or []),
        "copart_count": len(data.get("copart") or []),
        "iaai_count": len(data.get("iaai") or []),
    }
