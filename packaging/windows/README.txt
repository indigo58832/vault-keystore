Vault для Windows — один файл
===============================

Запускайте ТОЛЬКО Vault.exe (двойной клик).

Внутри уже есть:
  - интерфейс склада ключей
  - сервер проверки ключей (localhost:17777)

НЕ кладите рядом старые файлы:
  KeyCheckerServer.exe
  VaultLauncher.exe
Они мешают — Vault подключится к пустому серверу.

База ключей:
  C:\Users\<имя>\.local\share\keystore\keys.db

С Linux скопируйте keys.db в эту папку (создайте каталог keystore если нет).

Quick Check: Ctrl+Shift+S (или Ctrl+C + hotkey).

Если пишет «pkeyconfig» или «0 конфигов»:
  1. Закройте Vault и KeyCheckerServer в диспетчере задач
  2. Удалите KeyCheckerServer.exe из папки (оставьте только Vault.exe)
  3. Запустите Vault.exe снова, подождите 30 сек
  4. Индикатор «сервер» внизу должен быть зелёным

Скачивайте сборку из GitHub Actions (артефакт VaultPortable-windows),
не старый zip от 19 мая.
