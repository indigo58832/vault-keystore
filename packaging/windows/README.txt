Vault для Windows
=================

Запуск: двойной клик Vault.exe (или Start Vault.bat)

НОВЫЙ ПОДХОД (2026-05):
  - проверка ключей ВНУТРИ Vault.exe
  - без сервера localhost:17777
  - без KeyCheckerServer.exe

В папке лежит каталог Vault/ — не удаляйте файлы рядом с exe.

Первый запуск: подождите ~1 мин (загрузка базы ключей в фоне).
Внизу окна: зелёная «● проверка» = можно проверять.

Диагностика: Diagnose.bat → vault_diagnose_output.txt в этой папке.

База keys.db:
  C:\Users\<имя>\.local\share\keystore\keys.db

С Linux: скопируйте keys.db в эту папку.
