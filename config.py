from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "seen_lots.db"
SEARCHES_PATH = ROOT / "searches.txt"


def _bool(value: str | None, default: bool = True) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None) -> int | None:
    if value is None or value.strip() == "":
        return None
    return int(value)


def _csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


@dataclass(frozen=True)
class Search:
    name: str
    url: str


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    telegram_chat_id: str
    searches: tuple[Search, ...]
    poll_interval_minutes: int
    max_pages: int
    headless: bool
    make_filter: tuple[str, ...]
    year_from: int | None
    year_to: int | None
    max_bid: float | None
    crm_port: int
    crm_host: str


def parse_searches_file(path: Path) -> list[Search]:
    if not path.exists():
        return []
    searches: list[Search] = []
    pending_name: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("http://") or line.startswith("https://"):
            name = pending_name or f"Поиск {len(searches) + 1}"
            searches.append(Search(name=name, url=line))
            pending_name = None
        else:
            pending_name = line
    return searches


def write_searches_file(searches: list[Search], path: Path = SEARCHES_PATH) -> None:
    lines = [
        "# Название поиска, со следующей строки — URL с Copart.",
        "",
    ]
    for item in searches:
        lines.append(item.name)
        lines.append(item.url)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _env_searches(value: str | None) -> list[Search]:
    if not value or not value.strip():
        return []
    parts = [part.strip() for part in re.split(r"[\n|;]+", value) if part.strip()]
    return [
        Search(name=f"COPART_URL {i}", url=url)
        for i, url in enumerate(parts, start=1)
        if url.startswith("http")
    ]


def write_env_value(key: str, value: str, path: Path = ROOT / ".env") -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    updated = False
    out: list[str] = []
    for line in lines:
        if line.startswith(f"{key}="):
            out.append(f"{key}={value}")
            updated = True
        else:
            out.append(line)
    if not updated:
        if out and out[-1].strip():
            out.append("")
        out.append(f"{key}={value}")
    os.environ[key] = value
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def load_dotenv_once() -> None:
    load_dotenv(ROOT / ".env", override=True)


def collect_file_searches() -> list[Search]:
    load_dotenv_once()
    searches = parse_searches_file(SEARCHES_PATH)
    seen = {item.url for item in searches}
    for extra in _env_searches(os.getenv("COPART_URL")):
        if extra.url not in seen:
            searches.append(extra)
    return searches


def load_settings(*, require_telegram: bool = True, require_searches: bool = True) -> Settings:
    load_dotenv_once()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if require_telegram and (not token or not chat_id):
        raise SystemExit(
            "Заполните TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID в файле .env"
        )

    searches = collect_file_searches()
    if require_searches and not searches:
        raise SystemExit(
            "Нет поисков. Вставьте URL из Copart в searches.txt или добавьте его в CRM."
        )

    max_pages = _int(os.getenv("MAX_PAGES"))
    if max_pages is None:
        max_pages = 0

    return Settings(
        telegram_token=token,
        telegram_chat_id=chat_id,
        searches=tuple(searches),
        poll_interval_minutes=max(1, _int(os.getenv("POLL_INTERVAL_MINUTES")) or 10),
        max_pages=max(0, max_pages),
        headless=_bool(os.getenv("HEADLESS"), True),
        make_filter=tuple(m.upper() for m in _csv(os.getenv("MAKE_FILTER"))),
        year_from=_int(os.getenv("YEAR_FROM")),
        year_to=_int(os.getenv("YEAR_TO")),
        max_bid=float(os.getenv("MAX_BID")) if os.getenv("MAX_BID", "").strip() else None,
        crm_port=max(1, _int(os.getenv("CRM_PORT")) or 8080),
        crm_host=(os.getenv("CRM_HOST") or "0.0.0.0").strip() or "0.0.0.0",
    )
