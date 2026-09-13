@echo off
chcp 65001 >nul
title Tro ly ao tieng Viet v6.3
cd /d "%~dp0"

REM ============================================================
REM  CHAY NGAY - khong can cai dat bat cu thu vien nao
REM  Chuong trinh tu dung lite_model.py (thuan Python, ~97-98%%)
REM ============================================================

where python >nul 2>&1
if errorlevel 1 (
    echo [LOI] Khong tim thay Python trong PATH.
    echo       Tai Python 3.12 tai https://www.python.org/downloads/
    echo       va nho tich "Add python.exe to PATH" khi cai.
    pause
    exit /b 1
)

if exist ".venv\Scripts\activate.bat" call .venv\Scripts\activate.bat

python main.py %*

echo.
pause
