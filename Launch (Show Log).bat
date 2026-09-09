@echo off
rem Onmyoji Tool - launcher with a visible console.
rem Use this when something is wrong: it shows the log live and adds -v so
rem every click and template match score is recorded.
pushd "%~dp0"
set PYTHONIOENCODING=utf-8
echo === Onmyoji Tool (verbose) - log: logs\onmyoji_auto.log ===
echo.
python -u "decompiled\source\app.py" -v
echo.
echo === Da ket thuc, nhan phim bat ky de dong ===
pause >nul
popd
