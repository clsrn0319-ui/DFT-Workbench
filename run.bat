@echo off
REM 드라이룸 PC 실행 스크립트 — venv 활성화 → Streamlit 기동 (localhost 전용)
cd /d %~dp0
if not exist .venv (
    echo 가상환경이 없습니다. 먼저 다음을 실행하세요:
    echo   python -m venv .venv
    echo   .venv\Scripts\activate
    echo   pip install --no-index --find-links=wheelhouse -r requirements.txt
    pause
    exit /b 1
)
call .venv\Scripts\activate
set PYTHONPATH=%~dp0
streamlit run dry_process_ai\app\Home.py --server.address 127.0.0.1 --server.headless false
