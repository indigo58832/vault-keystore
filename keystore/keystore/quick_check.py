"""Быстрое окно проверки ключа.

Запуск:
    python3 -m keystore.quick_check

Что делает:
1. Читает текст из X11 PRIMARY selection (то что у тебя выделено на экране).
2. Находит ключи XXXXX-XXXXX-XXXXX-XXXXX-XXXXX через regex.
3. Если нашёл — сразу проверяет через локальный сервер 17777, показывает результат.
4. Если не нашёл — поле для ручного ввода. Ctrl+Enter / кнопка → проверка.

Окно компактное, поверх всего, исчезает по Esc или клику вне окна.
"""
from __future__ import annotations
import sys, os, re, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QGuiApplication, QShortcut, QKeySequence, QIcon
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit,
    QPushButton, QLabel, QScrollArea,
)

from keystore.checker import CheckerClient
from keystore.app import ICON_PATH, ensure_checker_server_running
from keystore.db import DB
from keystore import policy
from keystore import paths

KEY_RE = re.compile(r"[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}")


def get_x11_selection() -> str:
    """Берём текст из PRIMARY selection (Linux/X11) либо из обычного clipboard
    (Windows/macOS — там понятия PRIMARY selection нет).
    Если ничего нет — пустая строка."""
    # На Linux пробуем xclip/xsel — это PRIMARY (то что выделено, без Ctrl+C)
    if sys.platform.startswith("linux"):
        for tool, args in [
            ("xclip", ["-o", "-selection", "primary"]),
            ("xsel", ["-p"]),
        ]:
            try:
                r = subprocess.run([tool] + args, capture_output=True, timeout=2)
                if r.returncode == 0 and r.stdout:
                    return r.stdout.decode(errors="ignore")
            except Exception:
                pass
        return ""
    # На Windows/macOS — обычный clipboard
    try:
        return QGuiApplication.clipboard().text() or ""
    except Exception:
        return ""


class CheckWorker(QThread):
    """Проверка + умные действия с БД:
    - мёртвый ключ из нашего пула → удалить (или в архив если MAK)
    - чужой живой ключ → добавить в подходящую категорию
    - мёртвый из нашего пула → найти замену (alive из БД) и выдать пользователю
    """
    one_done = pyqtSignal(dict, dict)               # (result, action_dict)
    replacement_found = pyqtSignal(dict, dict, str)  # (dead_result, alive_result, replacement_key_str)
    finished_all = pyqtSignal()

    def __init__(self, keys: list[str], consume: bool = True):
        super().__init__()
        self.keys = keys
        self.consume = consume
        self.client = CheckerClient()
        # DB не создаём здесь — SQLite не любит когда коннект перебегает между потоками.
        # Создаём её в run() уже внутри worker-потока.
        self.db: DB | None = None

    def run(self):
        # SQLite connection должен жить в том же потоке где используется.
        self.db = DB()
        for k in self.keys:
            existing = self.db.get_key_by_string(k)

            # Quick Check — это РУЧНАЯ проверка из чата с покупателем.
            # Пользователь сам решает что проверяет (обычно Phone-товары).
            # Поэтому всегда полный режим: consume + точные коды ошибок.
            # Защита Retail/OEM от автоматических потерь работает на массовой проверке
            # (где она по категории), а тут — ответственность на пользователе.
            try:
                r = self.client.check(k, online=True, mak_count=True,
                                      consume=self.consume,
                                      allow_consume_retail=True)
            except Exception as e:
                r = {"key": k, "ok": False, "error": str(e)}

            action = policy.classify(r, in_pool=bool(existing))

            archive_id = self.db.get_archive_category_id()
            # Защита: проданные и архивные не трогаем автоматически
            skip_auto = bool(existing) and (
                existing.status == "sold" or existing.category_id == archive_id
            )

            # Применяем действие из policy
            if existing:
                try:
                    self.db.update_check_result(existing.id, r)
                except Exception:
                    pass
                if not skip_auto:
                    if action.kind == "delete":
                        self.db.delete_keys([existing.id])
                    elif action.kind == "archive":
                        self.db.move_key(existing.id, archive_id)
            # Чужие ключи в пул автоматически не добавляем — пользователь сам решает.

            # Передаём UI основной результат + action для пометки в карточке
            self.one_done.emit(r, action.__dict__)

            # Когда искать замену:
            # - 003 / 004 / 006 / 060 — реально мёртв (отозван/блок) → замена.
            # - 020 (MAK DMAK limit) → если ключ продан как Online и онлайн квота
            #   закончилась, покупателю нужна замена. По умолчанию ищем.
            # - 008 (Retail unlock exceeded) → ключ ещё рабочий по телефону, замена
            #   не нужна. Пропускаем.
            code = (r.get("online_code") or "").upper().replace("0X", "0x")
            is_dead = code in policy.BLOCKED_CODES or code == "0xC004C020"
            if is_dead:
                exclude_id = existing.id if existing else None
                # Перебираем кандидатов — некоторые могут быть «unknown» и реально мёртвыми.
                # Берём по очереди, проверяем через MS, мёртвых сразу удаляем из БД.
                candidates = self.db.find_replacements_all(
                    r.get("description"), exclude_key_id=exclude_id, limit=10
                )
                found_alive = False
                for cand in candidates:
                    try:
                        rcheck = self.client.check(
                            cand.key, online=True, mak_count=True, consume=self.consume,
                        )
                    except Exception as e:
                        rcheck = {"key": cand.key, "ok": False, "error": str(e)}
                    # сохраним результат в БД (статус обновится)
                    try:
                        self.db.update_check_result(cand.id, rcheck)
                    except Exception:
                        pass
                    # жив ли?
                    repl_action = policy.classify(rcheck, in_pool=True)
                    if repl_action.kind == "keep":
                        self.replacement_found.emit(r, rcheck, cand.key)
                        found_alive = True
                        break
                    # мёртвый — применим policy (удалим Retail / архивируем MAK)
                    if repl_action.kind == "delete":
                        self.db.delete_keys([cand.id])
                    elif repl_action.kind == "archive":
                        self.db.move_key(cand.id, self.db.get_archive_category_id())
                if not found_alive:
                    # nothing more to do — UI просто покажет основной результат без замены
                    pass

        self.finished_all.emit()


