@echo off
chcp 65001 >nul
rem 스케줄러가 부르는 조용한 실행기 — 결과는 logs\ 에 쌓인다.
cd /d "%~dp0"
if not exist "logs" mkdir "logs"
set "STAMP=%DATE:~0,4%-%DATE:~5,2%-%DATE:~8,2%"
python "%~dp0후보3선.py" >> "logs\후보3선_%STAMP%.log" 2>&1
exit /b %ERRORLEVEL%
