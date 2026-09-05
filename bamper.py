"""Поиск запчастей авто на bamper.by по марке / модели / году."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from config import DATA_DIR

log = logging.getLogger("bamper")

BAMPER_BASE = "https://bamper.by"
PARTS_CACHE = DATA_DIR / "bamper_parts.json"
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

# Частые slug марки на bamper (value select)
# slug = value <option> на bamper.by (не SEO-имя бренда)
MAKE_ALIASES: dict[str, str] = {
    "mercedes": "mercedes",
    "mercedesbenz": "mercedes",
    "mercedes-benz": "mercedes",
    "vw": "volkswagen",
    "volkswagen": "volkswagen",
    "landrover": "landrover",
    "land-rover": "landrover",
    "range rover": "landrover",
    "rangerover": "landrover",
    "alfa": "alfaromeo",
    "alfaromeo": "alfaromeo",
    "alfa-romeo": "alfaromeo",
    "citroen": "citroen",
    "citroën": "citroen",
    "skoda": "skoda",
    "škoda": "skoda",
    "bmw": "bmw",
    "audi": "audi",
    "toyota": "toyota",
    "honda": "honda",
    "nissan": "nissan",
    "ford": "ford",
    "opel": "opel",
    "peugeot": "peugeot",
    "renault": "renault",
    "hyundai": "hyundai",
    "kia": "kia",
    "mazda": "mazda",
    "mitsubishi": "mitsubishi",
    "subaru": "subaru",
    "suzuki": "suzuki",
    "volvo": "volvo",
    "lexus": "lexus",
    "infiniti": "infiniti",
    "jaguar": "jaguar",
    "jeep": "jeep",
    "chrysler": "chrysler",
    "dodge": "dodge",
    "chevrolet": "chevrolet",
    "cadillac": "cadillac",
    "porsche": "porsche",
    "mini": "mini",
    "seat": "seat",
    "fiat": "fiat",
    "tesla": "tesla",
    "ssangyong": "ssangyong",
    "greatwall": "greatwall",
    "great-wall": "greatwall",
    "haval": "haval",
    "geely": "geely",
    "chery": "chery",
    "rollsroyce": "rollsroyce",
    "rolls-royce": "rollsroyce",
    "rolls royce": "rollsroyce",
}

_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_PARTS_LOCK = threading.Lock()
_PARTS_MEM: list[dict[str, str]] | None = None
_MODELS_LOCK = threading.Lock()
_MODELS_MEM: dict[str, list[tuple[str, str]]] = {}
_MARKAS_LOCK = threading.Lock()
_MARKAS_MEM: list[tuple[str, str]] | None = None

# Типовой разбор легкового авто — только эти позиции ищем под марку/модель лота
DISMANTLE_PART_CODES: tuple[str, ...] = (
    # кузов
    "bamper-peredniy",
    "bamper-zadniy",
    "kapot",
    "kryshka-bagazhnika-dver-3-5",
    "dver-perednyaya-levaya",
    "dver-perednyaya-pravaya",
    "dver-zadnyaya-levaya",
    "dver-zadnyaya-pravaya",
    "krylo-perednee-levoe",
    "krylo-perednee-pravoe",
    "krylo-zadnee-levoe",
    "krylo-zadnee-pravoe",
    "porog-levyy",
    "porog-pravyy",
    "lonzheron-levyy",
    "lonzheron-pravyy",
    "krysha",
    "spoyler",
    "reshetka-radiatora",
    # оптика / стёкла / зеркала
    "fara-levaya",
    "fara-pravaya",
    "fara-protivotumannaya-levaya",
    "fara-protivotumannaya-pravaya",
    "fonar-zadniy-levyy",
    "fonar-zadniy-pravyy",
    "povorotnik-levyy",
    "povorotnik-pravyy",
    "zerkalo-naruzhnoe-levoe",
    "zerkalo-naruzhnoe-pravoe",
    "steklo-lobovoe",
    "steklo-zadnee",
    # ДВС / КПП / навесное
    "dvigatel",
    "kpp-avtomaticheskaya-akpp",
    "kpp-mekhanicheskaya-mkpp",
    "razdatochnaya-korobka",
    "generator",
    "starter",
    "turbina",
    "radiator-osnovnoy",
    "radiator-konditsionera",
    "kompressor-konditsionera",
    "ventilyator-radiatora",
    "nasos-toplivnyy",
    "bak-toplivnyy",
    "glushitel",
    "katalizator",
    # ходовая / рулевое
    "amortizator-peredniy-levyy",
    "amortizator-peredniy-pravyy",
    "amortizator-zadniy-levyy",
    "amortizator-zadniy-pravyy",
    "rychag-peredniy-levyy",
    "rychag-peredniy-pravyy",
    "stupitsa-perednyaya-levaya",
    "stupitsa-perednyaya-pravaya",
    "poluos-perednyaya-levaya-privodnoy-val-shrus",
    "poluos-perednyaya-pravaya-privodnoy-val-shrus",
    "rulevaya-reyka",
    "nasos-gidrousilitelya-rulya",
    "koleso-v-sbore",
    "disk-litoy",
    # салон
    "panel-perednyaya-salona-torpedo",
    "shchitok-priborov-pribornaya-panel",
    "sidene-perednee-levoe",
    "sidene-perednee-pravoe",
    "sidene-zadnee",
)


def _http(url: str, *, data: dict | None = None, timeout: int = 35) -> tuple[str, str]:
    headers = {**UA}
    body = None
    if data is not None:
        from urllib.parse import urlencode

        body = urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        headers["X-Requested-With"] = "XMLHttpRequest"
        headers["Referer"] = f"{BAMPER_BASE}/"
    req = Request(url, data=body, headers=headers)
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        final = resp.geturl()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1251", errors="ignore")
    return final, text


def slugify_token(value: str) -> str:
    text = (value or "").strip().lower().replace("ё", "е")
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower().replace("ё", "е"))


def load_markas(*, refresh: bool = False) -> list[tuple[str, str]]:
    """Официальные value марки с bamper.by — иначе rolls-royce / land-rover не совпадут."""
    global _MARKAS_MEM
    with _MARKAS_LOCK:
        if _MARKAS_MEM is not None and not refresh:
            return list(_MARKAS_MEM)
    try:
        _, html = _http(f"{BAMPER_BASE}/zchbu/zapchast_bamper-peredniy/", timeout=22)
    except Exception as exc:
        log.warning("Bamper markas: %s", exc)
        return list(_MARKAS_MEM or [])
    opts = _select_options(html, "marka") or _select_options(html, "MARKA")
    with _MARKAS_LOCK:
        _MARKAS_MEM = opts
    return list(opts)


def make_slug(make: str | None) -> str | None:
    raw = (make or "").strip().lower().replace("ё", "е")
    if not raw:
        return None
    compact = _compact(raw)
    if raw in MAKE_ALIASES:
        return MAKE_ALIASES[raw]
    if compact in MAKE_ALIASES:
        return MAKE_ALIASES[compact]
    for key, slug in MAKE_ALIASES.items():
        k = _compact(key)
        if k == compact:
            return slug
        # mercedesbenz → mercedes; не «mini» внутри mitsubishi
        if len(k) >= 5 and compact.startswith(k):
            return slug
    markas = load_markas()
    for code, name in markas:
        if _compact(code) == compact or _compact(name) == compact:
            return code
    token = slugify_token(raw)
    if token:
        tc = _compact(token)
        for code, _name in markas:
            if _compact(code) == tc:
                return code
    return token or None


def model_slug_candidates(model: str | None, title: str | None = None) -> list[str]:
    source = " ".join(x for x in (model or "", title or "") if x).strip().lower()
    if not source:
        return []
    source = re.sub(r"\b(19|20)\d{2}\b", " ", source)
    # марку убираем везде; Range Rover — модель Land Rover, не марка
    brands = (
        r"bmw|audi|mercedes(?:-benz)?|volkswagen|vw|toyota|honda|nissan|ford|opel|"
        r"peugeot|renault|hyundai|kia|mazda|mitsubishi|subaru|suzuki|volvo|lexus|"
        r"jeep|porsche|mini|skoda|seat|fiat|tesla|land[\s-]?rover|alfa[\s-]?romeo|"
        r"rolls[\s-]?royce|infiniti|acura|lincoln|buick|cadillac|chrysler|dodge|"
        r"chevrolet|gmc|ram|genesis|maserati|jaguar|bentley|smart|saab|pontiac|"
        r"hummer|scion|isuzu|ssangyong|great[\s-]?wall|haval|geely|chery"
    )
    source = re.sub(rf"\b(?:{brands})\b", " ", source, flags=re.I)
    noise = (
        r"\b(tdi|cdi|hdi|d4d|gdi|tfsi|tsi|fsi|cgi|mjet|crdi|dci|bluehdi|ecoboost|"
        r"xdrive|quattro|4matic|awd|4wd|2wd|fwd|rwd|auto|manual|luxury|premium|"
        r"edition|series|class|dr|door|estate|coupe|cabrio|sedan|hatch|suv|pickup|"
        r"van|diesel|petrol|hybrid|plug[\s-]?in|i|si|ci|n|l|d)\b"
    )
    cleaned = re.sub(noise, " ", source, flags=re.I)
    tokens = re.findall(r"[a-z0-9]+", cleaned)
    if not tokens:
        tokens = re.findall(r"[a-z0-9]+", source)
    out: list[str] = []

    def add(value: str) -> None:
        v = slugify_token(value)
        if v and v not in out:
            out.append(v)

    if tokens:
        add(tokens[0])
        # C300 / A250 / GLC350 → буква класса на bamper (c, a, glc)
        m = re.match(r"^([a-z]{1,4})\d{2,3}[a-z]?$", tokens[0])
        if m:
            add(m.group(1))
        # BMW 330i / 535i → серия 3 / 5
        m = re.match(r"^([1-8])(\d{2})[a-z]?$", tokens[0])
        if m:
            add(m.group(1))
            add(m.group(1) + m.group(2))
        if len(tokens) >= 2:
            add(f"{tokens[0]}-{tokens[1]}")
            add("".join(tokens[:2]))
            add(f"{tokens[0]}{tokens[1]}")
        if tokens[0].isdigit() and len(tokens) >= 2:
            add(tokens[1])
        add("".join(tokens[:3]))
        add("".join(tokens[:4]))
    if model:
        add(model)
        add(model.replace(" ", ""))
    return out[:12]


def year_window(year: int | None) -> tuple[int, int] | None:
    """Bamper принимает годы только в пути /god_2013-2015/, query god1/god2 почти не фильтрует."""
    if year is None:
        return None
    try:
        y = int(year)
    except (TypeError, ValueError):
        return None
    if not (1980 <= y <= 2035):
        return None
    return max(1980, y - 1), min(2035, y + 1)


def parse_engine_volume(value: str | None) -> str | None:
    """Bamper «Объем: 1.6» — одна цифра после точки."""
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:l|л)\b", text, re.I)
    if match:
        try:
            vol = float(match.group(1).replace(",", "."))
        except ValueError:
            return None
        if 0.5 <= vol <= 8.5:
            return f"{vol:.1f}"
    match = re.search(r"(\d{3,4})\s*(?:cc|см|cm3|см3)", text, re.I)
    if match:
        cc = int(match.group(1))
        if 600 <= cc <= 8500:
            return f"{round(cc / 1000, 1):.1f}"
    match = re.search(r"\b(\d\.\d)\b", text)
    if match:
        try:
            vol = float(match.group(1))
        except ValueError:
            return None
        if 0.5 <= vol <= 8.5:
            return f"{vol:.1f}"
    return None


def map_bamper_fuel(value: str | None) -> str | None:
    text = str(value or "").lower()
    if re.search(r"hybrid|гибрид|phev|mhev|h.?ev", text):
        return "gibrid"
    if re.search(r"electric|электро|\bev\b|bev", text):
        return "elektro"
    if re.search(r"diesel|дизел|tdi|tdci|hdi|cdi|dci|\btd\b", text):
        return "dizel"
    if re.search(r"petrol|gasoline|бензин|unleaded|tfsi|tsi|gdi|mpi|\bgas\b", text):
        return "benzin"
    return None


def map_bamper_gearbox(value: str | None) -> str | None:
    text = str(value or "").lower()
    if re.search(r"cvt|variator|вариатор", text):
        return "variator"
    if re.search(r"robot|dsg|dct|s-tronic|пдк|робот", text):
        return "robot"
    if re.search(r"manual|механик|мкпп|\bmt\b", text):
        return "mehanika"
    if re.search(r"auto|акпп|tiptronic|automatic|\bat\b|авт", text):
        return "avtomat"
    return None


def map_bamper_body(value: str | None) -> str | None:
    text = str(value or "").lower()
    if re.search(r"hatch|хэтч", text):
        return "hatchback"
    if re.search(r"estate|wagon|universal|avant|touring|универсал", text):
        return "universal"
    if re.search(r"suv|внедорож|crossover|кроссовер", text):
        return "vnedorozhnik"
    if re.search(r"minivan|mpv|минивэн", text):
        return "miniven"
    if re.search(r"coupe|купе", text):
        return "cupe"
    if re.search(r"liftback|лифтбек", text):
        return "liftbek"
    if re.search(r"pick.?up|пикап", text):
        return "pickup"
    if re.search(r"convertible|cabriolet|кабрио", text):
        return "cabriolet"
    if re.search(r"microbus|микроавтобус", text):
        return "mikroavtobus"
    if re.search(r"van|фургон|panel van", text):
        return "furgon"
    if re.search(r"truck|грузовик|lorry", text):
        return "gruzovik"
    if re.search(r"sedan|saloon|седан", text):
        return "sedan"
    return None


_FUEL_LABEL = {"benzin": "бензин", "dizel": "дизель", "gibrid": "гибрид", "elektro": "электро"}
_GEAR_LABEL = {"avtomat": "АКПП", "mehanika": "МКПП", "robot": "робот", "variator": "вариатор"}
_BODY_LABEL = {
    "sedan": "седан",
    "hatchback": "хэтчбек",
    "universal": "универсал",
    "vnedorozhnik": "внедорожник",
    "miniven": "минивэн",
    "cupe": "купе",
    "liftbek": "лифтбек",
    "pickup": "пикап",
    "cabriolet": "кабриолет",
    "mikroavtobus": "микроавтобус",
    "furgon": "фургон",
    "gruzovik": "грузовик",
}


def build_advanced_filters(
    *,
    year: int | None = None,
    engine: str | None = None,
    fuel: str | None = None,
    transmission: str | None = None,
    body_style: str | None = None,
) -> dict[str, Any]:
    """Поля «Больше параметров поиска» на bamper.by."""
    window = year_window(year)
    filters: dict[str, Any] = {"more": "Y"}
    if window:
        filters["god1"] = str(window[0])
        filters["god2"] = str(window[1])
        filters["year_from"] = window[0]
        filters["year_to"] = window[1]
    volume = parse_engine_volume(engine)
    if volume:
        filters["enginevalue"] = volume
    fuel_code = map_bamper_fuel(fuel) or map_bamper_fuel(engine)
    if fuel_code:
        filters["toplivo"] = fuel_code
        filters["toplivo_label"] = _FUEL_LABEL.get(fuel_code, fuel_code)
    gear = map_bamper_gearbox(transmission)
    if gear:
        filters["korobka"] = gear
        filters["korobka_label"] = _GEAR_LABEL.get(gear, gear)
    body = map_bamper_body(body_style)
    if body:
        filters["kuzov"] = body
        filters["kuzov_label"] = _BODY_LABEL.get(body, body)
    return filters


def part_search_url(
    marka: str,
    model: str,
    code: str,
    year: int | None = None,
    filters: dict[str, Any] | None = None,
) -> str:
    from urllib.parse import urlencode

    path = (
        f"{BAMPER_BASE}/zchbu/zapchast_{quote(code, safe='')}"
        f"/marka_{quote(marka, safe='')}/model_{quote(model, safe='')}/"
    )
    extra = dict(filters or {})
    window = year_window(year)
    if extra.get("year_from") and extra.get("year_to"):
        path += f"god_{extra['year_from']}-{extra['year_to']}/"
    elif extra.get("god1") and extra.get("god2"):
        path += f"god_{extra['god1']}-{extra['god2']}/"
    elif window:
        path += f"god_{window[0]}-{window[1]}/"
    query: dict[str, str] = {}
    for key in ("enginevalue", "toplivo", "korobka", "kuzov"):
        val = extra.get(key)
        if val not in (None, ""):
            query[key] = str(val)
    if query:
        query["more"] = "Y"
        return path + "?" + urlencode(query)
    return path


def load_parts_catalog(*, refresh: bool = False) -> list[dict[str, str]]:
    global _PARTS_MEM
    with _PARTS_LOCK:
        if _PARTS_MEM is not None and not refresh:
            return list(_PARTS_MEM)
        if PARTS_CACHE.is_file() and not refresh:
            try:
                raw = json.loads(PARTS_CACHE.read_text(encoding="utf-8"))
                items = [
                    {"code": str(x["CODE"]), "name": str(x["NAME"])}
                    for x in raw
                    if x.get("CODE") and x.get("NAME")
                ]
                if items:
                    _PARTS_MEM = items
                    return list(items)
            except Exception as exc:
                log.warning("bamper parts cache: %s", exc)
        # тянем каталог с bamper
        try:
            _, text = _http(
                f"{BAMPER_BASE}/ajax/getZapchastiNalichie.php",
                data={"marka": "bmw", "model": "x5"},
            )
            payload = json.loads(text)
            raw_items = payload.get("ITEMS") or []
            items = [
                {"code": str(x["CODE"]), "name": str(x["NAME"])}
                for x in raw_items
                if x.get("CODE") and x.get("NAME")
            ]
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            PARTS_CACHE.write_text(
                json.dumps(
                    [{"CODE": i["code"], "NAME": i["name"]} for i in items],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            _PARTS_MEM = items
            log.info("Bamper: каталог запчастей %s шт.", len(items))
            return list(items)
        except Exception as exc:
            log.error("Не удалось загрузить каталог Bamper: %s", exc)
            return list(_PARTS_MEM or [])


def _select_options(html: str, name: str) -> list[tuple[str, str]]:
    block = re.search(
        rf'<select[^>]*(?:name|id)="{re.escape(name)}"[^>]*>(.*?)</select>',
        html,
        re.I | re.S,
    )
    if not block:
        return []
    return [
        (v, t.strip())
        for v, t in re.findall(
            r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)',
            block.group(1),
            re.I,
        )
        if v
    ]


def _selected_values(html: str, name: str) -> list[str]:
    block = re.search(
        rf'<select[^>]*(?:name|id)="{re.escape(name)}"[^>]*>(.*?)</select>',
        html,
        re.I | re.S,
    )
    if not block:
        return []
    out: list[str] = []
    for attrs1, value, attrs2 in re.findall(
        r'<option([^>]*)value="([^"]*)"([^>]*)>',
        block.group(1),
        re.I,
    ):
        if value and ("selected" in attrs1.lower() or "selected" in attrs2.lower()):
            out.append(value)
    return out


def _filter_applied(html: str, *, marka: str, model: str | None = None) -> bool:
    """Bamper игнорит неверный slug в URL и показывает все марки — проверяем select."""
    selected_marka = {x.lower() for x in _selected_values(html, "MARKA")}
    selected_marka |= {x.lower() for x in _selected_values(html, "marka")}
    if marka.lower() not in selected_marka:
        return False
    if not model:
        return True
    selected_model = {x.lower() for x in _selected_values(html, "MODEL")}
    selected_model |= {x.lower() for x in _selected_values(html, "model")}
    # На выдаче список моделей часто пустой (подгружается ajax) — тогда не требуем selected.
    if not selected_model:
        return True
    return model.lower() in selected_model


def _ad_cars(html: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", c).strip()
        for _part, c in re.findall(r"<b>([^<]+)</b>\s*к\s*([^<]+?)\s*</a>", html, re.I)
    ]


def _ads_match_model(html: str, model: str) -> bool:
    """Отсекаем выдачу «все Mercedes», если в URL была неверная модель."""
    cars = _ad_cars(html)
    if len(cars) < 3:
        return True
    slug = re.sub(r"[^a-z0-9]", "", (model or "").lower())
    if not slug:
        return True
    chassis = re.search(r"[wcxh]\d{3}", slug)
    hits = 0
    sample = cars[:15]
    for car in sample:
        compact = re.sub(r"[^a-z0-9]", "", car.lower())
        if len(slug) >= 2 and slug in compact:
            hits += 1
        elif chassis and chassis.group(0) in compact:
            hits += 1
        elif len(slug) <= 2 and re.search(rf"\b{re.escape(slug)}\b", car, re.I):
            hits += 1
    return hits >= max(2, len(sample) // 3)


def _listing_matches_vehicle(html: str, marka: str, model: str) -> bool:
    if not _filter_applied(html, marka=marka):
        return False
    return _ads_match_model(html, model)


def _fetch_marka_models(marka: str) -> list[tuple[str, str]]:
    key = (marka or "").lower()
    with _MODELS_LOCK:
        cached = _MODELS_MEM.get(key)
    if cached is not None:
        return list(cached)
    url = f"{BAMPER_BASE}/zchbu/zapchast_bamper-peredniy/marka_{quote(marka, safe='')}/"
    try:
        _, html = _http(url, timeout=22)
    except Exception as exc:
        log.warning("Bamper models %s: %s", marka, exc)
        return []
    if not _filter_applied(html, marka=marka):
        return []
    opts = _select_options(html, "MODEL") or _select_options(html, "model")
    with _MODELS_LOCK:
        _MODELS_MEM[key] = opts
    return opts


def _pick_model_slug(
    candidates: list[str],
    models: list[tuple[str, str]],
    *,
    year: int | None = None,
) -> str | None:
    if not candidates:
        return None
    by_code = {code.lower(): code for code, _ in models}
    by_name = {name.lower(): code for code, name in models if name}

    # Mercedes letter-class + год → конкретный кузов (A W176 и т.п.)
    year_map = {
        "a": [
            (1997, 2004, "aw168"),
            (2004, 2012, "aw169"),
            (2012, 2018, "aw176"),
            (2018, 2035, "aw177"),
        ],
        "c": [
            (2000, 2007, "cw203"),
            (2007, 2014, "cw204"),
            (2014, 2021, "cw205"),
            (2021, 2035, "cw206"),
        ],
        "e": [
            (2002, 2009, "ew211"),
            (2009, 2016, "ew212"),
            (2016, 2023, "ew213"),
            (2023, 2035, "ew214"),
        ],
        "s": [
            (1998, 2005, "sw220"),
            (2005, 2013, "sw221"),
            (2013, 2020, "sw222"),
            (2020, 2035, "sw223"),
        ],
        "gla": [
            (2013, 2019, "glax156"),
            (2019, 2035, "glah247"),
        ],
        "glb": [(2019, 2035, "glbx247")],
        "glc": [
            (2015, 2022, "glcx253"),
            (2022, 2035, "glcx254"),
        ],
        "gle": [
            (2015, 2019, "glew166"),
            (2019, 2035, "glew167"),
        ],
        "3": [
            (2005, 2012, "3e90e91e92e93"),
            (2012, 2019, "3f30f31gtf34"),
            (2019, 2035, "3g20g21"),
        ],
        "5": [
            (2003, 2010, "5e60e61"),
            (2010, 2017, "5f10f11"),
            (2017, 2024, "5g30g31"),
        ],
        "x5": [
            (2006, 2013, "x5e70"),
            (2013, 2018, "x5f15"),
            (2018, 2035, "x5g05"),
        ],
    }
    if year:
        for cand in candidates:
            key = cand.lower().replace("-", "")
            for lo, hi, code in year_map.get(key, []):
                if lo <= year <= hi and code.lower() in by_code:
                    return by_code[code.lower()]

    # 1) точное совпадение кода — берём самый длинный (range rover sport > range rover)
    exact = [by_code[c.lower()] for c in candidates if c.lower() in by_code]
    if exact:
        return max(exact, key=len)

    # 2) совпадение по названию опции
    name_hits = [by_name[c.lower()] for c in candidates if c.lower() in by_name]
    if name_hits:
        return max(name_hits, key=len)

    # 3) префикс — только длинные slug, иначе «a» цепляет Actros; длиннее код лучше
    prefix_hits: list[str] = []
    for cand in candidates:
        c = cand.lower()
        if len(c) < 3:
            continue
        for code, name in models:
            cl, nl = code.lower(), name.lower()
            if cl == c or nl == c or cl.startswith(c) or c in nl.split():
                prefix_hits.append(code)
    if prefix_hits:
        return max(prefix_hits, key=len)

    return None


def resolve_vehicle(
    *,
    make: str | None,
    model: str | None = None,
    year: int | None = None,
    title: str | None = None,
    engine: str | None = None,
    fuel: str | None = None,
    transmission: str | None = None,
    body_style: str | None = None,
) -> dict[str, Any]:
    marka = make_slug(make)
    if not marka and title:
        # title: "2004 BMW X5 ..."
        m = re.match(r"^\s*(?:(?:19|20)\d{2}\s+)?([A-Za-zА-Яа-яЁё\-]+)", title or "")
        if m:
            marka = make_slug(m.group(1))
    # запасные slug марки, если алиас устарел
    marka_tries = []
    for x in (marka, make_slug(make or ""), slugify_token(make or "")):
        if x and x not in marka_tries:
            marka_tries.append(x)
    if marka == "mercedes-benz" and "mercedes" not in marka_tries:
        marka_tries.insert(0, "mercedes")

    candidates = model_slug_candidates(model, title)
    chosen = candidates[0] if candidates else None
    models: list[tuple[str, str]] = []
    resolved_marka = marka

    for try_marka in marka_tries:
        models = _fetch_marka_models(try_marka)
        if models:
            resolved_marka = try_marka
            break
        # страница без списка моделей — всё же проверим, что марка выбирается
        try:
            url = f"{BAMPER_BASE}/zchbu/zapchast_bamper-peredniy/marka_{quote(try_marka, safe='')}/"
            _, html = _http(url, timeout=18)
            if _filter_applied(html, marka=try_marka):
                resolved_marka = try_marka
                break
        except Exception:
            continue

    if resolved_marka and candidates:
        if models:
            chosen = _pick_model_slug(candidates, models, year=year)
        else:
            # проверка, что model slug реально применяется в фильтре
            for cand in candidates[:5]:
                url = part_search_url(resolved_marka, cand, "bamper-peredniy", year)
                try:
                    _, html = _http(url, timeout=18)
                    if _filter_applied(html, marka=resolved_marka, model=cand):
                        chosen = cand
                        break
                except Exception:
                    continue

    window = year_window(year)
    filters = build_advanced_filters(
        year=year,
        engine=engine,
        fuel=fuel,
        transmission=transmission,
        body_style=body_style,
    )
    return {
        "make": make,
        "model": model,
        "year": year,
        "year_from": window[0] if window else None,
        "year_to": window[1] if window else None,
        "marka": resolved_marka,
        "model_slug": chosen,
        "model_candidates": candidates,
        "engine": engine,
        "fuel": fuel,
        "transmission": transmission,
        "body_style": body_style,
        "filters": filters,
        "enginevalue": filters.get("enginevalue"),
        "toplivo": filters.get("toplivo"),
        "toplivo_label": filters.get("toplivo_label"),
        "korobka": filters.get("korobka"),
        "korobka_label": filters.get("korobka_label"),
        "kuzov": filters.get("kuzov"),
        "kuzov_label": filters.get("kuzov_label"),
    }


def _parse_count(html: str) -> int | None:
    # Bamper часто показывает общий «Найдено 501» не по детали — берём объявления на странице
    ids = set(re.findall(r"/zapchast_[a-z0-9\-]+/(\d+-\d+)/", html, re.I))
    if ids:
        # если есть пагинация — это минимум (первая страница)
        pages = [int(x) for x in re.findall(r"[?&]PAGEN_1=(\d+)", html)]
        page_ads = len(ids)
        if pages:
            last = max(pages)
            # грубая оценка: ~page_ads на страницу, кроме возможно неполной последней
            return max(page_ads, (last - 1) * page_ads + 1)
        return page_ads
    prices = len(re.findall(r'class="item-price"', html, re.I))
    if prices:
        return prices
    m = re.search(r"Найдено\s+(\d[\d\s]*)\s+объявлен", html, re.I)
    if not m:
        return None
    return int(re.sub(r"\s+", "", m.group(1)))


def _parse_prices(html: str) -> list[int]:
    prices: list[int] = []
    for block in re.findall(r'<h2 class="item-price">(.*?)</h2>', html, re.I | re.S):
        m = re.search(r">\s*([\d\s]+)\s*<sup", block)
        if not m:
            m = re.search(r"([\d\s]{2,})", block)
        if not m:
            continue
        val = int(re.sub(r"\s+", "", m.group(1)))
        if 5 <= val <= 1_000_000:
            prices.append(val)
    return prices


def scrape_part(
    marka: str,
    model: str,
    code: str,
    name: str,
    year: int | None = None,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = part_search_url(marka, model, code, year, filters)
    row: dict[str, Any] = {
        "code": code,
        "name": name,
        "url": url,
        "count": None,
        "min_byn": None,
        "avg_byn": None,
        "samples": [],
        "ok": False,
        "error": None,
    }
    time.sleep(0.05)
    try:
        _, html = _http(url, timeout=35)
        if not _listing_matches_vehicle(html, marka, model):
            log.warning("Bamper: страница не по авто %s/%s %s", marka, model, url)
            row["count"] = 0
            row["ok"] = True
            return row
        prices = _parse_prices(html)
        count = _parse_count(html)
        row["count"] = count if count is not None else (len(prices) if prices else 0)
        if prices:
            row["min_byn"] = min(prices)
            row["avg_byn"] = round(sum(prices) / len(prices))
            row["samples"] = prices[:8]
            if not row["count"]:
                row["count"] = len(prices)
        row["ok"] = True
    except HTTPError as exc:
        row["error"] = f"HTTP {exc.code}"
    except URLError as exc:
        row["error"] = str(exc.reason or exc)
    except Exception as exc:
        row["error"] = str(exc)
    return row


def _search_mode(mode: str | None) -> str:
    if str(mode or "").lower() in {"dismantle", "typical", "subset"}:
        return "dismantle"
    return "full"


def parts_for_mode(mode: str = "full") -> list[dict[str, str]]:
    """full = весь каталог Bamper; dismantle = типовой разбор авто."""
    catalog = load_parts_catalog()
    by_code = {p["code"]: p for p in catalog}
    if _search_mode(mode) == "full":
        return catalog
    out: list[dict[str, str]] = []
    for code in DISMANTLE_PART_CODES:
        item = by_code.get(code)
        if item:
            out.append(item)
    return out


def _part_totals(parts: list[dict[str, Any]]) -> tuple[int, int, int]:
    with_offers = 0
    sum_min = 0
    sum_avg = 0
    for row in parts:
        if not row.get("count"):
            continue
        with_offers += 1
        if row.get("min_byn"):
            sum_min += int(row["min_byn"])
        if row.get("avg_byn"):
            sum_avg += int(row["avg_byn"])
    return with_offers, sum_min, sum_avg


def build_parts_index(
    marka: str,
    model: str,
    year: int | None = None,
    *,
    mode: str = "full",
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Список деталей со ссылками на расширенный поиск под конкретное авто."""
    parts = parts_for_mode(mode)
    return [
        {
            "code": p["code"],
            "name": p["name"],
            "url": part_search_url(marka, model, p["code"], year, filters),
            "count": None,
            "min_byn": None,
            "avg_byn": None,
            "samples": [],
            "ok": False,
            "error": None,
        }
        for p in parts
    ]


