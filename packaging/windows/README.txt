Vault для Windows — один файл
===============================

Запуск: двойной клик Vault.exe

В папке должны быть:
  Vault.exe
  Diagnose.bat   (если что-то не работает)
  README.txt

НЕ кладите рядом:
  KeyCheckerServer.exe
  VaultLauncher.exe

Если «не открывается»:
  1. Диспетчер задач — завершить все Vault.exe
  2. Снова Vault.exe — подождите до 2 минут (первый запуск распаковывается)
  3. Иконка V в трее у часов — ПКМ → Показать
  4. Если пишет «уже запущен» — смотрите трей, не запускайте второй раз

Диагностика (простой путь):
  Двойной клик Diagnose.bat
  В ТОЙ ЖЕ папке появятся:
    vault_diagnose_output.txt
    vault_diagnose.json
  Откройте и пришлите vault_diagnose_output.txt

Также после запуска Vault:
    vault_startup.log  (в этой же папке)

База ключей:
  C:\Users\<имя>\.local\share\keystore\keys.db

Сборка: GitHub Actions → VaultPortable-windows (не zip от 19 мая).
В заголовке окна: Vault [номер-сборки] — без номера = старый exe.
