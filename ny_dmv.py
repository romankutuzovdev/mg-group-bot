"""Проверка Title / Lien Status на NY DMV (process.dmv.ny.gov/TitleStatus)."""

from __future__ import annotations

import re
from typing import Any

TITLE_STATUS_URL = "https://process.dmv.ny.gov/TitleStatus"

# NY DMV: максимум 5 букв или 4+slash (HA/DA, ME/BE).
_MAKE_CODES: dict[str, str] = {
    "ACURA": "ACURA",
    "ALFA": "ALFA",
    "AUDI": "AUDI",
    "BMW": "BMW",
    "BUICK": "BUICK",
    "CADILLAC": "CADIL",
    "CHEVROLET": "CHEVR",
    "CHEVY": "CHEVR",
    "CHRYSLER": "CHRYS",
    "DODGE": "DODGE",
    "FIAT": "FIAT",
    "FORD": "FORD",
    "GENESIS": "GENES",
    "GMC": "GMC",
    "HONDA": "HONDA",
    "HUMMER": "HUMME",
    "HYUNDAI": "HYUND",
    "INFINITI": "INFIN",
    "ISUZU": "ISUZU",
    "JAGUAR": "JAGUA",
    "JEEP": "JEEP",
    "KIA": "KIA",
    "LAND ROVER": "LAND",
    "LANDROVER": "LAND",
    "LEXUS": "LEXUS",
    "LINCOLN": "LINCO",
    "MASERATI": "MASER",
    "MAZDA": "MAZDA",
    "MERCEDES": "ME/BE",
    "MERCEDES-BENZ": "ME/BE",
    "MERCEDES BENZ": "ME/BE",
    "MERCURY": "MERCU",
    "MINI": "MINI",
    "MITSUBISHI": "MITSU",
    "NISSAN": "NISSA",
    "OLDSMOBILE": "OLDSM",
    "PLYMOUTH": "PLYMO",
    "PONTIAC": "PONTI",
    "PORSCHE": "PORSC",
    "RAM": "RAM",
    "SAAB": "SAAB",
    "SATURN": "SATUR",
    "SCION": "SCION",
    "SMART": "SMART",
    "SUBARU": "SUBAR",
    "SUZUKI": "SUZUK",
    "TESLA": "TESLA",
    "TOYOTA": "TOYOT",
    "VOLKSWAGEN": "VOLKS",
    "VW": "VOLKS",
    "VOLVO": "VOLVO",
    "HARLEY": "HA/DA",
    "HARLEY-DAVIDSON": "HA/DA",
    "HARLEY DAVIDSON": "HA/DA",
}


def normalize_vin(vin: str | None) -> str:
    s = re.sub(r"[^A-Za-z0-9]", "", str(vin or "").upper())
    # DMV: I→1, O→0 для VIN
    return s.replace("I", "1").replace("O", "0")


def dmv_make_code(make: str | None) -> str:
    raw = str(make or "").strip().upper()
    raw = re.sub(r"\s+", " ", raw)
    if not raw:
        return ""
    if raw in _MAKE_CODES:
        return _MAKE_CODES[raw]
    # частичное совпадение по ключу
    for key, code in _MAKE_CODES.items():
        if key in raw or raw in key:
            return code
    letters = re.sub(r"[^A-Z]", "", raw)
    if "/" in raw and len(raw) <= 5:
        return raw[:5]
    return letters[:5]


