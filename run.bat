@echo off
chcp 65001 > nul
title Bot de Gerenciamento do Telegram
echo ============================================================
echo Iniciando o Bot do Telegram...
echo ============================================================
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Criando ambiente virtual...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)

python main.py
pause
