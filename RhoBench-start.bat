@echo off
rem ===================================================================
rem  RhoBench 시작 (Windows) — 이 파일을 더블클릭하면 실행됩니다.
rem
rem  WSL2 안의 Ubuntu에서 서버를 켜고, 잠시 뒤 브라우저를 자동으로 엽니다.
rem
rem  ※ 아래 WSLDIR 이 Ubuntu 안의 프로그램 폴더 경로와 다르면 고치세요.
rem     (Ubuntu 터미널에서 `cd DFT-Workbench && pwd` 로 확인)
rem ===================================================================

set "WSLDIR=~/DFT-Workbench"
set "PORT=8000"

chcp 65001 >nul
title RhoBench

echo.
echo   RhoBench 를 시작합니다.
echo   서버가 준비되면 브라우저가 자동으로 열립니다 (약 20초).
echo   이 창을 닫으면 서버가 멈춥니다.
echo.

rem 서버가 뜰 시간을 준 뒤 브라우저를 연다
start "" /min powershell -NoProfile -Command "Start-Sleep -Seconds 20; Start-Process 'http://localhost:%PORT%'"

rem WSL 안에서 실행기 호출.
rem RHOBENCH_NO_PROMPT=1 — 비밀번호를 묻지 않고 지난번 것으로 바로 시작한다.
rem (최초 실행이라 저장된 비밀번호가 없으면 실행기가 알아서 물어본다.
rem  비밀번호를 바꾸려면 Ubuntu 터미널에서 ./scripts/start.sh 를 직접 실행)
wsl -e bash -lc "cd %WSLDIR% && RHOBENCH_NO_PROMPT=1 ./scripts/start.sh"

echo.
echo   서버가 종료되었습니다.
pause