def _parse_result(body_text: str, url: str) -> dict[str, Any]:
    text = re.sub(r"[ \t]+", " ", body_text or "")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    low = text.lower()

    error = None
    if "#error" in (url or "").lower() or "does not match our records" in low:
        error = "Данные не совпали с записями NY DMV (проверьте VIN / год / make)."
    elif "required field" in low or "please enter" in low and "error" in low:
        error = "NY DMV: не заполнены обязательные поля."

    title_issued = None
    m = re.search(
        r"(?:title\s+(?:issue|issued|print(?:ed)?)\s*date|date\s+(?:title\s+)?(?:was\s+)?issued)\s*:?\s*([A-Za-z0-9/,\-\s]{4,40})",
        text,
        re.I,
    )
    if m:
        title_issued = m.group(1).strip()

    liens_count: int | None = None
    m = re.search(r"(?:number of liens|liens?\s*(?:recorded)?)\s*:?\s*(\d+)", text, re.I)
    if m:
        liens_count = int(m.group(1))
    elif re.search(r"\bno\s+liens?\b|\bliens?\s*:\s*none\b|\b0\s+liens?\b", low):
        liens_count = 0

    lienholders: list[str] = []
    for m in re.finditer(
        r"(?:lienholder|lien holder|pending lienholder)\s*:?\s*([^\n]{3,120})",
        text,
        re.I,
    ):
        name = m.group(1).strip(" .:;")
        if name and name.lower() not in {"n/a", "none", "—", "-"}:
            lienholders.append(name[:120])

    has_lien = None
    if liens_count is not None:
        has_lien = liens_count > 0
    elif lienholders:
        has_lien = True
    elif re.search(r"\bpending\s+lien\b|\blien\s+recorded\b", low):
        has_lien = True
    elif re.search(r"\bno\s+lien\b|\bfree and clear\b|\bclear title\b", low):
        has_lien = False

    # Краткий сниппет результата (без меню сайта)
    snippet = text
    for marker in ("Check Title or Lien Status", "Title / Lien Status", "Vehicle Identification"):
        idx = snippet.find(marker)
        if idx >= 0:
            snippet = snippet[idx:]
            break
    snippet = snippet[:1800].strip()

    ok = error is None and (has_lien is not None or title_issued or "lien" in low)
    status = "error" if error else ("ok" if ok else "unknown")
    summary = error
    if not summary:
        if has_lien is True:
            n = liens_count if liens_count is not None else len(lienholders) or "?"
            summary = f"Есть залог (lien): {n}"
            if lienholders:
                summary += " — " + "; ".join(lienholders[:3])
        elif has_lien is False:
            summary = "Залога (lien) нет"
            if title_issued:
                summary += f" · title issued: {title_issued}"
        elif title_issued:
            summary = f"Title issued: {title_issued}"
        else:
            summary = "Ответ NY DMV получен — проверьте детали ниже"

    return {
        "ok": status == "ok",
        "status": status,
        "summary": summary,
        "has_lien": has_lien,
        "liens_count": liens_count,
        "lienholders": lienholders,
        "title_issued": title_issued,
        "error": error,
        "page_url": url,
        "snippet": snippet,
    }


def check_title_status(page: Any, *, vin: str, year: int | str, make: str) -> dict[str, Any]:
    """Заполнить форму TitleStatus на уже открытой Playwright page и разобрать ответ."""
    vin_n = normalize_vin(vin)
    year_s = re.sub(r"\D", "", str(year or ""))[:4]
    make_code = dmv_make_code(make)
    if len(vin_n) < 11:
        return {
            "ok": False,
            "status": "error",
            "summary": "Нужен полный VIN (11–17 символов)",
            "has_lien": None,
            "error": "invalid_vin",
            "vin": vin_n,
            "year": year_s,
            "make_code": make_code,
        }
    if len(year_s) != 4:
        return {
            "ok": False,
            "status": "error",
            "summary": "Нужен 4-значный год модели",
            "has_lien": None,
            "error": "invalid_year",
            "vin": vin_n,
            "year": year_s,
            "make_code": make_code,
        }
    if not make_code:
        return {
            "ok": False,
            "status": "error",
            "summary": "Нужен make (марка) для NY DMV",
            "has_lien": None,
            "error": "invalid_make",
            "vin": vin_n,
            "year": year_s,
            "make_code": make_code,
        }

    page.goto(TITLE_STATUS_URL, wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_selector("#sVehIdNum", timeout=25_000)
    try:
        page.check("#vehicleRadio")
    except Exception:
        pass
    page.fill("#sVehIdNum", vin_n)
    page.fill("#sVehModelYear", year_s)
    page.fill("#sVehMake", make_code)
    page.click('input[type=submit][name=Continue], input[type=submit][value="Continue"]')
    page.wait_for_timeout(2500)
    try:
        page.wait_for_load_state("domcontentloaded", timeout=20_000)
    except Exception:
        pass
    page.wait_for_timeout(1500)

    body = ""
    try:
        body = page.inner_text("body")
    except Exception:
        body = page.content()

    parsed = _parse_result(body, page.url)
    parsed.update(
        {
            "vin": vin_n,
            "year": year_s,
            "make": str(make or "").strip(),
            "make_code": make_code,
            "source": "ny_dmv_title_status",
            "check_url": TITLE_STATUS_URL,
        }
    )
    return parsed