def get_job(job_id: str) -> dict[str, Any] | None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def start_search_job(
    *,
    make: str | None,
    model: str | None = None,
    year: int | None = None,
    title: str | None = None,
    engine: str | None = None,
    fuel: str | None = None,
    transmission: str | None = None,
    body_style: str | None = None,
    scrape: bool = True,
    workers: int = 5,
    mode: str = "full",
) -> dict[str, Any]:
    vehicle = resolve_vehicle(
        make=make,
        model=model,
        year=year,
        title=title,
        engine=engine,
        fuel=fuel,
        transmission=transmission,
        body_style=body_style,
    )
    if not vehicle.get("marka") or not vehicle.get("model_slug"):
        raise ValueError(
            "Не удалось определить марку/модель авто с лота. Сначала подтяните лот в калькуляторе."
        )

    marka = vehicle["marka"]
    model_slug = vehicle["model_slug"]
    filters = vehicle.get("filters") or {}
    search_mode = _search_mode(mode)
    parts = build_parts_index(marka, model_slug, year, mode=search_mode, filters=filters)
    log.info(
        "Bamper расширенный поиск %s/%s год=%s объём=%s топливо=%s КПП=%s кузов=%s",
        marka,
        model_slug,
        f"{filters.get('god1')}-{filters.get('god2')}" if filters.get("god1") else year,
        filters.get("enginevalue") or "—",
        filters.get("toplivo") or "—",
        filters.get("korobka") or "—",
        filters.get("kuzov") or "—",
    )
    job_id = uuid.uuid4().hex[:12]
    job: dict[str, Any] = {
        "id": job_id,
        "status": "running" if scrape else "done",
        "mode": search_mode,
        "vehicle": vehicle,
        "total": len(parts),
        "done": 0 if scrape else len(parts),
        "with_offers": 0,
        "sum_min_byn": 0,
        "sum_avg_byn": 0,
        "parts": parts,
        "dismantle_codes": list(DISMANTLE_PART_CODES),
        "error": None,
        "started_at": time.time(),
        "finished_at": None if scrape else time.time(),
    }
    with _JOBS_LOCK:
        _JOBS[job_id] = job

    if not scrape:
        return get_job(job_id) or job

    def runner() -> None:
        local_parts = list(parts)
        done = 0
        try:
            with ThreadPoolExecutor(max_workers=max(1, min(8, int(workers)))) as pool:
                futures = {
                    pool.submit(
                        scrape_part,
                        marka,
                        model_slug,
                        p["code"],
                        p["name"],
                        year,
                        filters,
                    ): idx
                    for idx, p in enumerate(local_parts)
                }
                for fut in as_completed(futures):
                    idx = futures[fut]
                    try:
                        row = fut.result()
                    except Exception as exc:
                        row = {**local_parts[idx], "error": str(exc), "ok": False}
                    local_parts[idx] = row
                    done += 1
                    with_offers, sum_min, sum_avg = _part_totals(local_parts)
                    with _JOBS_LOCK:
                        current = _JOBS.get(job_id)
                        if not current:
                            return
                        if current.get("status") == "cancelled":
                            for f in futures:
                                f.cancel()
                            current["done"] = done
                            current["parts"] = local_parts
                            current["with_offers"] = with_offers
                            current["sum_min_byn"] = sum_min
                            current["sum_avg_byn"] = sum_avg
                            current["finished_at"] = time.time()
                            return
                        current["done"] = done
                        current["parts"] = local_parts
                        current["with_offers"] = with_offers
                        current["sum_min_byn"] = sum_min
                        current["sum_avg_byn"] = sum_avg
            with _JOBS_LOCK:
                current = _JOBS.get(job_id)
                if current and current.get("status") != "cancelled":
                    current["status"] = "done"
                    current["finished_at"] = time.time()
        except Exception as exc:
            log.exception("Bamper job %s failed", job_id)
            with _JOBS_LOCK:
                current = _JOBS.get(job_id)
                if current:
                    current["status"] = "error"
                    current["error"] = str(exc)
                    current["finished_at"] = time.time()

    threading.Thread(target=runner, name=f"bamper-{job_id}", daemon=True).start()
    return get_job(job_id) or job


def cancel_job(job_id: str) -> dict[str, Any] | None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        if job.get("status") == "running":
            job["status"] = "cancelled"
            job["finished_at"] = time.time()
        return dict(job)
