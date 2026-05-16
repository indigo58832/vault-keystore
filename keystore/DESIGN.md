# Дизайн расширения Vault — реализация 5 идей

> **Статус**: реализовано 2026-05-12. Что в каком файле — в разделе «Реализация по модулям». Тесты — в разделе «Тесты».


## Сводка кодов ошибок Microsoft

| Код | Значение | Действие |
|---|---|---|
| `0xC004C003` | заблокирован MS | **delete** (если Retail) / **archive** (если MAK) |
| `0xC004C004` | невалидный ключ | **delete** / **archive (MAK)** |
| `0xC004C006` | binding invalid | **delete** / **archive (MAK)** |
| `0xC004C060` | отозван (dynamically blocked) | **delete** / **archive (MAK)** |
| `0xC004C008` | онлайн квота исчерпана, **phone работает** | **keep** (status=phone_only) |
| `0xC004C020` | MAK лимит, **phone работает** | **keep** (status=phone_only) |
| `0xC004C00D`, `0xC004F069`, `0xC004E016`, `0xC004F050` | конфиг/SKU несовпадает | **keep** (не трогать — может быть просто не в той категории) |

Константы:
```python
BLOCKED_CODES = {"0xC004C003", "0xC004C004", "0xC004C006", "0xC004C060"}
PHONE_OK_CODES = {"0xC004C008", "0xC004C020"}
```

## Архитектурное правило

Чтобы 5 функций не были связаны в спагетти-кашу, выделяю **слой «политика обработки результата»** — одно место принимает результат проверки и решает что с ним делать.

```
[результат проверки] → policy.classify(result) → ClassifiedAction
                                                   ├── update_status(...)
                                                   ├── delete()
                                                   ├── archive()
                                                   └── add_new_to_pool(category)
```

Это будет модуль **`keystore/policy.py`**. Все функции (`_on_one_done` в main_window и quick_check) зовут одну и ту же логику и расходятся только в UX.

## Маппинг description → category

Простой, в коде. Если категория с таким именем существует — кладём туда. Если нет — кладём в спец «Inbox».

```python
def category_for_description(desc: str, is_mak: bool) -> str | None:
    """Возвращает имя категории-кандидата или None если непонятно куда."""
    if not desc:
        return None
    d = desc
    if any(k in d for k in ("Win 10", "Win 11", "Windows 10", "Windows 11")):
        if "Professional" in d:
            return "Windows Pro Phone" if is_mak else "Windows Pro Online"
        if "Core" in d or "Home" in d:
            return "Windows Home phone" if is_mak else "Windows Home Online"
        if "Enterprise" in d:
            return "Вин 10 Корпоративная"
    if "Office24" in d or "ProPlus2024" in d:
        return "Office 24 PP Phone" if is_mak else "Office 24 PP Online"
    if "ProPlus2021" in d:
        return "Office PP 21 Phone"
    if "ProPlus2019" in d:
        return "Office PP 19 Phone"
    if "Office16_ProPlus" in d or "ProPlus" in d and "2016" in d:
        return "Office PP 16 Phone"
    return None
```

Если категория с таким именем не существует в БД и автоматическое создание не разрешено — кладём в «Inbox». Можно или просто игнорим ключ и говорим пользователю «не понял куда положить».

## Архив

- Категория с именем `"Склад старых ключей"` (уже есть у пользователя в БД из импорта Obsidian)
- `db.get_archive_category_id()` — найти или создать
- Когда блокированный MAK обнаружен → `move_key(key_id, archive_id)` вместо удаления

## Реализация по модулям

### `keystore/policy.py` — НОВЫЙ модуль

