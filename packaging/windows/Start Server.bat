@echo off
setlocal
cd /d "%~dp0"

"%~dp0KeyCheckerServer\KeyCheckerServer.exe" --port 17777
