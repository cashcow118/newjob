@echo off
chcp 65001 >nul
title 오늘의 후보 3선 — 수동 실행
cd /d "%~dp0"
echo.
echo  100종목 스캔 후 후보 3선을 뽑습니다. 2~6분 걸립니다.
echo.
python "%~dp0후보3선.py" %*
echo.
pause
