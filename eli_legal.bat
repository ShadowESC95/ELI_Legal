@echo off
rem Start ELI Legal. With no arguments it opens the desktop application.
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (set PY=.venv\Scripts\python.exe) else (set PY=python)
%PY% -m eli_legal %*
