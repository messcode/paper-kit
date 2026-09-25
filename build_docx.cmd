@echo off
rem Thin wrapper for cmd.exe / PowerShell. The real logic lives in paperkit.py.
setlocal
if not defined JOURNAL set "JOURNAL=nature"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%~dp0paperkit.py" --journal %JOURNAL% build %*
) else (
  python "%~dp0paperkit.py" --journal %JOURNAL% build %*
)
