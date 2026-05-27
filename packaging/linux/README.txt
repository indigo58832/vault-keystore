Vault — portable-сборка для Linux
=================================

Содержимое папки:
  VaultLauncher   — запускает сервер проверки и GUI одним кликом
  Vault           — основное приложение (склад ключей)
  KeyCheckerServer — локальный сервер проверки (:17777)

Первый запуск
-------------
1. Установи Wine 32-bit (нужен для pidgenx / MAK count):
     sudo dpkg --add-architecture i386
     sudo apt update
     sudo apt install wine32 winbind xclip wmctrl

2. Один раз настрой Wine prefix:
     WINEPREFIX=~/.wine32 WINEARCH=win32 winecfg

3. Запусти:
     ./VaultLauncher

   Или только GUI (если сервер уже запущен):
     ./Vault

Зависимости GUI (обычно уже есть в Ubuntu/KDE/GNOME):
  libxcb-cursor0 libxkbcommon-x11-0 libgl1

База данных
-----------
~/.local/share/keystore/keys.db — та же, что при запуске через python.

Логи
----
/tmp/winkeycheck.log — сервер проверки
~/vault_server_error.log — ошибки winkeycheck

Hotkey Ctrl+Shift+S
-------------------
Если pynput не зарегистрировал hotkey — назначь в настройках GNOME/KDE
команду на ./Vault --quick-check (или через show_or_start.sh из исходников).
