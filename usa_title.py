"""Доплата за Title / Sale Doc по листу Title из «Ценообразование США.xlsx»."""

from __future__ import annotations

import json
import re
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent / "data" / "usa_title_tariffs.json"

_cache: dict | None = None
_cache_mtime: float | None = None


def _load() -> dict:
    global _cache, _cache_mtime
    try:
        mtime = DATA_PATH.stat().st_mtime if DATA_PATH.exists() else None
    except OSError:
        mtime = None
    if _cache is not None and mtime == _cache_mtime:
        return _cache
    if not DATA_PATH.exists():
        _cache = {"rules": [], "rows": []}
        _cache_mtime = mtime
        return _cache
    _cache = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    _cache_mtime = mtime
    return _cache


def _norm(text: str | None) -> str:
    s = str(text or "").lower()
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"[_/]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _has_token(text: str, token: str) -> bool:
    tok = _norm(token)
    if not tok:
        return False
    if " " in tok or len(tok) >= 5:
        return tok in text
    # короткие токены — по границам слов (lien, bos, acq…)
    return re.search(rf"(?<![a-z0-9]){re.escape(tok)}(?![a-z0-9])", text) is not None


def list_title_tariffs() -> list[dict]:
    """Список тарифов Title для ручного выбора в UI."""
    data = _load()
    items: list[dict] = []
    seen: set[str] = set()
    for row in data.get("rows") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        try:
            cost = float(row.get("cost_usd") or 0)
        except (TypeError, ValueError):
            cost = 0.0
        items.append(
            {
                "id": None,
                "name": name,
                "cost_usd": cost,
                "cost_raw": row.get("cost_raw") or ("без доплат" if cost <= 0 else f"$ {cost:g}"),
            }
        )
    for rule in data.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        name = str(rule.get("name") or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        try:
            cost = float(rule.get("cost_usd") or 0)
        except (TypeError, ValueError):
            cost = 0.0
        items.append(
            {
                "id": rule.get("id"),
                "name": name,
                "cost_usd": cost,
                "cost_raw": "без доплат" if cost <= 0 else f"$ {cost:g}",
            }
        )
    items.sort(key=lambda x: (float(x.get("cost_usd") or 0), str(x.get("name") or "")))
    return items


def lookup_title_fee(document_text: str | None) -> dict | None:
    """Сопоставить Title code / Title/Sale Doc с прайсом Excel (лист Title)."""
    raw = str(document_text or "").strip()
    if not raw:
        return None
    text = _norm(raw)

    # Точное совпадение с названием строки прайса (ручной выбор)
    for row in _load().get("rows") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if name and _norm(name) == text:
            try:
                cost_f = float(row.get("cost_usd") or 0)
            except (TypeError, ValueError):
                cost_f = 0.0
            return {
                "document_raw": raw,
                "matched_rule": name,
                "matched_id": None,
                "cost_usd": cost_f,
                "free": cost_f <= 0,
                "unmatched": False,
                "tariff_source": "usa_title_tariffs",
            }

    for rule in _load().get("rules") or []:
        if not isinstance(rule, dict):
            continue
        name = str(rule.get("name") or "").strip()
        if name and _norm(name) == text:
            try:
                cost_f = float(rule.get("cost_usd") or 0)
            except (TypeError, ValueError):
                cost_f = 0.0
            return {
                "document_raw": raw,
                "matched_rule": name,
                "matched_id": rule.get("id"),
                "cost_usd": cost_f,
                "free": cost_f <= 0,
                "unmatched": False,
                "tariff_source": "usa_title_tariffs",
            }
        all_need = [str(x) for x in (rule.get("all") or []) if x]
        any_need = [str(x) for x in (rule.get("any") or []) if x]
        if all_need and not all(_has_token(text, tok) for tok in all_need):
            continue
        if any_need and not any(_has_token(text, tok) for tok in any_need):
            continue
        if not all_need and not any_need:
            continue
        cost = rule.get("cost_usd")
        try:
            cost_f = float(cost) if cost is not None else 0.0
        except (TypeError, ValueError):
            cost_f = 0.0
        return {
            "document_raw": raw,
            "matched_rule": rule.get("name") or rule.get("id"),
            "matched_id": rule.get("id"),
            "cost_usd": cost_f,
            "free": cost_f <= 0,
            "unmatched": False,
            "tariff_source": "usa_title_tariffs",
        }
    return {
        "document_raw": raw,
        "matched_rule": None,
        "matched_id": None,
        "cost_usd": None,
        "free": False,
        "unmatched": True,
        "tariff_source": "usa_title_tariffs",
    }
