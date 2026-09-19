@echo off
chcp 65001 >nul
title 기존 텔레그램 보고 예약작업 - 완전 삭제
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo  ====================================================================
echo   기존 주식/봇/텔레그램 예약작업을 "완전 삭제"합니다. 되돌릴 수 없습니다.
echo   (새로 만든 "후보3선_1400" 은 목록에서 제외됩니다)
echo  ====================================================================
echo.
echo  [1단계] 삭제 대상 목록을 먼저 보여드립니다.
echo.

set CNT=0
for /f "tokens=2 delims=:" %%A in ('schtasks /Query /FO LIST 2^>nul ^| findstr /I /C:"TaskName" ^| findstr /I "주식 trading bot cashcow gap telegram 텔레그램 signal pullback pipeline 파이프라인 broadcast 1435"') do (
  set "T=%%A"
  set "T=!T:~1!"
  echo !T! | findstr /I "후보3선" >nul
  if errorlevel 1 (
    set /a CNT+=1
    echo    !CNT!. !T!
  )
)

echo.
if %CNT%==0 (
  echo  삭제할 작업이 없습니다. 이미 정리되어 있습니다.
  echo.
  pause
  exit /b 0
)

echo  위 %CNT%개를 삭제합니다.
echo.
set "OK="
set /p "OK=  진행하려면 DELETE 를 그대로 입력하고 Enter (취소: 그냥 Enter): "
if /I not "!OK!"=="DELETE" (
  echo.
  echo  취소했습니다. 아무것도 지우지 않았습니다.
  echo.
  pause
  exit /b 0
)

echo.
echo  [2단계] 삭제 중...
for /f "tokens=2 delims=:" %%A in ('schtasks /Query /FO LIST 2^>nul ^| findstr /I /C:"TaskName" ^| findstr /I "주식 trading bot cashcow gap telegram 텔레그램 signal pullback pipeline 파이프라인 broadcast 1435"') do (
  set "T=%%A"
  set "T=!T:~1!"
  echo !T! | findstr /I "후보3선" >nul
  if errorlevel 1 (
    schtasks /Delete /TN "!T!" /F >nul 2>&1
    if errorlevel 1 (echo    [실패] !T!  ^(관리자 권한으로 다시 실행해 보세요^)) else (echo    [삭제] !T!)
  )
)

echo.
echo  완료. 남은 작업 확인: schtasks /Query /FO TABLE ^| findstr /I "후보3선 주식 telegram"
echo.
pause
