@echo off
rem  RhoBench 종료 (Windows) — 백그라운드로 실행 중인 서버를 끈다.
rem  계산 중이던 작업은 단계별 체크포인트에서 다음 실행 때 이어서 계산된다.
set "WSLDIR=~/DFT-Workbench"
chcp 65001 >nul
title RhoBench 종료
wsl -e bash -lc "cd %WSLDIR% && ./scripts/start.sh --stop"
echo.
pause
