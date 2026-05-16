"""Фоновая автопроверка ключей.

Простая модель (2026-05-16 после интервью):
- Раз в 24 часа воркер обходит ВСЕ ключи во всех категориях, включая архив.
- Никаких «защищённых» категорий.
- Никакого автоперемещения по жизненному циклу.
- Применяется только policy.classify: live → keep, blocked → delete (Retail/OEM)
  или archive (MAK).
- Sold-ключи пропускаются (это история продаж).

Дроссель: 2 секунды между запросами к серверу :17777.
"""
from __future__ import annotations
import os
import time
import json
from datetime import datetime
from PyQt6.QtCore import QThread, pyqtSignal

from .db import DB, ARCHIVE_CATEGORY_NAME
from .checker import CheckerClient
from . import policy

STATE_FILE = os.path.expanduser("~/.local/share/keystore/auto_check.state.json")
LOG_FILE = os.path.expanduser("~/.local/share/keystore/auto_check.log")

INTERVAL_SECONDS = 24 * 3600           # раз в сутки
THROTTLE_SECONDS = 2.0                 # пауза между запросами к MS
FIRST_RUN_DELAY_SECONDS = 60           # первый прогон через минуту после старта Vault


def _load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(state: dict):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception:
        pass


def _log(message: str):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"[{ts}] {message}\n")
    except Exception:
        pass


class AutoCheckWorker(QThread):
    """Один прогон автопроверки. Один прогон в сутки = достаточно."""
    finished_run = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.client = CheckerClient()
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        if not self.client.health():
            _log("сервер :17777 недоступен — пропускаю прогон")
            self.finished_run.emit({"error": "server_offline"})
            return

        db = DB()
        archive_id = db.get_archive_category_id()
        cats = db.list_categories()

        _log(f"старт прогона; категорий к обходу: {len(cats)} (включая архив)")

        stats = {
            "checked": 0, "deleted": 0, "archived": 0, "kept": 0,
            "skipped_sold": 0, "errors": 0,
        }

        for cat in cats:
            if self._stop:
                _log("остановлен по запросу")
                break
            keys = db.list_keys(category_id=cat.id)
            _log(f"  '{cat.name}': {len(keys)} ключ(а)")

            for k in keys:
                if self._stop:
                    break
                if k.status == "sold":
                    stats["skipped_sold"] += 1
                    continue

                try:
                    r = self.client.check(
                        k.key, online=True, mak_count=True,
                        consume=True,
                        allow_consume_retail=True,
                    )
                except Exception as e:
                    stats["errors"] += 1
                    _log(f"    {k.key}: ошибка проверки — {e}")
                    time.sleep(THROTTLE_SECONDS)
                    continue

                try:
                    db.update_check_result(k.id, r)
                except Exception as e:
                    _log(f"    {k.key}: ошибка записи в БД — {e}")

                action = policy.classify(r, in_pool=True)
                if action.kind == "delete":
                    db.delete_keys([k.id])
                    stats["deleted"] += 1
                    _log(f"    {k.key}: УДАЛЁН ({action.reason})")
                elif action.kind == "archive":
                    # MAK-ключ уже может быть в архиве — не двигаем
                    if cat.id != archive_id:
                        db.move_key(k.id, archive_id)
                    stats["archived"] += 1
                    _log(f"    {k.key}: В АРХИВ ({action.reason})")
                else:
                    stats["kept"] += 1

                stats["checked"] += 1
                time.sleep(THROTTLE_SECONDS)

        state = _load_state()
        state["last_run_at"] = int(time.time())
        state["last_stats"] = stats
        _save_state(state)

        _log(f"конец прогона: {stats}")
        self.finished_run.emit(stats)


def should_run_now() -> bool:
    """Пора ли будить воркер? Да, если прошло >= 24ч с последнего прогона."""
    state = _load_state()
    last = state.get("last_run_at", 0)
    return (int(time.time()) - last) >= INTERVAL_SECONDS


def seconds_until_next_run() -> int:
    """Сколько секунд до следующего пробуждения воркера."""
    state = _load_state()
    last = state.get("last_run_at", 0)
    if last == 0:
        return FIRST_RUN_DELAY_SECONDS
    elapsed = int(time.time()) - last
    remaining = INTERVAL_SECONDS - elapsed
    return max(remaining, FIRST_RUN_DELAY_SECONDS)


def last_run_info() -> dict:
    """Информация о последнем прогоне для UI."""
    state = _load_state()
    return {
        "last_run_at": state.get("last_run_at"),
        "last_stats": state.get("last_stats", {}),
    }
