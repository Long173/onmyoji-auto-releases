@echo off
rem ---------------------------------------------------------------------------
rem  Onmyoji Tool - don rac Temp
rem
rem  Dung khi mo app bao:
rem    "Failed to load Python DLL ...\_MEIxxxxxx\python312.dll"
rem
rem  Vi sao: app duoc dong goi kieu one-file, nen moi lan chay no phai bung
rem  khoang 240 MB vao %TEMP%\_MEIxxxxxx roi moi nap python312.dll tu do. Neu
rem  o dia het cho, hoac Temp con sot nhieu thu muc _MEI cu, buoc bung nay
rem  that bai va bao dung loi tren.
rem
rem  File nay xoa cac thu muc _MEI cu va bao con bao nhieu cho trong.
rem  Thu muc cua app dang chay se khong xoa duoc - do la binh thuong.
rem ---------------------------------------------------------------------------
setlocal enabledelayedexpansion
title Onmyoji Tool - don rac Temp

echo.
echo   Onmyoji Tool - don rac Temp
echo   ==============================================
echo.
echo   Hay DONG app Onmyoji Tool truoc khi tiep tuc.
echo.
pause

echo.
echo   Dang don %TEMP% ...
echo.

set /a removed=0
set /a skipped=0

for /d %%d in ("%TEMP%\_MEI*") do (
    rd /s /q "%%d" 2>nul
    if exist "%%d" (
        set /a skipped+=1
        echo     bo qua ^(dang duoc dung^): %%~nxd
    ) else (
        set /a removed+=1
        echo     da xoa: %%~nxd
    )
)

echo.
echo   Da xoa !removed! thu muc, bo qua !skipped!.
echo.

rem  Hoi PowerShell cho chac: chu trong ket qua cua `fsutil volume diskfree`
rem  doi theo phien ban Windows, nen loc theo chu se hong tren may khac.
for /f %%f in ('powershell -NoProfile -Command "[math]::Floor((Get-PSDrive %SystemDrive:~0,1%).Free/1GB)" 2^>nul') do (
    set freegb=%%f
)
if defined freegb (
    echo   O %SystemDrive% con trong khoang !freegb! GB.
    if !freegb! LSS 3 (
        echo.
        echo   *** CANH BAO: con duoi 3 GB. ***
        echo   App can khoang 240 MB trong cho moi lan chay. Hay don bot
        echo   o dia roi thu lai, neu khong loi se lap lai.
    )
)

echo.
echo   Xong. Gio mo lai Onmyoji Tool.
echo.
echo   Neu VAN bao loi python312.dll: rat co the phan mem diet virus da
echo   xoa file do. Vao phan Quarantine / Protection history cua no,
echo   khoi phuc lai va them Onmyoji Tool vao danh sach loai tru.
echo.
pause
endlocal
