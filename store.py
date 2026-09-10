from __future__ import annotations

import json
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import DATA_DIR, DB_PATH, Search
from calculator import quote_lot
from search_url import parse_bidcars_search, parse_copart_search
from scraper import _is_lot_image


def _is_history_photo(url: str | None) -> bool:
    src = str(url or "").strip()
    if not src:
        return False
    if src.startswith("/api/media/"):
        return True
    if _is_lot_image(src):
        return True
    low = src.lower()
    if not src.startswith("https://"):
        return False
    if any(
        x in low
        for x in (
            "flag",
            "/flags/",
            "logo",
            "icon",
            "sprite",
            "onetrust",
            "placeholder",
            "/content/",
            "clo-platinum",
            "favicon",
            "avatar",
        )
    ):
        return False
    return any(
        x in low
        for x in (
            "bid.cars",
            "cloudfront",
            "amazonaws",
            "iaai",
            "_ful.",
            "_thb.",
            ".jpg",
            ".jpeg",
            ".webp",
            ".png",
        )
    )


def _pick_history_image(entry: dict, fallback: str | None = None) -> str | None:
    for raw in entry.get("images") or []:
        if _is_history_photo(str(raw)):
            return str(raw)
    raw = entry.get("image")
    if raw and _is_history_photo(str(raw)):
        return str(raw)
    if fallback and _is_history_photo(str(fallback)):
        return str(fallback)
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _later(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


class LotStore:
    def __init__(self, path: Path = DB_PATH) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS seen_lots (
                lot_id TEXT PRIMARY KEY,
                title TEXT,
                url TEXT,
                first_seen TEXT NOT NULL,
                sale_date TEXT,
                vin TEXT
            );
            CREATE TABLE IF NOT EXISTS lots (
                lot_id TEXT PRIMARY KEY,
                title TEXT,
                year INTEGER,
                make TEXT,
                model TEXT,
                bid REAL,
                location TEXT,
                category TEXT,
                odometer REAL,
                sale_date TEXT,
                vin TEXT,
                url TEXT,
                search_names TEXT,
                status TEXT NOT NULL DEFAULT 'new',
                notes TEXT NOT NULL DEFAULT '',
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                in_stock INTEGER NOT NULL DEFAULT 1,
                event TEXT,
                previous_sale_date TEXT,
                body_style TEXT,
                vat_on_sale INTEGER
            );
            CREATE TABLE IF NOT EXISTS searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                seeded_at TEXT
            );
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sync_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                lots_found INTEGER,
                new_count INTEGER,
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS calc_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lot_id TEXT NOT NULL,
                title TEXT,
                url TEXT,
                image TEXT,
                bid REAL,
                total_uk REAL,
                grand_usd REAL,
                category TEXT,
                location TEXT,
                payload TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL UNIQUE,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                role TEXT NOT NULL DEFAULT 'user',
                notify INTEGER NOT NULL DEFAULT 1,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_seen TEXT
            );
            CREATE TABLE IF NOT EXISTS login_tokens (
                token TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used_at TEXT,
                user_id INTEGER,
                session_token TEXT
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            """
        )
        for col, typedef in (
            ("sale_date", "TEXT"),
            ("vin", "TEXT"),
        ):
            self._ensure_column("seen_lots", col, typedef)
        self._ensure_column("lots", "body_style", "TEXT")
        self._ensure_column("lots", "vat_on_sale", "INTEGER")
        self._ensure_column("searches", "seeded_at", "TEXT")
        self._ensure_column("searches", "comment", "TEXT")
        self._ensure_column("searches", "client_telegram", "TEXT")
        self._ensure_column("searches", "client_phone", "TEXT")
        self._ensure_column("searches", "owner_user_id", "INTEGER")
        self._ensure_column("searches", "last_in_search", "INTEGER")
        self._ensure_column("searches", "last_new", "INTEGER")
        self._ensure_column("searches", "last_checked_at", "TEXT")
        self._ensure_column("calc_history", "auction", "TEXT")
        self._ensure_column("searches", "platform", "TEXT")
        self._ensure_column("searches", "kind", "TEXT")
        self._ensure_column("lots", "source", "TEXT")
        self._conn.execute(
            "UPDATE searches SET platform = 'bidcars' WHERE LOWER(url) LIKE '%bid.cars%' AND (platform IS NULL OR platform = '' OR platform = 'copart')"
        )
        self._conn.execute(
            "UPDATE searches SET platform = 'copart' WHERE platform IS NULL OR platform = ''"
        )
        self._conn.execute(
            "UPDATE searches SET kind = 'client' WHERE kind IS NULL OR kind = ''"
        )
        self._conn.execute(
            "UPDATE lots SET source = 'bidcars' WHERE LOWER(COALESCE(url, '')) LIKE '%bid.cars%' AND (source IS NULL OR source = '' OR source = 'copart')"
        )
        self._conn.execute(
            "UPDATE lots SET source = 'copart' WHERE source IS NULL OR source = ''"
        )
        self._migrate_seen_lots()
        self._migrate_search_seeds()
        self._demote_baseline_new()
        self._conn.commit()

    def _migrate_search_seeds(self) -> None:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'seeded'"
        ).fetchone()
        if row:
            self._conn.execute(
                "UPDATE searches SET seeded_at = COALESCE(seeded_at, ?) WHERE seeded_at IS NULL",
                (row[0],),
            )

    def _demote_baseline_new(self) -> None:
        """После первого прогона все текущие «new» — это база мониторинга, не лента."""
        done = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'feed_baseline_cleared'"
        ).fetchone()
        if done:
            return
        seeded = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'seeded'"
        ).fetchone()
        if not seeded:
            return
        self._conn.execute("UPDATE lots SET status = 'watching' WHERE status = 'new'")
        self._conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('feed_baseline_cleared', ?)",
            (_now(),),
        )

    def _ensure_column(self, table: str, name: str, typedef: str) -> None:
        cols = {row[1] for row in self._conn.execute(f"PRAGMA table_info({table})")}
        if name not in cols:
            self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typedef}")

    def _migrate_seen_lots(self) -> None:
        rows = self._conn.execute("SELECT * FROM seen_lots").fetchall()
        for row in rows:
            exists = self._conn.execute(
                "SELECT 1 FROM lots WHERE lot_id = ?", (row["lot_id"],)
            ).fetchone()
            if exists:
                continue
            now = row["first_seen"]
            self._conn.execute(
                """
                INSERT INTO lots(
                    lot_id, title, url, sale_date, vin, status, notes,
                    first_seen, last_seen, in_stock, search_names
                ) VALUES (?, ?, ?, ?, ?, 'watching', '', ?, ?, 1, '[]')
                """,
                (
                    row["lot_id"],
                    row["title"],
                    row["url"],
                    row["sale_date"],
                    row["vin"],
                    now,
                    now,
                ),
            )

    _SEARCH_SELECT = """
        SELECT s.*,
               u.username AS owner_username,
               u.first_name AS owner_first_name,
               u.last_name AS owner_last_name,
               u.telegram_id AS owner_telegram_id
        FROM searches s
        LEFT JOIN users u ON u.id = s.owner_user_id
    """

    def list_searches(
        self,
        *,
        with_counts: bool = True,
        platform: str | None = None,
        kind: str | None = None,
    ) -> list[dict]:
        sql = self._SEARCH_SELECT
        params: list = []
        clauses: list[str] = []
        if platform:
            clauses.append("COALESCE(s.platform, 'copart') = ?")
            params.append(platform)
        if kind:
            clauses.append("COALESCE(s.kind, 'client') = ?")
            params.append(kind)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY s.id"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        items = [self._search_row(row) for row in rows]
        if with_counts:
            self._attach_search_counts(items)
        return items

    def get_search(self, search_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                self._SEARCH_SELECT + " WHERE s.id = ?",
                (search_id,),
            ).fetchone()
        if not row:
            return None
        item = self._search_row(row)
        self._attach_search_counts([item])
        return item

    def _search_row(self, row: sqlite3.Row | dict) -> dict:
        data = dict(row)
        platform = str(data.get("platform") or "").strip().lower()
        url = data.get("url") or ""
        if platform not in {"copart", "bidcars"}:
            platform = "bidcars" if "bid.cars" in url.lower() else "copart"
        data["platform"] = platform
        kind = str(data.get("kind") or "").strip().lower()
        data["kind"] = kind if kind in {"client", "restoration"} else "client"
        parsed = parse_bidcars_search(url) if platform == "bidcars" else parse_copart_search(url)
        data["params"] = parsed["params"]
        data["summary"] = parsed["summary"]
        data["comment"] = (data.get("comment") or "").strip()
        data["client_telegram"] = (data.get("client_telegram") or "").strip()
        data["client_phone"] = (data.get("client_phone") or "").strip()
        first = (data.pop("owner_first_name", None) or "").strip()
        last = (data.pop("owner_last_name", None) or "").strip()
        username = (data.pop("owner_username", None) or "").strip()
        data.pop("owner_telegram_id", None)
        data["owner_name"] = " ".join(part for part in (first, last) if part) or (
            f"@{username}" if username else ""
        )
        checked = bool(data.get("last_checked_at"))
        data["in_search"] = int(data.get("last_in_search") or 0) if checked else 0
        data["new_count"] = int(data.get("last_new") or 0) if checked else 0
        return data

    @staticmethod
    def _name_set(raw) -> set[str]:
        if raw is None or raw == "":
            return set()
        if isinstance(raw, (list, tuple, set)):
            return {str(name) for name in raw if name}
        try:
            names = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {str(raw)} if raw else set()
        if isinstance(names, list):
            return {str(name) for name in names if name}
        return {str(names)} if names else set()

    @staticmethod
    def _search_keys(item: dict) -> set[str]:
        keys = {str(item.get("name") or "")}
        summary = str(item.get("summary") or "")
        if summary:
            keys.add(summary)
        keys.discard("")
        return keys

    def _attach_search_counts(self, items: list[dict]) -> None:
        for item in items:
            checked = bool(item.get("last_checked_at"))
            item["in_search"] = int(item.get("last_in_search") or 0) if checked else 0
            item["new_count"] = int(item.get("last_new") or 0) if checked else 0

    def set_search_scan_stats(self, search_id: int, *, in_search: int, new_count: int) -> None:
        with self._lock:
            self._conn.execute(
                """
                UPDATE searches
                SET last_in_search = ?, last_new = ?, last_checked_at = ?
                WHERE id = ?
                """,
                (int(in_search), int(new_count), _now(), search_id),
            )
            self._conn.commit()

    def mark_missing_for_keys(
        self, seen_ids: list[str], search_keys: set[str], *, source: str | None = None
    ) -> None:
        if not search_keys:
            return
        seen = {str(lot_id) for lot_id in seen_ids}
        want_source = (source or "").strip().lower() or None
        with self._lock:
            rows = self._conn.execute(
                "SELECT lot_id, search_names, source FROM lots WHERE in_stock = 1"
            ).fetchall()
            gone = []
            for row in rows:
                row_source = str(row["source"] or "copart").strip().lower() or "copart"
                if want_source and row_source != want_source:
                    continue
                if self._name_set(row["search_names"]) & search_keys and row["lot_id"] not in seen:
                    gone.append(row["lot_id"])
            for lot_id in gone:
                self._conn.execute(
                    "UPDATE lots SET in_stock = 0 WHERE lot_id = ?", (lot_id,)
                )
            self._conn.commit()

    def searches_by_manager(
        self, *, platform: str | None = None, kind: str | None = None
    ) -> list[tuple[str, list[dict]]]:
        rows = [
            item
            for item in self.list_searches(with_counts=False, platform=platform, kind=kind)
            if item.get("enabled")
        ]
        groups: dict[object, list[dict]] = {}
        order: list[object] = []
        for row in rows:
            key = row.get("owner_user_id") if row.get("owner_user_id") is not None else 0
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(row)
        result: list[tuple[str, list[dict]]] = []
        for key in order:
            items = groups[key]
            label = (items[0].get("owner_name") or "").strip() or "без менеджера"
            result.append((label, items))
        return result

    def enabled_searches(self, *, platform: str | None = None, kind: str | None = None) -> list[Search]:
        return [
            Search(name=item["name"], url=item["url"])
            for item in self.list_searches(with_counts=False, platform=platform, kind=kind)
            if item["enabled"]
        ]

    def search_keys(self, *, platform: str | None = None, kind: str | None = None) -> set[str]:
        keys: set[str] = set()
        for item in self.list_searches(with_counts=False, platform=platform, kind=kind):
            keys |= self._search_keys(item)
        return keys

    def import_searches(self, searches: list[Search]) -> None:
        with self._lock:
            for item in searches:
                self._conn.execute(
                    """
                    INSERT INTO searches(name, url, enabled, created_at, platform)
                    VALUES (?, ?, 1, ?, 'copart')
                    ON CONFLICT(url) DO UPDATE SET name = excluded.name
                    """,
                    (item.name, item.url, _now()),
                )
            self._conn.commit()

    def add_search(
        self,
        name: str,
        url: str,
        *,
        comment: str = "",
        client_telegram: str = "",
        client_phone: str = "",
        owner_user_id: int | None = None,
        platform: str = "copart",
        kind: str = "client",
    ) -> dict:
        plat = "bidcars" if str(platform).strip().lower() == "bidcars" else "copart"
        search_kind = "restoration" if str(kind).strip().lower() == "restoration" else "client"
        parsed = parse_bidcars_search(url) if plat == "bidcars" else parse_copart_search(url)
        if name.strip():
            label = name.strip()
        elif search_kind == "restoration":
            label = parsed["summary"] or ("Восстановление Bid.cars" if plat == "bidcars" else "Восстановление")
        else:
            label = parsed["summary"] or ("Поиск Bid.cars" if plat == "bidcars" else "Поиск")
        note = (comment or "").strip()
        telegram = (client_telegram or "").strip()
        phone = (client_phone or "").strip()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO searches(name, url, enabled, created_at, comment, client_telegram, client_phone, owner_user_id, platform, kind)
                VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    name = excluded.name,
                    enabled = 1,
                    comment = excluded.comment,
                    client_telegram = excluded.client_telegram,
                    client_phone = excluded.client_phone,
                    owner_user_id = COALESCE(searches.owner_user_id, excluded.owner_user_id),
                    platform = excluded.platform,
                    kind = excluded.kind
                """,
                (label, url.strip(), _now(), note, telegram, phone, owner_user_id, plat, search_kind),
            )
            self._conn.commit()
            row = self._conn.execute(
                self._SEARCH_SELECT + " WHERE s.url = ?",
                (url.strip(),),
            ).fetchone()
        return self._search_row(row) if row else {}

    def update_search(
        self,
        search_id: int,
        *,
        comment: str | None = None,
        client_telegram: str | None = None,
        client_phone: str | None = None,
        name: str | None = None,
    ) -> dict | None:
        if not self.get_search(search_id):
            return None
        with self._lock:
            if name is not None:
                label = name.strip()
                if label:
                    self._conn.execute("UPDATE searches SET name = ? WHERE id = ?", (label, search_id))
            if comment is not None:
                self._conn.execute(
                    "UPDATE searches SET comment = ? WHERE id = ?",
                    (comment.strip(), search_id),
                )
            if client_telegram is not None:
                self._conn.execute(
                    "UPDATE searches SET client_telegram = ? WHERE id = ?",
                    (client_telegram.strip(), search_id),
                )
            if client_phone is not None:
                self._conn.execute(
                    "UPDATE searches SET client_phone = ? WHERE id = ?",
                    (client_phone.strip(), search_id),
                )
            self._conn.commit()
        return self.get_search(search_id)

    def get_user_by_username(self, username: str) -> dict | None:
        name = (username or "").strip().lstrip("@").lower()
        if not name:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE enabled = 1 AND lower(COALESCE(username, '')) = ?",
                (name,),
            ).fetchone()
        return self._user_row(row) if row else None

    def resolve_telegram_target(self, raw: str) -> str | None:
        text = (raw or "").strip()
        if not text:
            return None
        match = re.search(r"(?:t\.me/|telegram\.me/)([A-Za-z0-9_]+)", text, re.I)
        if match:
            text = match.group(1)
        if text.startswith("@"):
            text = text[1:]
        if re.fullmatch(r"-?\d{5,}", text):
            return text
        user = self.get_user_by_username(text)
        if user:
            return str(user["telegram_id"])
        return None

    def search_contacts_for_lot(self, lot: dict) -> list[dict]:
        names = {str(name) for name in (lot.get("search_names") or []) if name}
        if not names:
            return []
        contacts = []
        for item in self.list_searches(with_counts=False):
            if item["name"] not in names and item.get("summary") not in names:
                continue
            contacts.append(
                {
                    "search": item["name"],
                    "comment": item.get("comment") or "",
                    "telegram": item.get("client_telegram") or "",
                    "phone": item.get("client_phone") or "",
                    "owner_name": item.get("owner_name") or "",
                    "params": list(item.get("params") or []),
                }
            )
        return contacts

    def search_notify_chats_for_lot(self, lot: dict) -> list[str]:
        """Менеджер поиска + все, у кого включены уведомления. Клиенту не пишем."""
        chats: list[str] = []
        names = {str(name) for name in (lot.get("search_names") or []) if name}
        for item in self.list_searches(with_counts=False):
            if item["name"] not in names and item.get("summary") not in names:
                continue
            owner_id = item.get("owner_user_id")
            if not owner_id:
                continue
            user = self.get_user(int(owner_id))
            if not user or not user.get("enabled"):
                continue
            chat = str(user.get("telegram_id") or "").strip()
            if chat and chat not in chats:
                chats.append(chat)
        for chat in self.notify_chat_ids():
            if chat and chat not in chats:
                chats.append(chat)
        return chats

    def mark_search_seeded(self, search_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE searches SET seeded_at = ? WHERE id = ?",
                (_now(), search_id),
            )
            self._conn.commit()

    def mark_all_searches_seeded(self, platform: str | None = None, kind: str | None = None) -> None:
        with self._lock:
            clauses = ["seeded_at IS NULL"]
            params: list = [_now()]
            if platform:
                clauses.append("COALESCE(platform, 'copart') = ?")
                params.append(platform)
            if kind:
                clauses.append("COALESCE(kind, 'client') = ?")
                params.append(kind)
            self._conn.execute(
                f"UPDATE searches SET seeded_at = ? WHERE {' AND '.join(clauses)}",
                params,
            )
            self._conn.commit()

    def delete_search(self, search_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM searches WHERE id = ?", (search_id,))
            self._conn.commit()

    def set_search_enabled(self, search_id: int, enabled: bool) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE searches SET enabled = ? WHERE id = ?",
                (1 if enabled else 0, search_id),
            )
            self._conn.commit()

    def is_first_run(self) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key = 'seeded'"
            ).fetchone()
        return row is None

    def mark_seeded(self) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('seeded', ?)",
                (_now(),),
            )
            self._conn.commit()

    def get_meta(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
                (key, value),
            )
            self._conn.commit()

    def get_fx_rate(self) -> float | None:
        raw = self.get_meta("fx_rate_gbp_usd")
        if not raw:
            return None
        try:
            rate = float(raw)
            return rate if rate > 0 else None
        except ValueError:
            return None

    def set_fx_rate(self, rate: float, *, source: str = "manual") -> float:
        text = f"{float(rate):.6f}".rstrip("0").rstrip(".")
        self.set_meta("fx_rate_gbp_usd", text)
        self.set_meta("fx_rate_updated_at", _now())
        self.set_meta("fx_rate_source", source)
        return float(text)

    def get_byn_rates(self) -> dict:
        """Курсы EUR/BYN и USD/BYN для растаможки РБ."""
        def _f(key: str) -> float | None:
            raw = self.get_meta(key)
            if not raw:
                return None
            try:
                val = float(raw)
                return val if val > 0 else None
            except ValueError:
                return None

        return {
            "eur_byn": _f("eur_byn"),
            "usd_byn": _f("usd_byn"),
            "source": self.get_meta("byn_rates_source") or "default",
        }

    def set_byn_rates(
        self,
        *,
        eur_byn: float | None = None,
        usd_byn: float | None = None,
        source: str = "manual",
    ) -> dict:
        if eur_byn is not None and float(eur_byn) > 0:
            text = f"{float(eur_byn):.6f}".rstrip("0").rstrip(".")
            self.set_meta("eur_byn", text)
        if usd_byn is not None and float(usd_byn) > 0:
            text = f"{float(usd_byn):.6f}".rstrip("0").rstrip(".")
            self.set_meta("usd_byn", text)
        self.set_meta("byn_rates_source", source)
        self.set_meta("byn_rates_updated_at", _now())
        return self.get_byn_rates()

    def get(self, lot_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM lots WHERE lot_id = ?", (lot_id,)
            ).fetchone()
            if row:
                fx_rate = self.get_fx_rate()
                lot = self._lot_row(row, fx_rate)
                return self._attach_search_params([lot])[0]
            row = self._conn.execute(
                "SELECT lot_id, title, url, sale_date, vin FROM seen_lots WHERE lot_id = ?",
                (lot_id,),
            ).fetchone()
        return dict(row) if row else None

    def vin_known(self, vin: str, exclude_lot: str) -> bool:
        if not vin or len(vin) < 11:
            return False
        with self._lock:
            row = self._conn.execute(
                """
                SELECT lot_id FROM lots
                WHERE vin = ? AND lot_id != ?
                LIMIT 1
                """,
                (vin, exclude_lot),
            ).fetchone()
        return row is not None

    def upsert_many(self, lots: list[dict]) -> None:
        self.apply_scan(lots, mark_missing=False)

    def apply_scan(self, lots: list[dict], *, mark_missing: bool = True, seed: bool = False) -> dict:
        now = _now()
        new_count = 0
        relist_count = 0
        seeded_count = 0
        with self._lock:
            seen_ids = [lot["lot_id"] for lot in lots]
            for lot in lots:
                prev = self._conn.execute(
                    "SELECT * FROM lots WHERE lot_id = ?", (lot["lot_id"],)
                ).fetchone()
                if seed:
                    lot.pop("event", None)
                event = lot.get("event")
                incoming = lot.get("search_names") or []
                if not isinstance(incoming, list):
                    incoming = [incoming] if incoming else []
                names = list(incoming)
                if prev is not None:
                    for name in self._name_set(prev["search_names"]):
                        if name not in names:
                            names.append(name)
                search_names = json.dumps(names, ensure_ascii=False)
                if prev is None:
                    if seed or event == "relist":
                        if seed:
                            seeded_count += 1
                        elif event == "relist":
                            relist_count += 1
                        status = "watching"
                        notes = ""
                        first_seen = now
                    else:
                        new_count += 1
                        status = "new"
                        notes = ""
                        first_seen = now
                else:
                    status = prev["status"]
                    notes = prev["notes"]
                    first_seen = prev["first_seen"]
                    if event == "relist":
                        relist_count += 1
                        # Уже известный лот / повторный аукцион — не показываем в ленте «новых»
                self._conn.execute(
                    """
                    INSERT INTO lots(
                        lot_id, title, year, make, model, bid, location, category,
                        odometer, sale_date, vin, url, search_names, status, notes,
                        first_seen, last_seen, in_stock, event, previous_sale_date,
                        body_style, vat_on_sale, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
                    ON CONFLICT(lot_id) DO UPDATE SET
                        title = excluded.title,
                        year = COALESCE(excluded.year, lots.year),
                        make = COALESCE(excluded.make, lots.make),
                        model = COALESCE(excluded.model, lots.model),
                        bid = excluded.bid,
                        location = COALESCE(excluded.location, lots.location),
                        category = COALESCE(excluded.category, lots.category),
                        odometer = COALESCE(excluded.odometer, lots.odometer),
                        sale_date = COALESCE(excluded.sale_date, lots.sale_date),
                        vin = COALESCE(excluded.vin, lots.vin),
                        url = excluded.url,
                        search_names = excluded.search_names,
                        status = excluded.status,
                        last_seen = excluded.last_seen,
                        in_stock = 1,
                        event = excluded.event,
                        previous_sale_date = excluded.previous_sale_date,
                        body_style = COALESCE(excluded.body_style, lots.body_style),
                        vat_on_sale = COALESCE(excluded.vat_on_sale, lots.vat_on_sale),
                        source = COALESCE(excluded.source, lots.source)
                    """,
                    (
                        lot["lot_id"],
                        lot.get("title") or "",
                        lot.get("year"),
                        lot.get("make"),
                        lot.get("model"),
                        lot.get("bid"),
                        lot.get("location"),
                        lot.get("category"),
                        lot.get("odometer"),
                        lot.get("sale_date"),
                        lot.get("vin"),
                        lot.get("url") or "",
                        search_names,
                        status,
                        notes,
                        first_seen,
                        now,
                        event,
                        lot.get("previous_sale_date"),
                        lot.get("body_style"),
                        None if lot.get("vat_on_sale") is None else (1 if lot.get("vat_on_sale") else 0),
                        lot.get("source") or "copart",
                    ),
                )
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO seen_lots(lot_id, title, url, first_seen, sale_date, vin)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        lot["lot_id"],
                        lot.get("title") or "",
                        lot.get("url") or "",
                        first_seen,
                        lot.get("sale_date"),
                        lot.get("vin"),
                    ),
                )
                self._conn.execute(
                    """
                    UPDATE seen_lots SET title = ?, url = ?, sale_date = ?, vin = ?
                    WHERE lot_id = ?
                    """,
                    (
                        lot.get("title") or "",
                        lot.get("url") or "",
                        lot.get("sale_date"),
                        lot.get("vin"),
                        lot["lot_id"],
                    ),
                )
            if mark_missing:
                if seen_ids:
                    placeholders = ",".join("?" * len(seen_ids))
                    self._conn.execute(
                        f"UPDATE lots SET in_stock = 0 WHERE lot_id NOT IN ({placeholders})",
                        seen_ids,
                    )
                else:
                    self._conn.execute("UPDATE lots SET in_stock = 0")
            self._conn.commit()
        return {"found": len(lots), "new": new_count, "relist": relist_count, "seeded": seeded_count}

    def list_lots(
        self,
        *,
        status: str | None = None,
        search: str | None = None,
        q: str | None = None,
        in_stock: bool | None = True,
        feed: bool = False,
        source: str | None = None,
        kind: str | None = None,
    ) -> list[dict]:
        sql = "SELECT * FROM lots WHERE 1=1"
        params: list = []
        if feed:
            sql += " AND status = 'new'"
        elif status:
            sql += " AND status = ?"
            params.append(status)
        if in_stock is True:
            sql += " AND in_stock = 1"
        elif in_stock is False:
            sql += " AND in_stock = 0"
        if source:
            sql += " AND COALESCE(source, 'copart') = ?"
            params.append(source)
        if search:
            sql += " AND search_names LIKE ?"
            params.append(f"%{search}%")
        if q:
            sql += " AND (title LIKE ? OR lot_id LIKE ? OR location LIKE ?)"
            like = f"%{q}%"
            params.extend([like, like, like])
        sql += """
            ORDER BY
                CASE status
                    WHEN 'new' THEN 0
                    WHEN 'watching' THEN 1
                    WHEN 'bid' THEN 2
                    ELSE 3
                END,
                last_seen DESC
        """
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        fx_rate = self.get_fx_rate()
        lots = [self._lot_row(row, fx_rate) for row in rows]
        lots = self._attach_search_params(lots)
        if kind:
            # Для client фильтруем по платформе source; для restoration — все площадки
            keys = self.search_keys(
                platform=source if kind == "client" else None,
                kind=kind,
            )
            if not keys:
                return []
            lots = [
                lot
                for lot in lots
                if self._name_set(lot.get("search_names")) & keys
            ]
        return lots

    def update_lot(self, lot_id: str, *, status: str | None = None, notes: str | None = None) -> dict | None:
        with self._lock:
            if status is not None:
                self._conn.execute(
                    "UPDATE lots SET status = ? WHERE lot_id = ?", (status, lot_id)
                )
            if notes is not None:
                self._conn.execute(
                    "UPDATE lots SET notes = ? WHERE lot_id = ?", (notes, lot_id)
                )
            self._conn.commit()
        return self.get(lot_id)

    def stats(self, *, platform: str | None = None, kind: str | None = None) -> dict:
        search_kind = kind or "client"
        searches = [
            item
            for item in self.list_searches(with_counts=False, platform=platform, kind=search_kind)
            if item.get("enabled")
        ]
        in_search = sum(int(item.get("last_in_search") or 0) for item in searches)
        new_from_search = sum(int(item.get("last_new") or 0) for item in searches)
        keys = self.search_keys(platform=platform, kind=search_kind)
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, in_stock, search_names, source FROM lots"
            ).fetchall()

        watching = bid = gone = all_count = 0
        for row in rows:
            if keys and not (self._name_set(row["search_names"]) & keys):
                continue
            if platform:
                row_source = str(row["source"] or "copart").strip().lower() or "copart"
                if row_source != platform:
                    continue
            all_count += 1
            if not row["in_stock"]:
                gone += 1
                continue
            status = row["status"]
            if status == "watching":
                watching += 1
            elif status == "bid":
                bid += 1

        return {
            "in_stock": in_search,
            "in_search": in_search,
            "new": new_from_search,
            "watching": watching,
            "bid": bid,
            "gone": gone,
            "all": all_count,
        }

    def start_sync(self) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO sync_runs(started_at) VALUES (?)", (_now(),)
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('sync_running', '1')"
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def finish_sync(
        self, run_id: int, *, lots_found: int = 0, new_count: int = 0, error: str | None = None
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                UPDATE sync_runs
                SET finished_at = ?, lots_found = ?, new_count = ?, error = ?
                WHERE id = ?
                """,
                (_now(), lots_found, new_count, error, run_id),
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('sync_running', '0')"
            )
            self._conn.commit()

    def sync_status(self) -> dict:
        with self._lock:
            running = self._conn.execute(
                "SELECT value FROM meta WHERE key = 'sync_running'"
            ).fetchone()
            last = self._conn.execute(
                """
                SELECT started_at, finished_at, lots_found, new_count, error
                FROM sync_runs ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
        return {
            "running": bool(running and running[0] == "1"),
            "last": dict(last) if last else None,
        }

    def list_users(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM users
                ORDER BY CASE role WHEN 'admin' THEN 0 ELSE 1 END, created_at
                """
            ).fetchall()
        return [self._user_row(row) for row in rows]

    def get_user(self, user_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return self._user_row(row) if row else None

    def get_user_by_telegram(self, telegram_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
        return self._user_row(row) if row else None

    def user_count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def enabled_admin_count(self, exclude_id: int | None = None) -> int:
        sql = "SELECT COUNT(*) FROM users WHERE role = 'admin' AND enabled = 1"
        params: list = []
        if exclude_id is not None:
            sql += " AND id != ?"
            params.append(exclude_id)
        with self._lock:
            return int(self._conn.execute(sql, params).fetchone()[0])

    def upsert_telegram_user(
        self,
        *,
        telegram_id: int,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> dict:
        now = _now()
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
            if row:
                self._conn.execute(
                    """
                    UPDATE users
                    SET username = ?, first_name = ?, last_name = ?, last_seen = ?
                    WHERE id = ?
                    """,
                    (username or None, first_name or None, last_name or None, now, row["id"]),
                )
                self._conn.commit()
                return self._user_row(
                    self._conn.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
                )
            role = "admin" if self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0 else "user"
            cur = self._conn.execute(
                """
                INSERT INTO users(
                    telegram_id, username, first_name, last_name, role,
                    notify, enabled, created_at, last_seen
                ) VALUES (?, ?, ?, ?, ?, 1, 1, ?, ?)
                """,
                (telegram_id, username or None, first_name or None, last_name or None, role, now, now),
            )
            self._conn.commit()
            return self._user_row(
                self._conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
            )

    def set_user_notify(self, user_id: int, notify: bool) -> dict | None:
        with self._lock:
            self._conn.execute(
                "UPDATE users SET notify = ? WHERE id = ?",
                (1 if notify else 0, user_id),
            )
            self._conn.commit()
        return self.get_user(user_id)

    def set_user_enabled(self, user_id: int, enabled: bool) -> dict | None:
        user = self.get_user(user_id)
        if not user:
            return None
        if not enabled and user["role"] == "admin" and self.enabled_admin_count(exclude_id=user_id) < 1:
            raise ValueError("Нельзя отключить последнего администратора")
        with self._lock:
            self._conn.execute(
                "UPDATE users SET enabled = ? WHERE id = ?",
                (1 if enabled else 0, user_id),
            )
            if not enabled:
                self._conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            self._conn.commit()
        return self.get_user(user_id)

    def set_user_role(self, user_id: int, role: str) -> dict | None:
        if role not in {"admin", "user"}:
            raise ValueError("Роль: admin или user")
        user = self.get_user(user_id)
        if not user:
            return None
        if role != "admin" and user["role"] == "admin" and self.enabled_admin_count(exclude_id=user_id) < 1:
            raise ValueError("Нужен хотя бы один администратор")
        with self._lock:
            self._conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
            self._conn.commit()
        return self.get_user(user_id)

    def notify_chat_ids(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT telegram_id FROM users WHERE enabled = 1 AND notify = 1"
            ).fetchall()
        return [str(row["telegram_id"]) for row in rows]

    def create_login_token(self, *, ttl_seconds: int = 600) -> str:
        token = "l_" + secrets.token_hex(16)
        now = _now()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO login_tokens(token, created_at, expires_at)
                VALUES (?, ?, ?)
                """,
                (token, now, _later(ttl_seconds)),
            )
            self._conn.commit()
        return token

    def get_login_token(self, token: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM login_tokens WHERE token = ?", (token,)
            ).fetchone()
        return dict(row) if row else None

    def complete_login_token(self, token: str, user_id: int) -> str | None:
        row = self.get_login_token(token)
        if not row:
            return None
        if row.get("session_token"):
            return row["session_token"] if row.get("user_id") == user_id else None
        if row["expires_at"] < _now():
            return None
        session = self.create_session(user_id)
        with self._lock:
            self._conn.execute(
                """
                UPDATE login_tokens
                SET used_at = ?, user_id = ?, session_token = ?
                WHERE token = ?
                """,
                (_now(), user_id, session, token),
            )
            self._conn.commit()
        return session

    def create_session(self, user_id: int, *, ttl_days: int = 30) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO sessions(token, user_id, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (token, user_id, _now(), _later(ttl_days * 24 * 3600)),
            )
            self._conn.execute(
                "UPDATE users SET last_seen = ? WHERE id = ?",
                (_now(), user_id),
            )
            self._conn.commit()
        return token

    def get_session_user(self, session_token: str | None) -> dict | None:
        if not session_token:
            return None
        with self._lock:
            row = self._conn.execute(
                """
                SELECT s.token AS session_token, s.expires_at, u.*
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token = ?
                """,
                (session_token,),
            ).fetchone()
            if not row:
                return None
            if row["expires_at"] < _now() or not row["enabled"]:
                self._conn.execute("DELETE FROM sessions WHERE token = ?", (session_token,))
                self._conn.commit()
                return None
        return self._user_row(row)

    def delete_session(self, session_token: str | None) -> None:
        if not session_token:
            return
        with self._lock:
            self._conn.execute("DELETE FROM sessions WHERE token = ?", (session_token,))
            self._conn.commit()

    @staticmethod
    def _user_row(row: sqlite3.Row) -> dict:
        data = dict(row)
        data.pop("session_token", None)
        data.pop("expires_at", None)
        first = (data.get("first_name") or "").strip()
        last = (data.get("last_name") or "").strip()
        username = (data.get("username") or "").strip()
        name = " ".join(part for part in (first, last) if part) or (f"@{username}" if username else "Пользователь")
        data["display_name"] = name
        data["notify"] = bool(data.get("notify"))
        data["enabled"] = bool(data.get("enabled"))
        return data

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def save_calc_history(self, entry: dict) -> dict:
        now = _now()
        image = _pick_history_image(entry)
        quote = entry.get("quote") or {}
        auction = str(entry.get("auction") or "copart").strip().lower()
        if auction not in {"copart", "iaai"}:
            auction = "iaai" if auction in {"bidcars", "usa", "us"} else "copart"
        payload = json.dumps(entry, ensure_ascii=False, default=str)
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO calc_history(
                    lot_id, title, url, image, bid, total_uk, grand_usd,
                    category, location, auction, payload, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.get("lot_id"),
                    entry.get("title"),
                    entry.get("url"),
                    image,
                    entry.get("bid"),
                    quote.get("total_uk"),
                    quote.get("grand_usd"),
                    entry.get("category"),
                    entry.get("location"),
                    auction,
                    payload,
                    now,
                    now,
                ),
            )
            self._conn.commit()
            return self.get_calc_history(int(cur.lastrowid))

    def update_calc_history(self, history_id: int, entry: dict) -> dict | None:
        current = self.get_calc_history(history_id)
        if not current:
            return None
        now = _now()
        image = _pick_history_image(entry, current.get("image"))
        quote = entry.get("quote") or {}
        auction = str(entry.get("auction") or current.get("auction") or "copart").strip().lower()
        if auction not in {"copart", "iaai"}:
            auction = "iaai" if auction in {"bidcars", "usa", "us"} else "copart"
        payload = json.dumps(entry, ensure_ascii=False, default=str)
        with self._lock:
            self._conn.execute(
                """
                UPDATE calc_history SET
                    title = ?, url = ?, image = ?, bid = ?, total_uk = ?, grand_usd = ?,
                    category = ?, location = ?, auction = ?, payload = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    entry.get("title"),
                    entry.get("url"),
                    image,
                    entry.get("bid"),
                    quote.get("total_uk"),
                    quote.get("grand_usd"),
                    entry.get("category"),
                    entry.get("location"),
                    auction,
                    payload,
                    now,
                    history_id,
                ),
            )
            self._conn.commit()
        return self.get_calc_history(history_id)

    def list_calc_history(self, limit: int = 40) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, lot_id, title, url, image, bid, total_uk, grand_usd,
                       category, location, auction, created_at, updated_at
                FROM calc_history
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            auction = str(item.get("auction") or "").strip().lower()
            if not auction:
                url = str(item.get("url") or "").lower()
                auction = "iaai" if "bid.cars" in url else "copart"
            item["auction"] = auction
            items.append(item)
        return items

    def get_calc_history(self, history_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT id, lot_id, title, url, image, bid, total_uk, grand_usd,
                       category, location, auction, payload, created_at, updated_at
                FROM calc_history WHERE id = ?
                """,
                (history_id,),
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        try:
            data["payload"] = json.loads(data.get("payload") or "{}")
        except json.JSONDecodeError:
            data["payload"] = {}
        auction = str(data.get("auction") or "").strip().lower()
        if not auction:
            payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
            url = str(data.get("url") or payload.get("url") or "").lower()
            if payload.get("auction") == "iaai" or payload.get("source") == "bidcars" or "bid.cars" in url:
                auction = "iaai"
            else:
                auction = "copart"
        data["auction"] = auction
        return data

    @staticmethod
    def _lot_row(row: sqlite3.Row, fx_rate: float | None = None) -> dict:
        data = dict(row)
        names = data.get("search_names") or "[]"
        try:
            data["search_names"] = json.loads(names)
        except json.JSONDecodeError:
            data["search_names"] = [names] if names else []
        vat = data.get("vat_on_sale")
        data["vat_on_sale"] = None if vat is None else bool(vat)
        source = str(data.get("source") or "copart").strip().lower() or "copart"
        if source not in {"copart", "bidcars"}:
            url = str(data.get("url") or "").lower()
            source = "bidcars" if "bid.cars" in url else "copart"
        data["source"] = source
        lot_id = str(data.get("lot_id") or "")
        if source == "bidcars" and lot_id.lower().startswith("bc-"):
            data["display_lot_id"] = lot_id[3:]
        else:
            data["display_lot_id"] = lot_id
        if source == "bidcars":
            data["quote"] = None
        else:
            data["quote"] = quote_lot(
                bid=data.get("bid"),
                location=data.get("location"),
                category=data.get("category"),
                title=data.get("title") or "",
                body_style=data.get("body_style"),
                fx_rate=fx_rate,
            )
        data.setdefault("search_params", [])
        data.setdefault("search_summary", "")
        return data

    def _attach_search_params(self, lots: list[dict]) -> list[dict]:
        searches = self.list_searches(with_counts=False)
        by_name = {item["name"]: item for item in searches}
        by_summary = {item["summary"]: item for item in searches if item.get("summary")}
        for lot in lots:
            seen: set[tuple[str, str]] = set()
            params: list[dict] = []
            contacts: list[dict] = []
            for name in lot.get("search_names") or []:
                item = by_name.get(name) or by_summary.get(name)
                if not item:
                    continue
                for param in item.get("params") or []:
                    key = (param["label"], param["value"])
                    if key in seen:
                        continue
                    seen.add(key)
                    params.append(param)
                comment = item.get("comment") or ""
                telegram = item.get("client_telegram") or ""
                phone = item.get("client_phone") or ""
                if comment or telegram or phone:
                    contact = {
                        "search": item["name"],
                        "comment": comment,
                        "telegram": telegram,
                        "phone": phone,
                    }
                    if contact not in contacts:
                        contacts.append(contact)
            lot["search_params"] = params
            lot["search_summary"] = " · ".join(part["value"] for part in params)
            lot["search_contacts"] = contacts
        return lots
