@echo off
chcp 65001 >nul
title 후보 3선 — 예약 해제
schtasks /Delete /TN "후보3선_1400" /F
echo.
echo  해제했습니다. 다시 켜려면 스케줄러등록_후보3선.bat 을 실행하세요.
pause
