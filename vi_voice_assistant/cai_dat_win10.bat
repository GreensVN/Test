@echo off
setlocal enabledelayedexpansion
title Cai dat Tro ly ao tieng Viet - tu dong nhan dien Windows

REM ============================================================================
REM  Cai dat tro ly ao tieng Viet tren Windows 7 / 8 / 8.1 / 10 / 11
REM
REM  BAN NANG CAP: file nay KHONG con danh rieng cho Windows 10 nua (ten file
REM  giu nguyen la "cai_dat_win10.bat" de tuong thich voi cac huong dan cu -
REM  vd FIX_LOI_CYTHON_WIN10.txt). Script se TU NHAN DIEN:
REM    - Phien ban Windows that su dang chay (qua registry, khong dung wmic
REM      vi wmic da bi go bo tren mot so ban Windows 11 moi)
REM    - Kien truc CPU (32-bit / 64-bit / ARM64)
REM    - Phien ban Python phu hop nhat dang co san (uu tien qua "py launcher")
REM  roi chon dung nhanh cai dat:
REM    NHANH "win7"    -> bat buoc Python 3.8.x, KHONG doi code page console
REM                        sang UTF-8 (tranh loi treo/im lang da biet tren
REM                        mot so may Windows 7 - xem platform_utils.py).
REM    NHANH "modern"  -> Windows 8/8.1/10/11, uu tien Python moi nhat co san,
REM                        cho phep UTF-8 console.
REM  Ca hai nhanh deu dung chung requirements.txt - file do da tu chon dung
REM  phien ban scikit-learn/joblib theo python_version bang "environment
REM  marker", nen script nay chi can goi dung 1 lenh pip install duy nhat.
REM ============================================================================

cd /d "%~dp0"

echo.
echo ============================================================
echo   BUOC 1/7 - Nhan dien he dieu hanh
echo ============================================================

REM --- Kien truc CPU ---
set "ARCH=32-bit"
if defined PROCESSOR_ARCHITEW6432 set "ARCH=64-bit"
if "%PROCESSOR_ARCHITECTURE%"=="AMD64" set "ARCH=64-bit"
if "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "ARCH=ARM64"

REM --- So build Windows tu registry (tin cay hon wmic, luon co san) ---
set "WIN_BUILD=0"
for /f "tokens=3" %%b in ('reg query "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion" /v CurrentBuildNumber 2^>nul') do set "WIN_BUILD=%%b"

set "WIN_PRODUCT="
for /f "tokens=2,*" %%a in ('reg query "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion" /v ProductName 2^>nul') do set "WIN_PRODUCT=%%b"

set "WIN_LABEL="
set "WIN_GEN="
set "WIN_GEN_UNSURE="

if !WIN_BUILD! GEQ 22000 (
    set "WIN_LABEL=Windows 11"
    set "WIN_GEN=modern"
) else if !WIN_BUILD! GEQ 10240 (
    set "WIN_LABEL=Windows 10"
    set "WIN_GEN=modern"
) else if !WIN_BUILD! GEQ 9600 (
    set "WIN_LABEL=Windows 8.1"
    set "WIN_GEN=modern"
) else if !WIN_BUILD! GEQ 9200 (
    set "WIN_LABEL=Windows 8"
    set "WIN_GEN=modern"
) else if !WIN_BUILD! GEQ 7600 (
    set "WIN_LABEL=Windows 7"
    set "WIN_GEN=win7"
) else (
    if defined WIN_PRODUCT (
        set "WIN_LABEL=!WIN_PRODUCT!"
    ) else (
        set "WIN_LABEL=Windows - khong doc duoc build tu registry"
    )
    set "WIN_GEN=modern"
    set "WIN_GEN_UNSURE=1"
)

echo   He dieu hanh    : !WIN_LABEL!  ^(build !WIN_BUILD!, %ARCH%^)
if defined WIN_PRODUCT echo   Ten day du       : !WIN_PRODUCT!

if "!WIN_GEN!"=="win7" (
    echo   Nhanh cai dat    : WINDOWS 7 - bat buoc Python 3.8.x, khong doi
    echo                      code page console sang UTF-8.
) else if defined WIN_GEN_UNSURE (
    echo   Nhanh cai dat    : khong chac chan doc duoc phien ban that su -
    echo                      dung tam nhanh "hien dai" ^(nhu Windows 10/11^).
) else (
    echo   Nhanh cai dat    : WINDOWS 8 / 8.1 / 10 / 11 - uu tien Python moi
    echo                      nhat dang co, cho phep UTF-8 console.
)

REM Chi doi code page tren nhanh "modern". Tren Windows 7, SetConsoleOutputCP
REM da ghi nhan lam HONG VINH VIEN kha nang ghi console tren mot so may - xem
REM giai thich chi tiet trong platform_utils.py (ham setup_console). Chuong
REM trinh Python cung tu ap dung dung logic nay khi chay that, nen o day chi
REM can dong bo theo cho nhat quan.
if not "!WIN_GEN!"=="win7" chcp 65001 >nul

echo.
echo ============================================================
echo   BUOC 2/7 - Tim phien ban Python phu hop
echo ============================================================

set "PYCMD="
set "PYVER="

