"""SQLite слой. Все ключи и категории живут здесь."""
from __future__ import annotations
import sqlite3
import os
import time
from dataclasses import dataclass
from typing import Iterable

DEFAULT_DB_PATH = os.path.expanduser("~/.local/share/keystore/keys.db")

ARCHIVE_CATEGORY_NAME = "Склад старых ключей"


@dataclass
class Section:
    """Раздел — контейнер для категорий. Первый уровень дерева."""
    id: int
    name: str
    sort_order: int


@dataclass
class Category:
    id: int
    name: str
    sort_order: int
    section_id: int | None = None  # FK на sections.id; None — категория без раздела
    group_name: str | None = None  # устаревшее, оставлено для совместимости


@dataclass
class Key:
    id: int
    key: str
    category_id: int
    status: str            # available | sold | blocked | exhausted | unknown
    last_checked_at: int | None
    # кэш последней проверки
    edition: str | None
    description: str | None
    type_label: str | None
    is_mak: int            # 0/1
    mak_count: int | None
    online_code: str | None
    online_human: str | None
    # метаданные
    added_at: int
    sold_at: int | None
    sold_to: str | None
    note: str | None


SCHEMA = """
CREATE TABLE IF NOT EXISTS sections (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    group_name TEXT,
    section_id INTEGER REFERENCES sections(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS keys (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    category_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'unknown',
    last_checked_at INTEGER,

    edition TEXT,
    description TEXT,
    type_label TEXT,
    is_mak INTEGER NOT NULL DEFAULT 0,
    mak_count INTEGER,
    online_code TEXT,
    online_human TEXT,

    added_at INTEGER NOT NULL,
    sold_at INTEGER,
    sold_to TEXT,
    note TEXT,

    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_keys_status ON keys(status);
CREATE INDEX IF NOT EXISTS idx_keys_category ON keys(category_id);
"""