_ACTION_LABELS = {
    "delete":      ("🗑", "#fca5a5", "удалён из пула"),
    "archive":     ("📦", "#fcd34d", "перемещён в архив"),
    "keep":        ("",   "",        ""),
    "skip":        ("",   "",        ""),
}


def render_result(r: dict, action: dict | None = None) -> str:
    """HTML-карточка результата + пометка что сделала программа с ключом."""
    if not r.get("ok"):
        return (
            f'<div style="margin:6px 0;padding:8px;background:#5b1d1d;color:#fca5a5;'
            f'border-radius:4px;"><b>{r.get("key","?")}</b><br>'
            f'{r.get("error","не удалось определить")}</div>'
        )
    rows = []
    # ключ — кликабельный (клик копирует в буфер)
    rows.append(
        f'<a href="copy:{r["key"]}" style="font-family:monospace;font-weight:600;'
        f'color:#fff;text-decoration:none;">{r["key"]}</a>'
    )
    rows.append(f'<div style="color:#ccc;">{r.get("description") or r.get("type_label") or ""}</div>')
    if r.get("is_mak") and r.get("mak_count") is not None:
        rows.append(f'<div style="color:#fcd34d;font-weight:600;">MAK Count: {r["mak_count"]}</div>')
    if r.get("online_ok") is True:
        rows.append('<div style="color:#6ee7b7;">✓ Online-valid</div>')
    elif r.get("online_ok") is False:
        human = r.get("online_human") or r.get("online_message") or "ошибка"
        code = r.get("online_code") or ""
        rows.append(f'<div style="color:#fca5a5;">✗ {human}</div>')
        if code and code != "0x0":
            rows.append(f'<div style="color:#fca5a5;font-family:monospace;font-size:12px;">{code}</div>')

    if action:
        kind = action.get("kind", "")
        icon, color, label = _ACTION_LABELS.get(kind, ("", "", ""))
        if label:
            text = f"{icon} {label}"
            rows.append(f'<div style="color:{color};margin-top:4px;font-size:12px;">{text}</div>')

    body = "<br>".join(rows)
    return f'<div style="margin:6px 0;padding:8px;background:#2a2a2a;border-radius:4px;border-left:3px solid #2563eb;">{body}</div>'


def render_replacement(dead_result: dict, alive_result: dict, repl_key: str) -> str:
    """Блок-замена. Только ключ, без подписей. Клик копирует."""
    return (
        '<div style="margin:6px 0;padding:8px;background:#0f3024;border-radius:4px;'
        'border-left:3px solid #10b981;">'
        f'<a href="copy:{repl_key}" style="font-family:monospace;font-weight:600;'
        f'color:#fff;text-decoration:none;font-size:14px;">{repl_key}</a>'
        '</div>'
    )


class QuickCheckWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Vault — быстрая проверка  [{paths.build_id()}]")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(460, 380)
        if os.path.exists(ICON_PATH):
            self.setWindowIcon(QIcon(ICON_PATH))

        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)

        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("Вставь ключ или несколько (или выдели на экране и вызови ещё раз)")
        self.input.setMaximumHeight(80)
        v.addWidget(self.input)

        btn_row = QHBoxLayout()
        self.btn_check = QPushButton("Проверить")
        self.btn_check.clicked.connect(self._do_check)
        btn_row.addWidget(self.btn_check)

        self.btn_copy_repl = QPushButton("Скопировать замену")
        self.btn_copy_repl.clicked.connect(self._copy_replacement)
        self.btn_copy_repl.setStyleSheet("background:#10b981;")
        self.btn_copy_repl.setVisible(False)
        btn_row.addWidget(self.btn_copy_repl)
        v.addLayout(btn_row)

        # буфер ключей-замен (заполняется через сигнал replacement_found)
        self._replacements: list[str] = []

        self.status = QLabel("")
        self.status.setStyleSheet("color:#93c5fd; font-size:12px;")
        v.addWidget(self.status)

        self.results = QLabel("")
        self.results.setTextFormat(Qt.TextFormat.RichText)
        self.results.setWordWrap(True)
        self.results.setAlignment(Qt.AlignmentFlag.AlignTop)
        # клик по ссылке внутри label = копирование в буфер
        self.results.setOpenExternalLinks(False)
        self.results.linkActivated.connect(self._on_link_clicked)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.results)
        v.addWidget(scroll, 1)

        # тёмная тема
        self.setStyleSheet("""
            QWidget { background: #1e1e1e; color: #e6e6e6; font-size:13px; }
            QPlainTextEdit { background: #2a2a2a; border: 1px solid #3a3a3a; padding: 4px; font-family: monospace; }
            QPushButton { background: #2563eb; color: white; padding: 6px 10px; border: none; border-radius:4px; }
            QPushButton:hover { background: #1d4ed8; }
            QPushButton:disabled { background: #555; }
            QScrollArea { border: none; }
        """)

        # шорткаты
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._do_check)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self._do_check)
        QShortcut(QKeySequence("Escape"), self, activated=self.close)

        self._refresh_server_hint()

        # Приоритет — выделенный текст (X11 PRIMARY)
        sel = get_x11_selection()
        if sel:
            self.input.setPlainText(sel)
            if KEY_RE.search(sel.upper()):
                QTimer.singleShot(100, self._do_check)

    def _refresh_server_hint(self):
        info = CheckerClient().health_info() or {}
        n = int(info.get("pkeyconfigs_loaded") or 0)
        if n > 0:
            self.status.setText(f"Сервер OK, pkeyconfig: {n}")
            self.status.setStyleSheet("color:#4ade80; font-size:12px;")
        else:
            roots = info.get("bundle_roots") or []
            self.status.setText(
                f"Сервер без pkeyconfig (0). build={paths.build_id()} "
                f"roots={roots!r}"
            )
            self.status.setStyleSheet("color:#fbbf24; font-size:12px;")

    def _do_check(self):
        text = self.input.toPlainText()
        text_up = text.upper()
        keys = list(dict.fromkeys(KEY_RE.findall(text_up)))

        if not keys:
            self.status.setText("В тексте не нашёл ни одного ключа.")
            self.results.setText("")
            return

        self.status.setText(f"Проверяю {len(keys)} ключ(а)…")
        self.results.setText("")
        self.btn_check.setEnabled(False)

        self._buf = []
        self._replacements: list[str] = []
        # NB: consume будет автоматически проигнорирован сервером для Retail/OEM
        self.worker = CheckWorker(keys, consume=True)
        self.worker.one_done.connect(self._on_one)
        self.worker.replacement_found.connect(self._on_replacement)
        self.worker.finished_all.connect(self._on_done)
        self.worker.start()

    def _on_one(self, result: dict, action: dict):
        self._buf.append(render_result(result, action))
        self.results.setText("\n".join(self._buf))

    def _on_replacement(self, dead_result: dict, alive_result: dict, repl_key: str):
        self._buf.append(render_replacement(dead_result, alive_result, repl_key))
        self.results.setText("\n".join(self._buf))
        self._replacements.append(repl_key)
        # обновим кнопку «Скопировать замену» если она есть
        self._refresh_replacement_button()

    def _refresh_replacement_button(self):
        if hasattr(self, "btn_copy_repl"):
            self.btn_copy_repl.setVisible(bool(self._replacements))
            if self._replacements:
                self.btn_copy_repl.setText(f"Скопировать замену{' (' + str(len(self._replacements)) + ')' if len(self._replacements) > 1 else ''}")

    def _on_link_clicked(self, url: str):
        """Клик по «ссылке» в карточке — копирует значение в буфер обмена.
        Формат: copy:<значение>
        """
        if url.startswith("copy:"):
            value = url[5:]
            QGuiApplication.clipboard().setText(value)
            self.status.setText(f"✓ Скопировано: {value}")

    def _copy_replacement(self):
        if self._replacements:
            # копируем последнюю найденную (наиболее свежий запрос)
            QGuiApplication.clipboard().setText("\n".join(self._replacements))
            self.status.setText(f"Замена скопирована в буфер.")

    def _on_done(self):
        self.status.setText("Готово.")
        self.btn_check.setEnabled(True)


def main():
    ensure_checker_server_running()
    app = QApplication.instance() or QApplication(sys.argv)
    win = QuickCheckWindow()
    win.show()
    win.raise_()
    win.activateWindow()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
