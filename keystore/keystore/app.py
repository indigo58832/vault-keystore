"""Точка входа: запускает Qt-приложение, трей-иконку и глобальный hotkey."""
from __future__ import annotations
import sys
import os
import signal

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QIcon, QAction, QPixmap, QPainter, QFont, QColor
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox

from .main_window import MainWindow
from . import auto_check


import os as _os

ICON_PATH = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                         "icons", "logos", "logo1_v_minimal.png")


def make_tray_icon(size: int = 64) -> QIcon:
    """Иконка Vault — берём готовый PNG со склада."""
    if _os.path.exists(ICON_PATH):
        return QIcon(ICON_PATH)
    # fallback — простой квадрат
    pm = QPixmap(size, size)
    pm.fill(QColor("#1e293b"))
    return QIcon(pm)


class HotkeyBridge(QObject):
    """Мостик из pynput-потока в Qt main thread."""
    triggered = pyqtSignal()


def setup_global_hotkey(bridge: HotkeyBridge, combo: str = "<ctrl>+<alt>+k") -> object | None:
    """Запускает pynput.GlobalHotKeys в фоне.
    Возвращает listener или None если не получилось.
    """
    try:
        from pynput import keyboard
    except Exception as e:
        print(f"[KeyStore] pynput недоступен: {e}", file=sys.stderr)
        return None

    def on_activate():
        bridge.triggered.emit()

    try:
        listener = keyboard.GlobalHotKeys({combo: on_activate})
        listener.daemon = True
        listener.start()
        print(f"[KeyStore] глобальный hotkey: {combo}", file=sys.stderr)
        return listener
    except Exception as e:
        print(f"[KeyStore] не удалось зарегистрировать hotkey: {e}", file=sys.stderr)
        return None


import tempfile
VAULT_PID_FILE = os.path.join(tempfile.gettempdir(), "vault.pid")


def _already_running() -> bool:
    """Проверка single-instance: уже ли запущен Vault?
    Если pid-файл существует и процесс жив — да, не запускаем второй.
    Кроссплатформенно: os.kill(pid, 0) работает на Linux/macOS/Windows.
    """
    try:
        with open(VAULT_PID_FILE) as f:
            pid = int(f.read().strip())
        try:
            os.kill(pid, 0)  # на всех платформах: ошибка если процесса нет
            return True
        except OSError:
            return False
    except (FileNotFoundError, ValueError):
        return False


def _write_pid_file():
    try:
        with open(VAULT_PID_FILE, "w") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass


def _remove_pid_file():
    try:
        os.unlink(VAULT_PID_FILE)
    except Exception:
        pass


def main():
    # Single-instance: если Vault уже запущен — молча выходим.
    # Чтобы открыть окно — пользователь использует трей или хоткей.
    if _already_running():
        print(f"[Vault] уже запущен — выхожу. PID-файл: {VAULT_PID_FILE}",
              file=sys.stderr)
        return

    # Ctrl-C в терминале закрывает приложение
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # окно можно закрыть, программа жива в трее

    # Связь с .desktop-файлом → GNOME покажет иконку Vault в доке/панели,
    # а не дефолтную шестерёнку.
    app.setApplicationName("Vault")
    app.setApplicationDisplayName("Vault")
    app.setDesktopFileName("keystore")  # имя .desktop без расширения

    _write_pid_file()
    app.aboutToQuit.connect(_remove_pid_file)

    icon = make_tray_icon()
    app.setWindowIcon(icon)

    win = MainWindow()
    win.setWindowIcon(icon)

    def show_window():
        win.showNormal()
        win.raise_()
        win.activateWindow()

    def hide_window():
        win.hide()

    def quit_app():
        app.quit()

    # tray
    tray = QSystemTrayIcon(icon)
    tray.setToolTip("Vault — Ctrl+Alt+K чтобы показать")
    menu = QMenu()
    a_show = QAction("Показать")
    a_show.triggered.connect(show_window)
    menu.addAction(a_show)
    a_hide = QAction("Скрыть")
    a_hide.triggered.connect(hide_window)
    menu.addAction(a_hide)
    menu.addSeparator()

    # ── Автопроверка ────────────────────────────────────────────────
    # Каждые 24 часа: проверяем только Phone-категории через Consume.
    # Online/Archive не трогаем — финансовый риск ложного удаления.
    auto_worker: auto_check.AutoCheckWorker | None = None

    def start_auto_check():
        nonlocal auto_worker
        if auto_worker is not None and auto_worker.isRunning():
            return
        auto_worker = auto_check.AutoCheckWorker()
        auto_worker.finished_run.connect(_on_auto_check_done)
        auto_worker.start()
        tray.showMessage("Vault", "Автопроверка началась",
                         QSystemTrayIcon.MessageIcon.Information, 3000)

    def _on_auto_check_done(stats: dict):
        if stats.get("error") == "server_offline":
            tray.showMessage("Vault", "Автопроверка не сработала: сервер не отвечает.",
                             QSystemTrayIcon.MessageIcon.Warning, 5000)
        else:
            msg = (f"Автопроверка: проверено {stats.get('checked', 0)}, "
                   f"удалено {stats.get('deleted', 0)}, "
                   f"в архив {stats.get('archived', 0)}")
            tray.showMessage("Vault", msg, QSystemTrayIcon.MessageIcon.Information, 5000)
        # Будим воркер заново через 24 ч.
        QTimer.singleShot(auto_check.INTERVAL_SECONDS * 1000, start_auto_check)

    a_check_now = QAction("Проверить сейчас")
    a_check_now.triggered.connect(start_auto_check)
    menu.addAction(a_check_now)
    menu.addSeparator()

    a_quit = QAction("Выйти")
    a_quit.triggered.connect(quit_app)
    menu.addAction(a_quit)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: show_window() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
    tray.show()

    # global hotkey
    bridge = HotkeyBridge()
    bridge.triggered.connect(show_window)
    listener = setup_global_hotkey(bridge, "<ctrl>+<alt>+k")
    if listener is None:
        # tray всё равно работает, hotkey можно настроить в GNOME shortcuts
        tray.showMessage(
            "KeyStore",
            "Hotkey недоступен. Используй трей или назначь /run-keystore на клавишу в GNOME.",
            QSystemTrayIcon.MessageIcon.Information, 5000,
        )

    # Планируем автопроверку.
    # Если последний прогон был >= 24h назад — запустим скоро (через минуту).
    # Иначе — досчитаем оставшееся время.
    delay_ms = auto_check.seconds_until_next_run() * 1000
    QTimer.singleShot(delay_ms, start_auto_check)

    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
