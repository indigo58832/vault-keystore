@echo off
cd /d "%~dp0"
echo Running Vault diagnose...
Vault.exe --diagnose
echo.
echo Report: %USERPROFILE%\.local\share\keystore\vault_diagnose.json
pause
