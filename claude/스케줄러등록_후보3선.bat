@echo off
chcp 65001 >nul
title 후보 3선 — 평일 14:00 예약 등록
cd /d "%~dp0"
echo.
echo  평일(월~금) 14:00 에 "후보3선_자동.bat" 이 돌도록 등록합니다.
echo  폴더: %~dp0
echo.
pause >nul
schtasks /Create /TN "후보3선_1400" /TR "\"%~dp0후보3선_자동.bat\"" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 14:00 /RL HIGHEST /F
if errorlevel 1 (
  echo.
  echo  [실패] 오른쪽 클릭 - 관리자 권한으로 실행 을 해보세요.
) else (
  echo.
  echo  [완료] 평일 14:00 등록됨. 작업 이름: 후보3선_1400
  echo  지금 한 번 시험해 보려면: schtasks /Run /TN "후보3선_1400"
)
echo.
pause
