@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title Cai dat GIONG NOI (TTS + STT) - Tro ly ao tieng Viet v6.3
cd /d "%~dp0"

REM ============================================================
REM  CAI TUNG GOI MOT - mot goi loi KHONG lam hong ca lenh
REM  KHONG cai pyaudio (hay loi build tren Windows) -> dung sounddevice
REM ============================================================

where python >nul 2>&1
if errorlevel 1 (
    echo [LOI] Khong tim thay Python trong PATH.
    echo       Tai Python 3.12 tai https://www.python.org/downloads/
    pause
    exit /b 1
)

echo.
echo ============================================================
python --version
echo ============================================================

if not exist ".venv" (
    echo [1/3] Tao moi truong ao .venv...
    python -m venv .venv
)
call .venv\Scripts\activate.bat

echo.
echo [2/3] Nang cap pip...
python -m pip install --upgrade pip setuptools wheel

echo.
echo [3/3] Cai tung goi mot...
echo.

set OK_LIST=
set FAIL_LIST=

call :install pyttsx3            "Doc tieng Viet offline (TTS)"
call :install SpeechRecognition  "Nhan dien giong noi qua Google"
call :install sounddevice        "Thu am tu micro - THAY THE pyaudio"
call :install numpy              "Bat buoc di kem sounddevice"
call :install rapidfuzz          "So khop mo ten app/web/file"
call :install pytest             "Chay bo unit test"
call :install gTTS               "Giong Viet tu nhien nhat (can internet)"
call :install comtypes           "Dieu khien am luong chinh xac"
call :install pycaw              "Dieu khien am luong chinh xac"

echo.
echo ============================================================
echo  KET QUA
echo ============================================================
echo  Thanh cong : !OK_LIST!
if defined FAIL_LIST (
    echo  That bai   : !FAIL_LIST!
    echo.
    echo  Cac goi that bai deu la TUY CHON - chuong trinh van chay binh thuong.
) else (
    echo  That bai   : ^(khong co^)
)
echo.
echo  LUU Y: KHONG cai pyaudio. Du an dung sounddevice de thu am
echo         ^(xem stt.py, ham _record^). sounddevice co san PortAudio
echo         nen khong can trinh bien dich C++.
echo ============================================================

echo.
echo Kiem tra tinh nang dang bat...
python -c "import platform_utils; platform_utils.print_feature_report()" 2>nul
python main.py --version

echo.
echo Chay chuong trinh voi giong noi:
echo     .venv\Scripts\activate.bat
echo     python main.py --speak
echo.
pause
exit /b 0

:install
set PKG=%~1
set DESC=%~2
echo ------------------------------------------------------------
echo  Dang cai: %PKG%   (%DESC%)
echo ------------------------------------------------------------
python -m pip install --only-binary=:all: --upgrade %PKG%
if errorlevel 1 (
    echo    [!] Khong co wheel dung san, thu lai cho phep build...
    python -m pip install --upgrade %PKG%
    if errorlevel 1 (
        echo    [X] THAT BAI: %PKG%  -- bo qua, day la goi tuy chon.
        set FAIL_LIST=!FAIL_LIST! %PKG%
        echo.
        exit /b 0
    )
)
echo    [OK] %PKG%
set OK_LIST=!OK_LIST! %PKG%
echo.
exit /b 0
