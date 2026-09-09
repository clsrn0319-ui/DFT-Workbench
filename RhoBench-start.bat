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
echo   서버가 준비되면 브라우저가 자동으로 열립니다.
echo   서버는 백그라운드로 돌아가므로 이 창은 닫아도 됩니다.
echo   끄려면 RhoBench-stop.bat 을 실행하세요.
echo.

rem WSL 안에서 실행기를 «백그라운드 모드»로 호출 — 창을 닫아도 서버가 남는다.
rem RHOBENCH_NO_PROMPT=1 — 비밀번호를 묻지 않고 지난번 것으로 바로 시작한다.
rem (최초 실행이라 저장된 비밀번호가 없으면 실행기가 알아서 물어본다.
rem  비밀번호를 바꾸려면 Ubuntu 터미널에서 ./scripts/start.sh 를 직접 실행)
wsl -e bash -lc "cd %WSLDIR% && RHOBENCH_NO_PROMPT=1 ./scripts/start.sh --background"
if errorlevel 1 (
  echo.
  echo   서버를 시작하지 못했습니다. Ubuntu 터미널에서 ./scripts/start.sh 로 원인을 확인하세요.
  pause
  exit /b 1
)
start "" "http://localhost:%PORT%"
echo.
echo   브라우저를 열었습니다. 이 창은 닫아도 됩니다.
timeout /t 8 >nul
