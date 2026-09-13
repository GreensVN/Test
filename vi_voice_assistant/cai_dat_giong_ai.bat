@echo off
setlocal enabledelayedexpansion
title Cai dat GIONG AI tieng Viet (VieNeu chinh + Piper du phong)
cd /d "%~dp0"

REM ============================================================================
REM  v6.4: engine CHINH da doi tu Piper sang VieNeu-TTS v3-Turbo (Apache 2.0).
REM  Ban truoc cua file nay (v6.3) chi cai Piper - gio cai CA HAI:
REM    - VieNeu (engine mac dinh giong_noi_ai.py dung)   - can Python 3.10+
REM    - Piper  (du phong/lich su, nhe hon, PHAI ghi cong) - Python nao cung duoc
REM  10 giong dung san cua VieNeu chay thuan CPU qua ONNX, KHONG can torch.
REM  Rieng NHAN BAN GIONG (tham so ref_audio / lenh "nhan-ban") can cai them
REM  torch + torchaudio (van chi chay CPU, KHONG can GPU that - day la yeu cau
REM  cua goi vieneu de trich xuat dac trung giong noi khi nhan ban, khong phai
REM  do du an nay dat ra) - BUOC 4 se hoi ban co muon cai phan nay khong.
REM ============================================================================

echo.
echo ============================================================
echo   BUOC 1/7 - Kiem tra Python
echo ============================================================
where python >nul 2>&1
if errorlevel 1 (
    echo [LOI] Khong tim thay Python trong PATH.
    echo       Tai Python 3.12 tai https://www.python.org/downloads/
    pause
    exit /b 1
)

if exist ".venv\Scripts\activate.bat" call .venv\Scripts\activate.bat

python --version

set "VIENEU_OK=0"
set "PYMAJOR=0"
set "PYMINOR=0"
set "PYVER_FULL=?"
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set "PYVER_FULL=%%v"
for /f "tokens=1,2 delims=." %%a in ("!PYVER_FULL!") do (
    set "PYMAJOR=%%a"
    set "PYMINOR=%%b"
)
if !PYMAJOR! GTR 3 set "VIENEU_OK=1"
if !PYMAJOR! EQU 3 if !PYMINOR! GEQ 10 set "VIENEU_OK=1"

if "!VIENEU_OK!"=="1" (
    echo   [OK] Python !PYVER_FULL! - du dieu kien cho VieNeu ^(can 3.10+^).
) else (
    echo   [CHU Y] Python !PYVER_FULL! phat hien duoc - VieNeu can 3.10+ nen se
    echo       BO QUA cac buoc cai VieNeu ben duoi. Ban van dung duoc giong
    echo       Piper du phong o BUOC 5.
    echo       Muon dung VieNeu: cai Python 3.12 tai
    echo       https://www.python.org/downloads/  roi chay lai file nay.
)

echo.
echo ============================================================
echo   BUOC 2/7 - Nang cap pip / setuptools / wheel
echo ============================================================
python -m pip install --upgrade pip setuptools wheel

echo.
echo ============================================================
echo   BUOC 3/7 - Cai VieNeu-TTS v3-Turbo ^(engine CHINH, Apache 2.0^)
echo ============================================================
if "!VIENEU_OK!"=="1" (
    python -m pip install --only-binary=:all: --upgrade vieneu
    if errorlevel 1 (
        echo    [!] Khong co wheel dung san, thu lai cho phep build...
        python -m pip install --upgrade vieneu
    )
    if errorlevel 1 (
        echo    [X] Cai vieneu THAT BAI. Ban van dung duoc Piper du phong ^(BUOC 5^).
        set "VIENEU_OK=0"
    ) else (
        echo    [OK] Da cai vieneu.
    )
) else (
    echo    Bo qua ^(xem ly do o BUOC 1^).
)

echo.
echo ============================================================
echo   BUOC 4/7 - Ho tro NHAN BAN GIONG ^(tuy chon, rieng cho VieNeu^)
echo ============================================================
if "!VIENEU_OK!"=="1" (
    echo   10 giong dung san KHONG can buoc nay. Chi can neu ban muon dung
    echo   lenh "nhan-ban" ^(nhan ban giong tu audio mau 3-5 giay^) - buoc do
    echo   can them thu vien torch + torchaudio ^(ban CPU, KHONG can GPU
    echo   that, tren Windows thu them khoang 150-250 MB^).
    echo.
    choice /C YN /N /M "  Cai them ho tro nhan ban giong ngay bay gio? [Y/N] "
    if errorlevel 2 (
        echo    Bo qua. Ve sau can thi cai bang:  pip install torch torchaudio
    ) else (
        echo    Dang cai torch + torchaudio...
        python -m pip install --upgrade torch torchaudio
        if errorlevel 1 (
            echo    [CANH BAO] Cai khong thanh cong. Lenh "nhan-ban" se chua
            echo               dung duoc, nhung 10 giong dung san van binh thuong.
        ) else (
            echo    [OK] Xong - lenh "nhan-ban" gio dung duoc.
        )
    )
) else (
    echo    Bo qua ^(VieNeu chua san sang - xem BUOC 1^).
)

echo.
echo ============================================================
echo   BUOC 5/7 - Cai Piper du phong ^(MIT, PHAI ghi cong^)
echo ============================================================
echo   Piper + vi_VN-vais1000-medium: nhe hon VieNeu nhieu ^(~63 MB^), nhung
echo   chat luong thap hon ro ret. Huu ich neu may qua yeu cho VieNeu, Python
echo   qua cu ^(^<3.10^), hoac ban thich giong nay hon. KHONG con la engine
echo   mac dinh tu v6.4 nhung van duoc cai de du phong.
echo.
python -m pip install --only-binary=:all: --upgrade sounddevice numpy SpeechRecognition
REM Ban moi hon piper-tts da chuyen sang GPL-3.0. Ghim 1.2.0 de giu MIT.
python -m pip install --only-binary=:all: "piper-tts==1.2.0" onnxruntime
if errorlevel 1 (
    echo    [!] Khong cai duoc piper-tts 1.2.0 tren Python nay.
    echo        Piper 1.2.0 chi co wheel toi Python 3.11.
    echo        Cach xu ly: dung Python 3.11/3.12, hoac cai ban moi:
    echo            pip install piper-tts onnxruntime
    echo        LUU Y: ban moi la GPL-3.0 - doc GIONG_NOI_AI_TIENG_VIET.txt phan 3.
    echo.
)

echo.
echo ============================================================
echo   BUOC 6/7 - Tai giong AI ve may ^(lan dau tien, co the mat vai phut^)
echo ============================================================
if "!VIENEU_OK!"=="1" (
    python giong_noi_ai.py tai
) else (
    echo    Bo qua tai VieNeu ^(chua cai duoc - xem cac buoc tren^).
)

echo.
echo ============================================================
echo   BUOC 7/7 - Kiem tra ket qua
echo ============================================================
python giong_noi_ai.py kiem-tra
echo.
echo Doc thu:
python giong_noi_ai.py thu "Xin chao, toi la tro ly ao tieng Viet."

echo.
echo ============================================================
echo Xem bang giay phep day du:
echo     python giong_noi_ai.py giay-phep
echo.
echo Nhan ban giong tu audio mau ^(can BUOC 4 da cai torch^):
echo     python giong_noi_ai.py nhan-ban mau.wav "Cau can doc"
echo.
echo NHO: Piper PHAI ghi cong ^(giu file giong_ai\ATTRIBUTION.txt khi phat
echo hanh san pham^). VieNeu la Apache 2.0 nen khong bat buoc, nhung van nen giu.
echo ============================================================
pause