if "!WIN_GEN!"=="win7" (
    echo   Windows 7 chi chay duoc voi Python 3.8.x - dang do tim...

    where py >nul 2>&1
    if not errorlevel 1 (
        py -3.8 --version >nul 2>&1
        if not errorlevel 1 set "PYCMD=py -3.8"
    )

    if not defined PYCMD (
        where python >nul 2>&1
        if not errorlevel 1 (
            for /f "tokens=2" %%v in ('python --version 2^>^&1') do set "PYVER=%%v"
            echo !PYVER! | findstr /b /l "3.8." >nul
            if not errorlevel 1 set "PYCMD=python"
        )
    )

    if not defined PYCMD (
        echo.
        echo   [LOI] Khong tim thay Python 3.8.x trong PATH.
        echo         Windows 7 CHI chay duoc voi Python 3.8.x - day la ban
        echo         3.8 cuoi cung con trinh cai .exe chinh thuc ho tro
        echo         Windows 7. Tai tai:
        echo         https://www.python.org/downloads/release/python-3810/
        echo         Nho tich "Add python.exe to PATH" khi cai, roi chay lai
        echo         file nay.
        echo.
        pause
        exit /b 1
    )
) else (
    echo   Dang tim Python moi nhat dang co ^(uu tien 3.13 xuong 3.9^)...

    where py >nul 2>&1
    if not errorlevel 1 (
        for %%v in (3.13 3.12 3.11 3.10 3.9) do (
            if not defined PYCMD (
                py -%%v --version >nul 2>&1
                if not errorlevel 1 set "PYCMD=py -%%v"
            )
        )
        if not defined PYCMD (
            py -3 --version >nul 2>&1
            if not errorlevel 1 set "PYCMD=py -3"
        )
    )

    if not defined PYCMD (
        where python >nul 2>&1
        if not errorlevel 1 set "PYCMD=python"
    )

    if not defined PYCMD (
        echo.
        echo   [LOI] Khong tim thay Python trong PATH.
        echo         Cai Python 3.12 tai https://www.python.org/downloads/
        echo         va nho tich "Add python.exe to PATH".
        echo.
        pause
        exit /b 1
    )
)

echo   [OK] Se dung lenh: !PYCMD!
!PYCMD! --version

echo.
echo ============================================================
echo   BUOC 3/7 - Tao moi truong ao .venv
echo ============================================================
if not exist ".venv" (
    !PYCMD! -m venv .venv
    if errorlevel 1 (
        echo [LOI] Khong tao duoc moi truong ao bang: !PYCMD!
        pause
        exit /b 1
    )
)
call .venv\Scripts\activate.bat

echo.
echo ============================================================
echo   BUOC 4/7 - Nang cap pip / setuptools / wheel
echo ============================================================
python -m pip install --upgrade pip setuptools wheel

echo.
echo ============================================================
echo   BUOC 5/7 - Kiem tra Visual C++ Redistributable
echo ============================================================
if "!WIN_GEN!"=="win7" (
    reg query "HKLM\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\X64" /v Installed >nul 2>&1
    if errorlevel 1 (
        echo   [CANH BAO] Chua thay Microsoft Visual C++ Redistributable
        echo              2015-2022 ^(x64^). numpy/scikit-learn co the bao loi
        echo              "DLL load failed" du pip install khong bao loi gi.
        echo              Tai va cai tai:
        echo              https://aka.ms/vs/17/release/vc_redist.x64.exe
    ) else (
        echo   [OK] Da tim thay Visual C++ Redistributable 2015-2022 ^(x64^).
    )
) else (
    echo   Bo qua - buoc nay chi can thiet tren Windows 7.
)

echo.
echo ============================================================
echo   BUOC 6/7 - Cai thu vien tu requirements.txt
echo              ^(CHI dung wheel dung san, KHONG bien dich tu source^)
echo ============================================================
python -m pip install --only-binary=:all: --upgrade -r requirements.txt
if errorlevel 1 (
    echo.
    echo   [CANH BAO] Mot so goi khong co wheel dung san cho Python nay.
    echo              Chuong trinh VAN CHAY DUOC ma khong can scikit-learn
    echo              ^(tu dung lite_model.py, chinh xac ~97-98%%^).
    if "!WIN_GEN!"=="win7" (
        echo              Kiem tra lai: ban dang dung dung Python 3.8.x chu?
    ) else (
        echo              Neu Python hien tai qua moi ^(3.13+^), thu cai them
        echo              Python 3.12 roi chay lai file nay.
    )
)

echo.
echo ============================================================
echo   BUOC 7/7 - Kiem tra ket qua
echo ============================================================
python -c "import sklearn, joblib; print('scikit-learn', sklearn.__version__, '| joblib', joblib.__version__)" 2>nul
python main.py --version

echo.
echo ============================================================
echo   XONG.
echo   He dieu hanh : !WIN_LABEL!  ^(%ARCH%^)
echo   Python dung   : !PYCMD!
echo.
echo   Lan sau chay chuong trinh bang:
echo       .venv\Scripts\activate.bat
echo       python main.py
if "!WIN_GEN!"=="win7" (
    echo.
    echo   LUU Y RIENG CHO WINDOWS 7:
    echo   - Chu co dau ^(a, a-mu, d-gach, e-mu, o-mu, o-moc, u-moc...^) co
    echo     the hien sai thanh dau hoi trong console - day la danh doi CO
    echo     CHU DICH de tranh treo/im lang console tren mot so may Win7.
    echo     Xem muc VIII trong HUONG_DAN_SU_DUNG.txt neu muon bat lai UTF-8
    echo     ^(chap nhan rui ro^): set VIVOICE_FORCE_UTF8_CONSOLE=1
    echo   - Neu thieu Visual C++ Redistributable, cai tai:
    echo     https://aka.ms/vs/17/release/vc_redist.x64.exe
)
echo ============================================================
pause
