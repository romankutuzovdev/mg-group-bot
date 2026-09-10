"""Растаможка легкового авто в РБ (ЕАЭС) для физлиц — Решение Совета ЕЭК №107.

Ставки единого таможенного платежа (вместо пошлины+НДС) для личного пользования.
Утильсбор — постановление Совмина РБ (ставки с апреля 2026).
Электромобиль (чистый BEV): таможенный платёж = 0 (как при тарифной льготе / по запросу).
Гибриды PHEV/HEV/EREV под EV-льготу не попадают.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any
from urllib.request import urlopen

log = logging.getLogger("copart")

# Утильсбор физлицо M1, личное пользование (с 29.04.2026)
UTIL_FEE_UNDER_3_BYN = 624.92
UTIL_FEE_OVER_3_BYN = 1282.02
CUSTOMS_OPS_FEE_BYN = 120.0
EPTS_FEE_BYN = 80.4  # ориентир Белтаможсервис

# До 3 лет: max(% от стоимости, €/см³)
UNDER_3_BRACKETS = [
    # (max_price_eur inclusive, percent, eur_per_cc)
    (8500, 0.54, 2.5),
    (16700, 0.48, 3.5),
    (42300, 0.48, 5.5),
    (84500, 0.48, 7.5),
    (169000, 0.48, 15.0),
    (float("inf"), 0.48, 20.0),
]

# 3–5 лет и >5 лет: только €/см³ по объёму
AGE_3_5_CC = [
    (1000, 1.5),
    (1500, 1.7),
    (1800, 2.5),
    (2300, 2.7),
    (3000, 3.0),
    (float("inf"), 3.6),
]
AGE_OVER_5_CC = [
    (1000, 3.0),
    (1500, 3.2),
    (1800, 3.5),
    (2300, 4.8),
    (3000, 5.0),
    (float("inf"), 5.7),
]


def round2(value: float) -> float:
    return round(float(value) + 1e-9, 2)


def detect_engine_type(fuel: str | None = None, engine: str | None = None, title: str | None = None) -> str:
    """fuel | electric | erev | phev"""
    blob = " ".join(str(x or "") for x in (fuel, engine, title)).lower()
    if re.search(r"\berev\b|range.?extend|extended.?range", blob):
        return "erev"
    if re.search(r"\bphev\b|plug.?in\s*hybrid|подключаем", blob):
        return "phev"
    if re.search(
        r"\belectric\b|\bev\b|\bbev\b|электро|electricity|battery\s*electric|"
        r"tesla|электромобил|электромотор|электродвигател",
        blob,
    ):
        # чистый EV, не hybrid
        if re.search(r"hybrid|гибрид|hev\b|phev|erev", blob) and not re.search(
            r"\bbev\b|battery\s*electric|pure\s*electric|полностью\s*электр", blob
        ):
            return "phev"
        return "electric"
    if re.search(r"diesel|дизель|tdi|cdi|dci", blob):
        return "diesel"
    if re.search(r"hybrid|гибрид|\bhev\b", blob):
        return "phev"
    return "fuel"


def detect_fuel_kind(fuel: str | None, engine: str | None = None) -> str:
    blob = " ".join(str(x or "") for x in (fuel, engine)).lower()
    if re.search(r"diesel|дизель", blob):
        return "diesel"
    return "petrol"


def parse_engine_cc(engine: str | None, title: str | None = None) -> int | None:
    text = " ".join(str(x or "") for x in (engine, title))
    if not text.strip():
        return None
    # 1998 cc / 2000см3 / 2,0 л / 2.0L / 4.0L, V8
    m = re.search(r"(\d{3,4})\s*(?:cc|см\s*³|см3|cm3|куб)", text, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d)\s*[.,]\s*(\d)\s*[lл]\b", text, re.I)
    if m:
        return int(m.group(1)) * 1000 + int(m.group(2)) * 100
    m = re.search(r"(\d)[.,](\d)\s*(?:litre|liter)\b", text, re.I)
    if m:
        return int(m.group(1)) * 1000 + int(m.group(2)) * 100
    m = re.search(r"\b(\d{1,2})\s*[lл]\b", text, re.I)
    if m:
        liters = int(m.group(1))
        if 1 <= liters <= 8:
            return liters * 1000
    m = re.search(r"\b(\d{4})\b", text)
    if m:
        n = int(m.group(1))
        if 600 <= n <= 8000:
            return n
    return None


def vehicle_age_band(year: int | None, *, as_of: date | None = None) -> str:
    """under3 | age3to5 | over5"""
    as_of = as_of or date.today()
    if not year or year < 1950 or year > as_of.year + 1:
        return "age3to5"
    # возраст с года выпуска (как на таможне — от даты производства; год ≈ консервативно)
    age = as_of.year - int(year)
    if age < 3:
        return "under3"
    if age <= 5:
        return "age3to5"
    return "over5"


def _cc_rate(volume_cc: int, table: list[tuple[float, float]]) -> float:
    for max_cc, rate in table:
        if volume_cc <= max_cc:
            return rate
    return table[-1][1]


def _under3_bracket(price_eur: float) -> tuple[float, float]:
    for max_price, percent, per_cc in UNDER_3_BRACKETS:
        if price_eur <= max_price:
            return percent, per_cc
    return UNDER_3_BRACKETS[-1][1], UNDER_3_BRACKETS[-1][2]


_RATES_CACHE: dict[str, float] | None = None
_RATES_CACHE_AT: float = 0.0
_RATES_TTL_SEC = 300.0


def fetch_nbrb_rates(*, force: bool = False) -> dict[str, float]:
    """Курсы НБРБ: EUR, USD → BYN. Кеш 5 мин, короткий таймаут — не блокирует UI."""
    global _RATES_CACHE, _RATES_CACHE_AT
    import time

    now = time.time()
    if (
        not force
        and _RATES_CACHE
        and (now - _RATES_CACHE_AT) < _RATES_TTL_SEC
    ):
        return dict(_RATES_CACHE)

    out: dict[str, float] = {}
    try:
        with urlopen(
            "https://www.nbrb.by/api/exrates/rates?periodicity=0",
            timeout=2.5,
        ) as resp:
            rows = json.loads(resp.read().decode())
        for row in rows or []:
            cur = str(row.get("Cur_Abbreviation") or "").upper()
            if cur not in {"EUR", "USD"}:
                continue
            scale = float(row.get("Cur_Scale") or 1) or 1.0
            official = float(row.get("Cur_OfficialRate") or 0)
            if official > 0:
                out[cur] = official / scale
    except Exception as exc:
        log.warning("НБРБ курсы недоступны: %s", exc)

    if "EUR" in out and "USD" in out:
        try:
            out["_usd_eur"] = float(out["USD"]) / float(out["EUR"])
        except Exception:
            out["_usd_eur"] = 0.92
    else:
        # fallback: прошлый кеш или константы
        if _RATES_CACHE:
            return dict(_RATES_CACHE)
        out = {"USD": 3.2, "EUR": 3.45, "_usd_eur": 3.2 / 3.45}
        try:
            with urlopen(
                "https://api.frankfurter.app/latest?from=USD&to=EUR",
                timeout=2.0,
            ) as resp:
                data = json.loads(resp.read().decode())
                usd_eur = float(data["rates"]["EUR"])
                if usd_eur > 0:
                    out["_usd_eur"] = usd_eur
        except Exception as exc:
            log.warning("Frankfurter недоступен: %s", exc)
            out.setdefault("_usd_eur", 0.92)

    _RATES_CACHE = dict(out)
    _RATES_CACHE_AT = now
    return dict(out)


def _usd_to_eur(usd: float, rates: dict[str, float]) -> float:
    cross = float(rates.get("_usd_eur") or 0)
    if cross > 0:
        return round2(usd * cross)
    usd_byn = float(rates.get("USD") or 0)
    eur_byn = float(rates.get("EUR") or 0)
    if usd_byn > 0 and eur_byn > 0:
        return round2(usd * usd_byn / eur_byn)
    return round2(usd * 0.92)


def calculate_customs_by(
    *,
    price_usd: float | None = None,
    price_eur: float | None = None,
    engine_cc: int | None = None,
    year: int | None = None,
    age_band: str | None = None,
    engine_type: str | None = None,
    fuel: str | None = None,
    engine: str | None = None,
    title: str | None = None,
    person: str = "individual",  # individual | company
    benefit_50: bool = False,
    include_epts: bool = True,
    rates: dict[str, float] | None = None,
) -> dict[str, Any]:
    rates = rates or fetch_nbrb_rates()
    eng_type = (engine_type or detect_engine_type(fuel, engine, title) or "fuel").lower()
    if eng_type in {"ev", "bev", "electro", "electricity"}:
        eng_type = "electric"
    band = (age_band or vehicle_age_band(year)).lower()
    if band in {"under_3", "<3", "less3"}:
        band = "under3"
    elif band in {"3_5", "3-5", "3to5", "from3to5"}:
        band = "age3to5"
    elif band in {">5", "over_5", "more5"}:
        band = "over5"

    vol = int(engine_cc) if engine_cc and int(engine_cc) > 0 else parse_engine_cc(engine, title)
    if price_eur is not None and float(price_eur) > 0:
        customs_value_eur = round2(float(price_eur))
    else:
        customs_value_eur = _usd_to_eur(float(price_usd or 0), rates)

    is_electric = eng_type == "electric"
    is_individual = str(person or "individual").lower() not in {"company", "legal", "jur", "юр"}

    duty_eur = 0.0
    duty_note = ""
    formula = ""

    if is_electric:
        duty_eur = 0.0
        duty_note = (
            "Электромобиль (BEV): единый таможенный платёж = 0 "
            "(тарифная льгота / правило калькулятора). Гибриды не считаются EV."
        )
        formula = "EV → 0"
    elif not is_individual:
        # Упрощённо для юрлица: пошлина 15% + НДС 20% (ориентир; точные коды ТН ВЭД могут отличаться)
        duty_base = round2(customs_value_eur * 0.15)
        vat = round2((customs_value_eur + duty_base) * 0.20)
        duty_eur = round2(duty_base + vat)
        duty_note = "Юрлицо (упрощённо): пошлина 15% + НДС 20% от (стоимость+пошлина). Уточняйте по коду ТН ВЭД."
        formula = f"15%×{customs_value_eur} + 20%×({customs_value_eur}+{duty_base})"
        if eng_type in {"erev"}:
            duty_note += " EREV считается как ДВС/гибрид."
    else:
        if not vol or vol < 50:
            return {
                "ok": False,
                "error": "Укажите объём двигателя (см³) для расчёта пошлины",
                "engine_type": eng_type,
                "age_band": band,
                "customs_value_eur": customs_value_eur,
            }
        if band == "under3":
            percent, per_cc = _under3_bracket(customs_value_eur)
            by_price = round2(customs_value_eur * percent)
            by_cc = round2(vol * per_cc)
            duty_eur = max(by_price, by_cc)
            formula = f"max({percent:.0%}×{customs_value_eur}={by_price}; {vol}×{per_cc}={by_cc})"
            duty_note = "До 3 лет: max(% от стоимости, €/см³) — Решение ЕЭК №107"
        elif band == "over5":
            per_cc = _cc_rate(vol, AGE_OVER_5_CC)
            duty_eur = round2(vol * per_cc)
            formula = f"{vol}×{per_cc} €/см³"
            duty_note = "Старше 5 лет: только €/см³ — Решение ЕЭК №107"
        else:
            per_cc = _cc_rate(vol, AGE_3_5_CC)
            duty_eur = round2(vol * per_cc)
            formula = f"{vol}×{per_cc} €/см³"
            duty_note = "От 3 до 5 лет: только €/см³ — Решение ЕЭК №107"

    if benefit_50 and is_individual and not is_electric and duty_eur > 0:
        duty_eur = round2(duty_eur * 0.5)
        duty_note += " · льгота 50% (Указ №140)"

    util_byn = UTIL_FEE_UNDER_3_BYN if band == "under3" else UTIL_FEE_OVER_3_BYN
    # Для EV утилсбор всё равно платится по правилам ГТК — оставляем в итоге
    ops_byn = CUSTOMS_OPS_FEE_BYN
    epts_byn = EPTS_FEE_BYN if include_epts else 0.0

    eur_byn = float(rates.get("EUR") or 0) or 3.45
    usd_byn = float(rates.get("USD") or 0) or 3.2
    duty_byn = round2(duty_eur * eur_byn)
    total_byn = round2(duty_byn + util_byn + ops_byn + epts_byn)
    total_eur = round2(duty_eur + (util_byn + ops_byn + epts_byn) / eur_byn)
    total_usd = round2(total_byn / usd_byn) if usd_byn else None

    band_label = {
        "under3": "менее 3 лет",
        "age3to5": "от 3 до 5 лет",
        "over5": "более 5 лет",
    }.get(band, band)

    return {
        "ok": True,
        "engine_type": eng_type,
        "is_electric": is_electric,
        "person": "individual" if is_individual else "company",
        "age_band": band,
        "age_band_label": band_label,
        "year": year,
        "engine_cc": vol,
        "customs_value_eur": customs_value_eur,
        "customs_value_usd": round2(float(price_usd)) if price_usd not in (None, "") else None,
        "duty_eur": duty_eur,
        "duty_byn": duty_byn,
        "duty_note": duty_note,
        "formula": formula,
        "benefit_50": bool(benefit_50 and is_individual),
        "util_fee_byn": util_byn,
        "customs_ops_fee_byn": ops_byn,
        "epts_fee_byn": epts_byn,
        "total_byn": total_byn,
        "total_eur": total_eur,
        "total_usd": total_usd,
        "rates": {
            "EUR_BYN": round2(eur_byn),
            "USD_BYN": round2(usd_byn),
            "source": "nbrb" if rates.get("EUR") else "fallback",
        },
        "notes": [
            "Ориентир для физлица (личное пользование). Окончательную сумму определяет таможня.",
            "Возраст считается от года выпуска (дата производства точнее).",
            *(
                [
                    "С 05.09.2026 квота беспошлинного ввоза EV физлицами исчерпана (ГТК); "
                    "в калькуляторе для EV платёж всё равно = 0 по вашему правилу."
                ]
                if is_electric
                else []
            ),
        ],
    }
