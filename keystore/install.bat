@echo off
REM Установка зависимостей Vault на Windows
REM Требуется Python 3.11+ (https://www.python.org/downloads/) с галкой "Add to PATH"

echo === Vault: установка зависимостей ===
echo.

REM Проверка Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [!] Python не найден. Скачай его на https://www.python.org/downloads/
    echo [!] При установке поставь галку "Add Python to PATH".
    pause
    exit /b 1
)

echo Python OK.
echo.
echo Ставлю pyqt6, requests, pynput, urllib3...
python -m pip install --upgrade pip
python -m pip install PyQt6 requests pynput urllib3
if errorlevel 1 (
    echo [!] Ошибка установки зависимостей.
    pause
    exit /b 1
)

echo.
echo === Готово! ===
echo Запускай Vault через start.bat.
echo Перед этим запусти winkeycheck\server.py в отдельном окне (см. README).
pause
