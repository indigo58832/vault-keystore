@echo off
setlocal
cd /d "%~dp0"

start "" /min "%~dp0KeyCheckerServer\KeyCheckerServer.exe" --port 17777
timeout /t 2 /nobreak >nul
start "" "%~dp0Vault\Vault.exe"
