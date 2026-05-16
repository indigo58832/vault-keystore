@echo off
REM Запуск Vault на Windows. Лог в %TEMP%\keystore.log
cd /d "%~dp0"
start "" pythonw -m keystore >> "%TEMP%\keystore.log" 2>&1
