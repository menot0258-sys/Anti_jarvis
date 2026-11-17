@echo off
cd /d "%~dp0"
where python >nul 2>nul && (python server.py & goto end)
where py >nul 2>nul && (py server.py & goto end)
echo Python 3 not found. Install it from https://python.org and tick "Add to PATH".
:end
pause