```python
from dataclasses import dataclass
from typing import Literal

BLOCKED_CODES = {"0xC004C003", "0xC004C004", "0xC004C006", "0xC004C060"}
PHONE_OK_CODES = {"0xC004C008", "0xC004C020"}

@dataclass
class Action:
    """Что делать с ключом по результату проверки."""
    kind: Literal["keep", "delete", "archive", "add_to_pool", "skip"]
    target_category_name: str | None = None   # для add_to_pool
    reason: str = ""                          # для логов

def classify(result: dict, in_pool: bool) -> Action:
    """Решает что делать с ключом после проверки.
    
    in_pool — есть ли уже этот ключ в нашей БД.
    """
    if not result.get("ok"):
        return Action(kind="skip", reason="result not ok")
    
    code = (result.get("online_code") or "").upper().replace("0X", "0x")
    is_mak = bool(result.get("is_mak"))
    
    # точно мёртвый
    if code in BLOCKED_CODES:
        if in_pool:
            if is_mak:
                return Action(kind="archive", reason=f"MAK blocked {code} → archive")
            else:
                return Action(kind="delete", reason=f"Retail blocked {code} → delete")
        else:
            return Action(kind="skip", reason=f"foreign blocked, not adding")
    
    # рабочий (включая phone)
    if result.get("online_ok") is True or code in PHONE_OK_CODES or (is_mak and result.get("mak_count", -1) >= 0):
        if in_pool:
            return Action(kind="keep", reason="alive, update status only")
        else:
            cat = category_for_description(result.get("description"), is_mak)
            if cat:
                return Action(kind="add_to_pool", target_category_name=cat,
                              reason=f"foreign alive → add to {cat}")
            else:
                return Action(kind="skip", reason="no category mapping")
    
    return Action(kind="keep", reason="ambiguous, keep status")
```

### `keystore/db.py` — расширение

Добавить:

```python
ARCHIVE_CATEGORY_NAME = "Склад старых ключей"

def get_archive_category_id(self) -> int:
    """Найти/создать категорию архива."""
    cat = self.conn.execute(
        "SELECT id FROM categories WHERE name = ?", (self.ARCHIVE_CATEGORY_NAME,)
    ).fetchone()
    if cat: return cat["id"]
    return self.add_category(self.ARCHIVE_CATEGORY_NAME)

def move_key(self, key_id: int, new_category_id: int) -> None:
    self.conn.execute(
        "UPDATE keys SET category_id = ? WHERE id = ?",
        (new_category_id, key_id)
    )
    self.conn.commit()

def get_key_by_string(self, key: str) -> Key | None:
    """Найти ключ по самой строке. Нужно для quick_check (проверки in_pool)."""
    key = key.strip().upper()
    row = self.conn.execute("SELECT * FROM keys WHERE key = ?", (key,)).fetchone()
    return _row_to_key(row) if row else None

def find_replacement(self, description: str, exclude_key_id: int | None = None) -> Key | None:
    """Найти живой ключ с тем же description.
    Сначала ищет available, потом phone_only.
    Исключает заданный key_id (чтобы не предложить тот же ключ как замену себе)."""
    for status in ("available", "phone_only"):
        sql = """SELECT * FROM keys
                 WHERE status = ? AND description = ?"""
        params = [status, description]
        if exclude_key_id is not None:
            sql += " AND id != ?"
            params.append(exclude_key_id)
        sql += " ORDER BY added_at ASC LIMIT 1"
        row = self.conn.execute(sql, params).fetchone()
        if row:
            return _row_to_key(row)
    return None

def find_category_by_name(self, name: str) -> Category | None:
    row = self.conn.execute("SELECT * FROM categories WHERE name = ?", (name,)).fetchone()
    return Category(row["id"], row["name"], row["sort_order"]) if row else None
```

### `keystore/main_window.py` — интеграция

В `_on_one_done(key_id, result)` — после `update_check_result()` применить policy:

```python
def _on_one_done(self, key_id: int, result: dict):
    self.db.update_check_result(key_id, result)
    action = policy.classify(result, in_pool=True)
    
    if action.kind == "delete":
        self.db.delete_keys([key_id])
    elif action.kind == "archive":
        archive_id = self.db.get_archive_category_id()
        self.db.move_key(key_id, archive_id)
    # keep — ничего не делаем, статус уже обновлён
    
    self._reload_keys()  # обновить строку или убрать
    # лог в статус-бар: что случилось
```

В `_add_keys()` — после добавления, если включена автопроверка, запустить CheckWorker с `consume=False`:

```python
def _add_keys(self):
    # ... текущий код ...
    added, dups = self.db.add_keys(...)
    
    # автопроверка новых
    if self.auto_check_on_add:
        # достать ID только что добавленных
        new_ids = [...]  # query из БД
        items = [(kid, key) for kid, key in ...]
        self._start_check_worker(items, consume=False)  # принудительно без consume
```

В `__init__` — добавить настройку `self.auto_check_on_add = True`. Можно в UI настроек или просто константой.

### `keystore/quick_check.py` — интеграция с БД

В `CheckWorker.__init__` — получить БД:
```python
self.db = DB()
```

В `CheckWorker.run()` — после check'а применить policy. Сигналы:
- `one_done(result)` — для рендера
- `pool_changed()` — если что-то поменялось в БД (для лога)
- `replacement_found(dead_result, replacement_result)` — для UI идеи №4

