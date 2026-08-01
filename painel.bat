@echo off
REM Abre o painel de configuracao no navegador.
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m tools.painel
) else (
  python -m tools.painel
)
pause
