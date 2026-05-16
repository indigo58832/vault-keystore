"""Recode (мутация) Microsoft-ключа: тот же Product ID, визуально другой ключ.

Логика взята из work_tool/generator_key/key_tool.py. Алгоритм:
- декодируем ключ в (group, serial, security, upgrade, extra)
- сохраняем нижние 48 бит security
- генерируем новый верхний counter (5 бит, рандом)
- собираем обратно, пересчитываем CRC checksum
"""
from __future__ import annotations
import random
from functools import reduce

ALPHABET = "BCDFGHJKMPQRTVWXY2346789"


def _crc_table():
    tab = []
    for i in range(256):
        k = i << 24
        for _ in range(8):
            k = (k << 1) ^ 0x4C11DB7 if k & 0x80000000 else k << 1
        tab.append(k & 0xFFFFFFFF)
    return tab


CRC_TABLE = _crc_table()


def decode(key: str) -> dict:
    key = key.replace("-", "").upper()
    n_pos = key.index("N")
    digits = [n_pos] + [ALPHABET.index(c) for c in key.replace("N", "")]
    val = reduce(lambda a, x: a * 24 + x, digits)
    return {
        "group":    (val & 0x000FFFFF),
        "serial":   (val & 0x003FFFFFFF00000) >> 20,
        "security": (val & 0x0007FFFFFFFFFFFFC000000000000) >> 50,
        "checksum": (val & 0x0001FF80000000000000000000000000) >> 103,
        "upgrade":  (val & 0x00020000000000000000000000000000) >> 113,
        "extra":    (val & 0x00040000000000000000000000000000) >> 114,
    }


def _compute_checksum(val_no_crc: int) -> int:
    crc = 0xFFFFFFFF
    for byte in val_no_crc.to_bytes(16, "little"):
        crc = (crc << 8) ^ CRC_TABLE[((crc >> 24) ^ byte) & 0xFF]
    return (~crc) & 0x3FF


def encode(group: int, serial: int, security: int, upgrade: int, extra: int) -> str:
    val = (extra << 114) | (upgrade << 113) | (security << 50) | (serial << 20) | group
    checksum = _compute_checksum(val)
    val |= checksum << 103
    num = 0
    for _ in range(25):
        num = (num << 8) | (val % 24)
        val //= 24
    raw = num.to_bytes(25, "little")
    chars = [ALPHABET[b] for b in raw[1:]]
    chars.insert(raw[0], "N")
    s = "".join(chars)
    return "-".join(s[i:i + 5] for i in range(0, 25, 5))


def verify(key: str) -> bool:
    try:
        f = decode(key)
    except (ValueError, KeyError):
        return False
    val_no_crc = (
        (f["extra"] << 114) | (f["upgrade"] << 113) | (f["security"] << 50) |
        (f["serial"] << 20) | f["group"]
    )
    return _compute_checksum(val_no_crc) == f["checksum"]


def recode(key: str, *, rng: random.Random | None = None) -> str:
    """Делает recode: меняет верхние 5 бит counter в security, остальное не трогает.
    Возвращает визуально другой ключ с тем же group/serial/security_base/upgrade.
    Для Microsoft activation это **тот же** ключ (по Product ID/Advanced PID)."""
    r = rng or random
    f = decode(key)
    base_security = f["security"] & 0xFFFFFFFFFFFF
    new_counter = r.randint(0, 0x1F)
    new_security = (new_counter << 48) | base_security
    return encode(f["group"], f["serial"], new_security, f["upgrade"], f["extra"])


def recode_unique(key: str, count: int) -> list[str]:
    """Возвращает count визуально-разных recode-ключей.
    Counter имеет всего 5 бит (0..31) → максимум 31 уникальный (минус оригинал).
    Сам оригинал в результат НЕ включается.
    """
    r = random.Random()
    original = key.replace("-", "").upper()
    seen: set[str] = {original}
    out: list[str] = []
    tries = 0
    max_unique = 31  # верхняя граница без оригинала
    while len(out) < min(count, max_unique) and tries < count * 20:
        tries += 1
        candidate = recode(key, rng=r)
        norm = candidate.replace("-", "").upper()
        if norm in seen:
            continue
        seen.add(norm)
        out.append(candidate)
    return out