class DB:
    def __init__(self, path: str = DEFAULT_DB_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self._migrate()

    def _migrate(self):
        """Одноразовые правки старых записей под новую логику."""
        # exhausted с кодом 0xC004C008/0xC004C020 → phone_only (онлайн вышло, phone работает).
        self.conn.execute(
            """UPDATE keys SET status = 'phone_only'
               WHERE status = 'exhausted'
                 AND upper(online_code) IN ('0XC004C008', '0XC004C020')"""
        )
        # Колонки для старых БД
        cols = {row["name"] for row in self.conn.execute("PRAGMA table_info(categories)")}
        if "group_name" not in cols:
            self.conn.execute("ALTER TABLE categories ADD COLUMN group_name TEXT")
        if "section_id" not in cols:
            self.conn.execute("ALTER TABLE categories ADD COLUMN section_id INTEGER REFERENCES sections(id) ON DELETE SET NULL")
        self.conn.commit()
        # Миграция group_name (текстовая строка) → section_id (реальная сущность).
        # Запускается один раз, когда есть категории с group_name но без section_id.
        self._migrate_groups_to_sections()
        # Чистка: «Без раздела» — виртуальный раздел в UI, не должен быть в sections
        self._cleanup_reserved_sections()

    def _cleanup_reserved_sections(self):
        """Убирает из sections запись «Без раздела» (если осталась от старых миграций).
        Категории, которые на неё ссылались, получают section_id = NULL."""
        row = self.conn.execute(
            "SELECT id FROM sections WHERE name = 'Без раздела'"
        ).fetchone()
        if row:
            sid = row["id"]
            self.conn.execute(
                "UPDATE categories SET section_id = NULL WHERE section_id = ?", (sid,)
            )
            self.conn.execute("DELETE FROM sections WHERE id = ?", (sid,))
            self.conn.commit()

    def _migrate_groups_to_sections(self):
        """Преобразует устаревший group_name в записи в таблице sections.
        Для каждого уникального непустого group_name создаёт раздел,
        а у соответствующих категорий заполняет section_id.
        Также пытается вывести раздел по имени для категорий с NULL group_name."""
        # Категории с group_name но без section_id
        rows = self.conn.execute(
            "SELECT id, name, group_name FROM categories WHERE section_id IS NULL"
        ).fetchall()
        if not rows:
            return

        now = int(time.time())

        def get_or_create_section(name: str) -> int:
            r = self.conn.execute("SELECT id FROM sections WHERE name = ?", (name,)).fetchone()
            if r:
                return r["id"]
            cur = self.conn.execute(
                "INSERT INTO sections(name, sort_order) VALUES (?, ?)", (name, now)
            )
            return cur.lastrowid

        def infer_section(cat_name: str) -> str | None:
            n = (cat_name or "").lower()
            if "офис" in n or "office" in n:
                return "Office"
            if "psn" in n or "playstation" in n or "ps5" in n or "ps4" in n:
                return "PSN"
            if "win" in n or "вин" in n or "windows" in n:
                return "Windows"
            if "склад" in n or "архив" in n:
                return "Архив"
            return None

        for r in rows:
            target = (r["group_name"] or "").strip() if r["group_name"] else None
            if not target:
                target = infer_section(r["name"])
            if not target or target == "Без раздела":
                # «Без раздела» — виртуальная корзина, не создаём как реальную секцию
                continue
            section_id = get_or_create_section(target)
            self.conn.execute(
                "UPDATE categories SET section_id = ? WHERE id = ?",
                (section_id, r["id"]),
            )
        self.conn.commit()

    # --- sections ---

    def list_sections(self) -> list[Section]:
        rows = self.conn.execute(
            "SELECT id, name, sort_order FROM sections ORDER BY sort_order, name"
        ).fetchall()
        return [Section(r["id"], r["name"], r["sort_order"]) for r in rows]

    def add_section(self, name: str) -> int:
        name = name.strip()
        if not name:
            raise ValueError("Имя раздела пустое")
        # «Без раздела» — зарезервированное виртуальное имя в UI
        if name == "Без раздела":
            raise ValueError("Имя «Без раздела» зарезервировано")
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO sections(name, sort_order) VALUES (?, ?)",
            (name, int(time.time())),
        )
        self.conn.commit()
        if cur.lastrowid:
            return cur.lastrowid
        r = self.conn.execute("SELECT id FROM sections WHERE name = ?", (name,)).fetchone()
        return r["id"]

    def rename_section(self, section_id: int, new_name: str):
        self.conn.execute("UPDATE sections SET name = ? WHERE id = ?",
                          (new_name.strip(), section_id))
        self.conn.commit()

    def delete_section(self, section_id: int):
        """Удаляет раздел. Категории внутри становятся «без раздела» (section_id = NULL)."""
        self.conn.execute("UPDATE categories SET section_id = NULL WHERE section_id = ?",
                          (section_id,))
        self.conn.execute("DELETE FROM sections WHERE id = ?", (section_id,))
        self.conn.commit()

    def find_section_by_name(self, name: str) -> Section | None:
        r = self.conn.execute("SELECT id, name, sort_order FROM sections WHERE name = ?",
                              (name,)).fetchone()
        if r:
            return Section(r["id"], r["name"], r["sort_order"])
        return None

    def set_category_section(self, cat_id: int, section_id: int | None):
        self.conn.execute("UPDATE categories SET section_id = ? WHERE id = ?",
                          (section_id, cat_id))
        self.conn.commit()

    # --- categories ---

    def list_categories(self) -> list[Category]:
        rows = self.conn.execute(
            "SELECT id, name, sort_order, group_name, section_id "
            "FROM categories ORDER BY sort_order, name"
        ).fetchall()
        return [Category(r["id"], r["name"], r["sort_order"],
                         r["section_id"], r["group_name"]) for r in rows]

    def add_category(self, name: str, group_name: str | None = None,
                     section_id: int | None = None) -> int:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO categories(name, sort_order, group_name, section_id) "
            "VALUES (?, ?, ?, ?)",
            (name.strip(), int(time.time()), group_name, section_id),
        )
        self.conn.commit()
        if cur.lastrowid:
            return cur.lastrowid
        row = self.conn.execute("SELECT id FROM categories WHERE name = ?", (name.strip(),)).fetchone()
        return row["id"]

    def set_category_group(self, cat_id: int, group_name: str | None) -> None:
        """Устаревший метод. Используй set_category_section."""
        self.conn.execute("UPDATE categories SET group_name = ? WHERE id = ?",
                          (group_name, cat_id))
        self.conn.commit()

    def rename_category(self, cat_id: int, new_name: str) -> None:
        self.conn.execute("UPDATE categories SET name = ? WHERE id = ?", (new_name.strip(), cat_id))
        self.conn.commit()

    def delete_category(self, cat_id: int) -> None:
        self.conn.execute("DELETE FROM categories WHERE id = ?", (cat_id,))
        self.conn.commit()

    # --- keys ---

    def list_keys(
        self, category_id: int | None = None, status: str | None = None
    ) -> list[Key]:
        sql = "SELECT * FROM keys"
        params: list = []
        clauses: list[str] = []
        if category_id is not None:
            clauses.append("category_id = ?")
            params.append(category_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY (status = 'available') DESC, added_at ASC"
        rows = self.conn.execute(sql, params).fetchall()
        return [_row_to_key(r) for r in rows]

    def add_keys(self, category_id: int, keys: Iterable[str]) -> tuple[int, int]:
        """Вернёт (added, duplicates)."""
        added = 0
        dups = 0
        now = int(time.time())
        for k in keys:
            k = k.strip().upper()
            if not k:
                continue
            try:
                self.conn.execute(
                    "INSERT INTO keys(key, category_id, status, added_at) VALUES (?, ?, 'unknown', ?)",
                    (k, category_id, now),
                )
                added += 1
            except sqlite3.IntegrityError:
                dups += 1
        self.conn.commit()
        return added, dups

    def add_clones(self, parent_key_id: int, new_keys: Iterable[str]) -> tuple[int, int]:
        """Добавляет ключи-клоны: копирует все «общие» свойства родителя.
        Для recode'нутых MAK-ключей это правильно: они = тот же ключ у MS,
        значит у них один тип/эдишн/Advanced PID/MAK count.

        НЕ копируем: sold_at, sold_to (новые свежие, не проданы), added_at (свой now).
        """
        parent = self.conn.execute(
            "SELECT * FROM keys WHERE id = ?", (parent_key_id,)
        ).fetchone()
        if not parent:
            return 0, 0
        added = 0
        dups = 0
        now = int(time.time())
        for k in new_keys:
            k = k.strip().upper()
            if not k:
                continue
            try:
                self.conn.execute(
                    """INSERT INTO keys(
                        key, category_id, status, last_checked_at,
                        edition, description, type_label,
                        is_mak, mak_count,
                        online_code, online_human,
                        added_at, note
                    ) VALUES (?, ?, ?, ?,  ?, ?, ?,  ?, ?,  ?, ?,  ?, ?)""",
                    (
                        k, parent["category_id"], parent["status"], parent["last_checked_at"],
                        parent["edition"], parent["description"], parent["type_label"],
                        parent["is_mak"], parent["mak_count"],
                        parent["online_code"], parent["online_human"],
                        now, parent["note"],
                    ),
                )
                added += 1
            except sqlite3.IntegrityError:
                dups += 1
        self.conn.commit()
        return added, dups

    def update_check_result(self, key_id: int, result: dict) -> None:
        """Запись результата с keystore.checker.check() в БД."""
        status = _status_from_result(result)
        self.conn.execute(
            """UPDATE keys SET
                last_checked_at = ?,
                edition = ?, description = ?, type_label = ?,
                is_mak = ?, mak_count = ?,
                online_code = ?, online_human = ?,
                status = ?
            WHERE id = ?""",
            (
                int(time.time()),
                result.get("edition"),
                result.get("description"),
                result.get("type_label"),
                1 if result.get("is_mak") else 0,
                result.get("mak_count"),
                result.get("online_code"),
                result.get("online_human"),
                status,
                key_id,
            ),
        )
        self.conn.commit()

    def mark_sold(self, key_id: int, sold_to: str | None = None) -> None:
        self.conn.execute(
            "UPDATE keys SET status = 'sold', sold_at = ?, sold_to = ? WHERE id = ?",
            (int(time.time()), sold_to, key_id),
        )
        self.conn.commit()

    def mark_available(self, key_id: int) -> None:
        self.conn.execute(
            "UPDATE keys SET status = 'available', sold_at = NULL, sold_to = NULL WHERE id = ?",
            (key_id,),
        )
        self.conn.commit()

    def get_archive_category_id(self) -> int:
        """Найти или создать спец-категорию архива (`Склад старых ключей`)."""
        return self.add_category(ARCHIVE_CATEGORY_NAME)

    def move_key(self, key_id: int, new_category_id: int) -> None:
        """Переместить ключ в другую категорию (используется для архивации MAK)."""
        self.conn.execute(
            "UPDATE keys SET category_id = ? WHERE id = ?",
            (new_category_id, key_id),
        )
        self.conn.commit()

    def get_key_by_string(self, key: str) -> Key | None:
        """Найти ключ по самой строке (для проверки in_pool в quick_check)."""
        key = key.strip().upper()
        row = self.conn.execute("SELECT * FROM keys WHERE key = ?", (key,)).fetchone()
        return _row_to_key(row) if row else None

    def find_replacement(self, description: str, exclude_key_id: int | None = None) -> Key | None:
        """Найти потенциально живой ключ с тем же `description`.
        Возвращает первый по приоритету: available → phone_only → unknown.
        НЕ возвращает sold/blocked/exhausted.
        Перед использованием ОБЯЗАТЕЛЬНО проверить через MS (вдруг unknown оказался мёртв).
        """
        if not description:
            return None
        for status in ("available", "phone_only", "unknown"):
            sql = "SELECT * FROM keys WHERE status = ? AND description = ?"
            params: list = [status, description]
            if exclude_key_id is not None:
                sql += " AND id != ?"
                params.append(exclude_key_id)
            sql += " ORDER BY added_at ASC LIMIT 1"
            row = self.conn.execute(sql, params).fetchone()
            if row:
                return _row_to_key(row)
        return None

    def find_replacements_all(self, description: str, exclude_key_id: int | None = None,
                              limit: int = 20) -> list[Key]:
        """Все потенциально живые ключи с тем же description (для перебора в случае
        если первый окажется мёртвым). Тот же приоритет: available → phone_only → unknown.
        """
        if not description:
            return []
        out: list[Key] = []
        for status in ("available", "phone_only", "unknown"):
            sql = "SELECT * FROM keys WHERE status = ? AND description = ?"
            params: list = [status, description]
            if exclude_key_id is not None:
                sql += " AND id != ?"
                params.append(exclude_key_id)
            sql += " ORDER BY added_at ASC"
            for row in self.conn.execute(sql, params).fetchall():
                out.append(_row_to_key(row))
                if len(out) >= limit:
                    return out
        return out

    def find_category_by_name(self, name: str) -> Category | None:
        row = self.conn.execute("SELECT * FROM categories WHERE name = ?", (name,)).fetchone()
        if row:
            return Category(row["id"], row["name"], row["sort_order"],
                            row["section_id"], row["group_name"])
        return None

    def get_keys_by_ids(self, key_ids: Iterable[int]) -> list[Key]:
        ids = list(key_ids)
        if not ids:
            return []
        q = "SELECT * FROM keys WHERE id IN ({})".format(",".join("?" * len(ids)))
        return [_row_to_key(r) for r in self.conn.execute(q, ids).fetchall()]

    def delete_keys(self, key_ids: Iterable[int]) -> None:
        ids = list(key_ids)
        if not ids:
            return
        q = "DELETE FROM keys WHERE id IN ({})".format(",".join("?" * len(ids)))
        self.conn.execute(q, ids)
        self.conn.commit()

    def set_note(self, key_id: int, note: str | None) -> None:
        self.conn.execute("UPDATE keys SET note = ? WHERE id = ?", (note, key_id))
        self.conn.commit()

    def category_stats(self, category_id: int) -> dict:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) c FROM keys WHERE category_id = ? GROUP BY status",
            (category_id,),
        ).fetchall()
        out = {"total": 0, "available": 0, "phone_only": 0, "sold": 0,
               "blocked": 0, "exhausted": 0, "unknown": 0}
        for r in rows:
            out[r["status"]] = r["c"]
            out["total"] += r["c"]
        # «реально рабочие» = свободные (online valid) + рабочие по телефону
        out["working"] = out["available"] + out["phone_only"]
        return out


