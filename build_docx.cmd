@echo off
rem Thin wrapper for cmd.exe / PowerShell. The real logic lives in paperkit.py.
setlocal
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%~dp0paperkit.py" build %*
) else (
  python "%~dp0paperkit.py" build %*
)
