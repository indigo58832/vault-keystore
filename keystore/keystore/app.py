"""Точка входа: запускает Qt-приложение, трей-иконку и глобальный hotkey."""
from __future__ import annotations
import sys
import os
import signal
import subprocess

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QIcon, QAction, QPixmap, QPainter, QFont, QColor
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox

from .main_window import MainWindow
from . import auto_check
from . import paths
from .server_boot import ensure_checker_server_running as boot_checker_server


ICON_PATH = paths.icon_path()


def make_tray_icon(size: int = 64) -> QIcon:
    """Иконка Vault — берём готовый PNG со склада."""
    if os.path.exists(ICON_PATH):
        return QIcon(ICON_PATH)
    # fallback — простой квадрат
    pm = QPixmap(size, size)
    pm.fill(QColor("#1e293b"))
    return QIcon(pm)


class HotkeyBridge(QObject):
    """Мостик из pynput-потока в Qt main thread."""
    triggered = pyqtSignal()


def setup_global_hotkey(bridge: HotkeyBridge, combo: str = "<ctrl>+<shift>+s") -> object | None:
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
QUICK_CHECK_PID_FILE = os.path.join(tempfile.gettempdir(), "vault_quick_check.pid")
CHECKER_LOG_FILE = os.path.join(tempfile.gettempdir(), "winkeycheck.log")


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


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_quick_check_pid() -> int | None:
    try:
        with open(QUICK_CHECK_PID_FILE) as f:
            return int(f.read().strip())
    except Exception:
        return None


def _write_quick_check_pid(pid: int):
    try:
        with open(QUICK_CHECK_PID_FILE, "w") as f:
            f.write(str(pid))
    except Exception:
        pass


def _remove_quick_check_pid():
    try:
        os.unlink(QUICK_CHECK_PID_FILE)
    except Exception:
        pass


def toggle_quick_check() -> bool:
    """Открыть/закрыть окно быстрой проверки отдельным процессом."""
    old_pid = _read_quick_check_pid()
    if old_pid and _pid_alive(old_pid):
        try:
            os.kill(old_pid, signal.SIGTERM)
        except OSError:
            pass
        _remove_quick_check_pid()
        return False

    creationflags = 0
    popen_kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
        "cwd": paths.app_dir(),
    }
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        popen_kwargs["start_new_session"] = True

    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--quick-check"]
    else:
        cmd = [sys.executable, "-m", "keystore", "--quick-check"]

    proc = subprocess.Popen(cmd, creationflags=creationflags, **popen_kwargs)
    _write_quick_check_pid(proc.pid)
    return True


def ensure_checker_server_running() -> bool:
    return boot_checker_server(
        server_binary=paths.server_binary(),
        server_dev_script=paths.server_dev_script(),
        log_file=CHECKER_LOG_FILE,
        is_frozen=paths.is_frozen(),
    )


def main():
    # Single-instance: если Vault уже запущен — молча выходим.
    # Чтобы открыть окно — пользователь использует трей или хоткей.
    if _already_running():
        print(f"[Vault] уже запущен — выхожу. PID-файл: {VAULT_PID_FILE}",
              file=sys.stderr)
        return

    # Ctrl-C в терминале закрывает приложение
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    server_ok = ensure_checker_server_running()

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
    tray.setToolTip("Vault — Ctrl+Shift+S: быстрая проверка")
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

    if not server_ok:
        tray.showMessage(
            "Vault",
            "Сервер проверки ключей не запустился (:17777). "
            "Проверка и Quick Check работать не будут.",
            QSystemTrayIcon.MessageIcon.Critical,
            8000,
        )
    elif paths.is_frozen() and os.path.isfile(paths.server_binary()):
        tray.showMessage(
            "Vault",
            "Рядом лежит старый KeyCheckerServer.exe — удалите его. "
            "Нужен только Vault.exe, иначе проверка может не работать.",
            QSystemTrayIcon.MessageIcon.Warning,
            10000,
        )

    # global hotkey
    bridge = HotkeyBridge()
    bridge.triggered.connect(toggle_quick_check)
    listener = setup_global_hotkey(bridge, "<ctrl>+<shift>+s")
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