def _row_to_key(r: sqlite3.Row) -> Key:
    return Key(
        id=r["id"], key=r["key"], category_id=r["category_id"], status=r["status"],
        last_checked_at=r["last_checked_at"],
        edition=r["edition"], description=r["description"], type_label=r["type_label"],
        is_mak=r["is_mak"], mak_count=r["mak_count"],
        online_code=r["online_code"], online_human=r["online_human"],
        added_at=r["added_at"], sold_at=r["sold_at"], sold_to=r["sold_to"], note=r["note"],
    )


def _status_from_result(result: dict) -> str:
    """Маппит ответ check.py в status.

    ВАЖНО: 0xC004C008 и 0xC004C020 значат «онлайн-квота вышла», но
    ТЕЛЕФОННАЯ активация (через Confirmation ID) у этих ключей ещё работает —
    для Phone-товара это рабочий ключ. Поэтому статус 'phone_only', не 'exhausted'.
    """
    if not result.get("ok"):
        return "unknown"
    code = (result.get("online_code") or "").upper()
    # онлайн исчерпан, но phone живой
    if code in ("0XC004C020", "0XC004C008"):
        return "phone_only"
    # реально мёртвый — заблокирован MS
    if code in ("0XC004C003", "0XC004C060"):
        return "blocked"
    # MAK Count 0 — тоже только онлайн исчерпан, phone мог жить
    if result.get("is_mak") and result.get("mak_count") == 0:
        return "phone_only"
    if result.get("online_ok") is True:
        return "available"
    if result.get("online_ok") is False:
        return "blocked"
    return "unknown"