```python
def run(self):
    for k in self.keys:
        try:
            r = self.client.check(k, online=True, mak_count=True, consume=self.consume)
        except Exception as e:
            r = {"key": k, "ok": False, "error": str(e)}
        
        existing = self.db.get_key_by_string(k)
        action = policy.classify(r, in_pool=bool(existing))
        
        if action.kind == "delete" and existing:
            # MAK не удалять — проверка уже отрабатывает в classify
            self.db.delete_keys([existing.id])
        elif action.kind == "archive" and existing:
            self.db.move_key(existing.id, self.db.get_archive_category_id())
        elif action.kind == "add_to_pool" and not existing and action.target_category_name:
            cat = self.db.find_category_by_name(action.target_category_name)
            if cat:
                self.db.add_keys(cat.id, [k])
                # после добавления — обновим кэш проверки чтобы не нужно было проверять заново
                new_key = self.db.get_key_by_string(k)
                if new_key:
                    self.db.update_check_result(new_key.id, r)
        
        self.one_done.emit(r, action.__dict__)  # передаём action для рендера
        
        # ИДЕЯ 4: автозамена при блок
        if action.kind in ("delete", "archive"):
            repl = self.db.find_replacement(r.get("description"), exclude_key_id=(existing.id if existing else None))
            if repl:
                # проверим что замена жива
                rcheck = self.client.check(repl.key, online=True, mak_count=False, consume=False)
                if rcheck.get("ok") and rcheck.get("online_ok") is not False:
                    self.replacement_found.emit(r, rcheck, repl.id)
    
    self.finished_all.emit()
```

В `QuickCheckWindow`:
- Слот `_on_replacement_found(dead, alive, repl_id)` — добавить в карточки специальный блок «✓ Найдена замена …» с кнопкой «Скопировать»
- В `render_result` использовать `action` чтобы пометить что было сделано (удалено / в архив / добавлено в пул)

## Порядок реализации

Реализую в таком порядке, после каждого шага — smoke-test:

1. **`policy.py`** — самостоятельный модуль, легко протестировать на синтетических dict'ах.
2. **`db.py`** — добавить `get_archive_category_id`, `move_key`, `get_key_by_string`, `find_replacement`, `find_category_by_name`.
3. **`main_window.py`** — интегрировать policy в `_on_one_done` (автоудаление/архив).
4. **`main_window.py`** — автопроверка при `_add_keys`.
5. **`quick_check.py`** — интеграция с БД (умное поведение).
6. **`quick_check.py`** — автозамена (UI + сигнал).
7. UX полировка: статус-сообщения, опционально галочка «Показать архив».

## Тесты (после реализации)

Запустить вручную:
```bash
cd ~/Applications/work_tool/keystore
python3 -c "
import sys; sys.path.insert(0, '.')
from keystore import policy
from keystore.db import DB
# ... в самой реализации интеграционный тест прогнан, см. summary в чате
"
```

Что протестировано:
- ✓ `policy.classify()` — 14 кейсов
- ✓ `policy.category_for_description()` — 8 кейсов  
- ✓ Retail-блок → удаление из БД
- ✓ MAK-блок → перемещение в архив (cat_id меняется)
- ✓ Чужой живой → маппится в `Windows Pro Online` / `Windows Pro Phone` / `Office 24 PP Phone` и т.п.

## Известные ограничения

- Маппинг `description → category` — жёсткий, в коде (`policy.category_for_description`). Если у пользователя категории называются иначе или появляется новый продукт — надо править функцию.
- При автодобавлении ключа в чужую категорию, если категория не существует — ключ пропускается. Можно потом добавить автосоздание категории или Inbox.
- Замена при автозамене ищется по точному совпадению `description`. Для разных типов активации (Phone vs Online) `description` может отличаться — это правильно, не путаем.
- Клоны (recode) обрабатываются как обычные ключи. Если родитель-MAK уехал в архив, его клоны останутся пока их не проверишь — тогда они тоже уедут. Это норма: каждый clone получит тот же ответ от MS и обработается по policy одинаково.

## Что НЕ делаю

- Не делаю настройки в JSON-файле — пока константы в коде. Когда станет нужно — добавим.
- Не делаю прогресс-бары / красивые анимации — сосредоточен на функциональности.
- Не трогаю стили / иконки.
- Не трогаю Chrome-расширение и сервер 17777 — они работают, их не касаемся.
