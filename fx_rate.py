from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from urllib.request import urlopen

log = logging.getLogger("copart")

DEFAULT_FX_RATE = 1.27
FX_KEY = "fx_rate_gbp_usd"
FX_UPDATED_KEY = "fx_rate_updated_at"
FX_SOURCE_KEY = "fx_rate_source"
STALE_HOURS = 24


def fetch_gbp_usd_rate() -> float | None:
    try:
        with urlopen("https://api.frankfurter.app/latest?from=GBP&to=USD", timeout=8) as resp:
            data = json.loads(resp.read().decode())
            rate = float(data["rates"]["USD"])
            if rate > 0:
                return rate
    except Exception as exc:
        log.warning("Не удалось получить курс GBP→USD автоматически: %s", exc)
    return None


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def ensure_fx_rate(store) -> float:
    rate = store.get_fx_rate()
    updated = _parse_ts(store.get_meta(FX_UPDATED_KEY))
    stale = updated is None or (datetime.now(timezone.utc) - updated).total_seconds() > STALE_HOURS * 3600
    if rate and not stale:
        return rate
    fresh = fetch_gbp_usd_rate()
    if fresh:
        store.set_fx_rate(fresh, source="auto")
        log.info("Курс GBP→USD обновлён автоматически: %s", fresh)
        return fresh
    if rate:
        return rate
    store.set_fx_rate(DEFAULT_FX_RATE, source="default")
    log.info("Курс GBP→USD: значение по умолчанию %s", DEFAULT_FX_RATE)
    return DEFAULT_FX_RATE
