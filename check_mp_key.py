"""MP_API_KEY 가 올바르게 설정됐는지 확인하는 스크립트.

실행:  python check_mp_key.py

.env 파일(또는 환경 변수)에서 MP_API_KEY 를 읽어,
Materials Project 서버에 실제로 접속되는지 확인합니다.
키 자체는 화면에 그대로 출력하지 않고 일부만 가려서 보여줍니다.
"""

import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()  # 같은 폴더의 .env 를 읽어 환경 변수로 올림
except ModuleNotFoundError:
    print("[안내] python-dotenv 가 없어 .env 자동 로드를 건너뜁니다.")
    print("       pip install -r requirements.txt 로 설치할 수 있습니다.\n")

key = os.environ.get("MP_API_KEY")

# 1) 키가 존재하는지
if not key or key == "your_materials_project_api_key_here":
    print("❌ MP_API_KEY 가 설정되지 않았습니다.")
    print("   .env 파일에 실제 키를 넣었는지 확인하세요.")
    sys.exit(1)

masked = key[:4] + "..." + key[-4:] if len(key) > 8 else "****"
print(f"✅ MP_API_KEY 를 찾았습니다: {masked}  (길이 {len(key)}자)")

# 2) 실제로 Materials Project 에 접속되는지
try:
    from mp_api.client import MPRester
except ModuleNotFoundError:
    print("\n[안내] mp-api 가 설치되어 있지 않아 접속 테스트는 건너뜁니다.")
    print("       pip install -r requirements.txt 후 다시 실행하세요.")
    sys.exit(0)

try:
    with MPRester(key) as mpr:
        docs = mpr.materials.summary.search(
            formula="Si", fields=["material_id", "formula_pretty"]
        )
    print(f"✅ 서버 접속 성공! 예시로 'Si' 검색 결과 {len(docs)}건을 받았습니다.")
    print("   → 키가 정상 동작합니다. 🎉")
except Exception as e:
    print("❌ 서버 접속에 실패했습니다. 키가 틀렸거나 네트워크 문제일 수 있습니다.")
    print(f"   오류 내용: {e}")
    sys.exit(1)
