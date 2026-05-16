"""Политика обработки результата проверки ключа.

Простая модель (2026-05-16):
- Живой ключ (включая phone-only через 008/020) → keep
- Заблокирован/невалид (003/004/006/060): Retail/OEM → delete, MAK → archive
- Чужой живой ключ (in_pool=False): тоже keep, пусть положит руками
- Чужой битый — skip

Никакого автоопределения категорий, никаких «защищённых» категорий —
всё это убрано после интервью с пользователем.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

# Точно мёртвые ключи: MS заблокировал/невалид/binding error.
# Retail/OEM → удалить из базы. MAK → переместить в архив (история нужна).
BLOCKED_CODES = {
    "0xC004C003",  # SL_E_CHPA_PRODUCT_KEY_BLOCKED
    "0xC004C004",  # SL_E_CHPA_INVALID_PRODUCT_KEY
    "0xC004C006",  # SL_E_CHPA_BINDING_INVALID
    "0xC004C060",  # SL_E_CHPA_DYNAMICALLY_BLOCKED_PRODUCT_KEY
}

# Онлайн исчерпан, но активация по телефону работает. Для нашего магазина = живой товар.
PHONE_OK_CODES = {
    "0xC004C008",  # SL_E_CHPA_MAXIMUM_UNLOCK_EXCEEDED
    "0xC004C020",  # SL_E_CHPA_DMAK_LIMIT_EXCEEDED
}


ActionKind = Literal["keep", "delete", "archive", "skip"]


@dataclass
class Action:
    """Что сделать с ключом по результату проверки."""
    kind: ActionKind
    reason: str = ""


def _norm_code(code: str | None) -> str:
    if not code:
        return ""
    return code.strip().upper().replace("0X", "0x")


def classify(result: dict, in_pool: bool) -> Action:
    """Главное правило: что делать с ключом по результату проверки.

    Параметры:
      result   — словарь от check.py / сервера 17777
      in_pool  — есть ли уже этот ключ в нашей БД
    """
    if not result.get("ok"):
        return Action(kind="skip", reason="проверка не удалась")

    code = _norm_code(result.get("online_code"))
    is_mak = bool(result.get("is_mak"))

    # Точно мёртвый
    if code in BLOCKED_CODES:
        if not in_pool:
            return Action(kind="skip", reason=f"чужой битый ключ ({code})")
        if is_mak:
            return Action(kind="archive", reason=f"MAK заблокирован ({code}) → в архив")
        return Action(kind="delete", reason=f"Retail/OEM заблокирован ({code}) → удалить")

    # Живой (online_ok, или phone-only код, или MAK с известным mak_count)
    is_alive = (
        result.get("online_ok") is True
        or code in PHONE_OK_CODES
        or (is_mak and isinstance(result.get("mak_count"), int) and result["mak_count"] >= 0)
    )
    if is_alive:
        return Action(kind="keep", reason="живой")

    # Неоднозначно (sku-mismatch, конфиг-ошибки) — оставляем как есть
    return Action(kind="keep", reason=f"неоднозначный код {code or '(нет)'} — оставляем")
