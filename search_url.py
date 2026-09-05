from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, unquote, urlparse

KEY_LABELS = {
    "MAKE": "Марка",
    "MODL": "Модель",
    "MODEL": "Модель",
    "YEAR": "Год",
    "TITL": "Категория",
    "TITLE": "Категория",
    "SLG": "Категория",
    "LOCN": "Площадка",
    "LOCATION": "Площадка",
    "SITE": "Площадка",
    "YARD": "Площадка",
    "BODY": "Кузов",
    "BODT": "Кузов",
    "FUEL": "Топливо",
    "ODM": "Пробег",
    "MILE": "Пробег",
    "ORR": "Пробег",
    "DAMG": "Повреждение",
    "PRIC": "Цена",
    "BID": "Ставка",
    "VIN": "VIN",
    "COLOR": "Цвет",
    "CLR": "Цвет",
    "TRAN": "КПП",
    "DRIVE": "Привод",
    "ENG": "Двигатель",
}


def parse_copart_search(url: str) -> dict:
    params: list[dict] = []
    parsed = urlparse(url or "")
    query = parse_qs(parsed.query)

    raw = ""
    if "searchCriteria" in query:
        raw = query["searchCriteria"][0]
    criteria: dict = {}
    if raw:
        text = unquote(raw)
        try:
            criteria = json.loads(text)
        except json.JSONDecodeError:
            try:
                criteria = json.loads(unquote(text))
            except json.JSONDecodeError:
                criteria = {}

    filters = criteria.get("filter") or {}
    if isinstance(filters, dict):
        for key, values in filters.items():
            if not isinstance(values, list):
                values = [values]
            cleaned = [_clean_filter_value(str(item)) for item in values if item not in (None, "")]
            cleaned = [item for item in cleaned if item]
            if not cleaned:
                continue
            params.append(
                {
                    "key": str(key),
                    "label": KEY_LABELS.get(str(key).upper(), str(key)),
                    "value": ", ".join(cleaned),
                }
            )

    queries = criteria.get("query") or []
    extra = [str(item).strip() for item in queries if str(item).strip() and str(item).strip() != "*"]
    if extra:
        params.append({"key": "QUERY", "label": "Запрос", "value": ", ".join(extra)})

    if query.get("query") and not extra:
        q = query["query"][0].strip()
        if q and q != "*":
            params.append({"key": "QUERY", "label": "Запрос", "value": q})

    summary = " · ".join(item["value"] for item in params) or "Поиск Copart"
    return {"params": params, "summary": summary}


BIDCARS_FILTER_LABELS = {
    "make": "Марка",
    "model": "Модель",
    "type": "Тип",
    "status": "Статус",
    "auction-type": "Аукцион",
    "auction_type": "Аукцион",
    "exterior-color": "Цвет",
    "exterior_color": "Цвет",
    "color": "Цвет",
    "damage": "Повреждение",
    "primary-damage": "Повреждение",
    "location": "Площадка",
    "seller": "Продавец",
    "odometer-from": "Пробег от",
    "odometer-to": "Пробег до",
    "fuel": "Топливо",
    "transmission": "КПП",
    "drive": "Привод",
}


def parse_bidcars_search(url: str) -> dict:
    params: list[dict] = []
    parsed = urlparse(url or "")
    query = parse_qs(parsed.query)
    path = unquote(parsed.path or "")

    year_from = (query.get("year-from") or query.get("year_from") or [""])[0].strip()
    year_to = (query.get("year-to") or query.get("year_to") or [""])[0].strip()
    if year_from and year_to and year_from != year_to:
        params.append({"key": "YEAR", "label": "Год", "value": f"{year_from}–{year_to}"})
    elif year_from or year_to:
        params.append({"key": "YEAR", "label": "Год", "value": year_from or year_to})

    skip = {
        "search-type",
        "search_type",
        "year-from",
        "year_from",
        "year-to",
        "year_to",
        "page",
        "sort",
        "sort-by",
        "sort_by",
    }
    skip_values = {"", "all", "*", "any"}
    for key, values in query.items():
        low = str(key).lower()
        if low in skip:
            continue
        cleaned = [unquote(str(item)).strip() for item in values if item not in (None, "")]
        cleaned = [item for item in cleaned if item and item.lower() not in skip_values]
        if not cleaned:
            continue
        params.append(
            {
                "key": str(key),
                "label": BIDCARS_FILTER_LABELS.get(low, str(key)),
                "value": ", ".join(cleaned),
            }
        )

    path_q = re.sub(r"^/(?:[a-z]{2}/)?search(?:/results)?/?", "", path, flags=re.I).strip("/")
    if path_q and path_q.lower() not in {"results", "search"}:
        slug = re.sub(r"[-_]+", " ", path_q).strip()
        if slug:
            params.append({"key": "QUERY", "label": "Запрос", "value": slug})

    summary = " · ".join(item["value"] for item in params) or "Поиск Bid.cars"
    return {"params": params, "summary": summary}


def _clean_filter_value(raw: str) -> str:
    text = unquote(str(raw or "")).replace('\\"', '"').strip()
    match = re.search(r"\[(\d+)\s+TO\s+(\d+)\]", text, re.I)
    if match:
        return f"{match.group(1)}–{match.group(2)}"
    quoted = re.findall(r'"([^"]+)"', text)
    if quoted:
        text = ", ".join(quoted)
    else:
        if ":" in text:
            text = text.rsplit(":", 1)[-1].strip()
        text = text.strip(" \"'")
    upper = text.upper()
    if upper in {"B", "CAT B", "CATB"}:
        return "Cat B"
    if re.fullmatch(r"[A-Z]", upper):
        return f"Cat {upper}"
    return text
