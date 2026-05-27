@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo === Vault diagnose ===
echo Folder: %CD%
echo.
if not exist "Vault.exe" (
  echo ERROR: Vault.exe not found in this folder.
  pause
  exit /b 1
)
Vault.exe --diagnose > "%CD%\vault_diagnose_output.txt" 2>&1
echo.
echo Done. Files in THIS folder:
echo   vault_diagnose_output.txt
echo   vault_diagnose.json
echo.
if exist "%CD%\vault_diagnose.json" type "%CD%\vault_diagnose.json"
echo.
notepad "%CD%\vault_diagnose_output.txt"
pause
