"""환경·용매·소재 프리셋 정의.

RhoBench UI(모의 프로토타입)의 설정 체계를 그대로 따르되, 각 항목이 실제
PySCF 계산 파라미터로 매핑되도록 정의한다.

SMD 용매 파라미터 형식은 PySCF solvent_db와 동일:
  [n(20°C), n(25°C), alpha(Abraham HBD), beta(Abraham HBA),
   gamma(표면장력, cal·mol⁻¹·Å⁻² = dyn/cm × 1.4393), eps(유전상수),
   phi(방향족 탄소 비율), psi(할로겐 비율)]

EC/DMC/EMC/NMP는 Minnesota SMD 기본 DB에 없어 문헌 물성(유전상수,
굴절률, 표면장력, Kamlet-Taft/Abraham 파라미터)으로 구성한 커스텀 항목이다.
EC/DMC 1:1 혼합 용매는 부피분율 가중 평균으로 근사한 유효 매질(단일 유전
연속체) 취급이며, 이는 관례적 근사임을 결과 노트에 명시한다.
"""

HARTREE2EV = 27.211386
HARTREE2KCAL = 627.5095

# 절대 전극 전위 (V). SHE 4.44 V (Trasatti), Li/Li+ = SHE − 3.04 V.
ABSOLUTE_POTENTIALS = {
    "Li/Li+": 1.44,
    "SHE": 4.44,
}

SOLVENTS = [
    {
        "id": "sol-ec", "kind": "single", "name": "Ethylene carbonate", "abbr": "EC",
        "smiles": "O=C1OCCO1", "formula": "C3H4O3", "modelKey": "smd:ec",
        "smd": [1.4209, 1.4158, 0.00, 0.60, 72.8, 89.78, 0.0, 0.0],
        "note": "카보네이트계 전해액 (ε=89.78, 40°C 액상 기준)",
    },
    {
        "id": "sol-dmc", "kind": "single", "name": "Dimethyl carbonate", "abbr": "DMC",
        "smiles": "COC(=O)OC", "formula": "C3H6O3", "modelKey": "smd:dmc",
        "smd": [1.3687, 1.3660, 0.00, 0.38, 41.0, 3.107, 0.0, 0.0],
        "note": "저점도 선형 카보네이트 (ε=3.107)",
    },
    {
        "id": "sol-emc", "kind": "single", "name": "Ethyl methyl carbonate", "abbr": "EMC",
        "smiles": "CCOC(=O)OC", "formula": "C4H8O3", "modelKey": "smd:emc",
        "smd": [1.3652, 1.3630, 0.00, 0.38, 38.6, 2.958, 0.0, 0.0],
        "note": "저점도 선형 카보네이트 (ε=2.958)",
    },
    {
        "id": "sol-water", "kind": "single", "name": "Water", "abbr": "H2O",
        "smiles": "O", "formula": "H2O", "modelKey": "smd:water",
        "smd": None,  # PySCF 내장 'water' 항목 사용
        "builtin_key": "water",
        "note": "수계 바인더 공정",
    },
    {
        "id": "sol-nmp", "kind": "single", "name": "N-Methyl-2-pyrrolidone", "abbr": "NMP",
        "smiles": "CN1CCCC1=O", "formula": "C5H9NO", "modelKey": "smd:nmp",
        "smd": [1.4700, 1.4680, 0.00, 0.77, 58.6, 32.2, 0.0, 0.0],
        "note": "PVDF 등 유기계 공정",
    },
    {
        "id": "sol-ecdmc", "kind": "mixed", "name": "EC/DMC 1:1", "abbr": "EC/DMC",
        "components": [{"abbr": "EC", "ratio": 1}, {"abbr": "DMC", "ratio": 1}],
        "ratioBasis": "부피비", "modelKey": "smd:ec-dmc-11",
        "smd": [1.3948, 1.3909, 0.00, 0.49, 56.9, 46.44, 0.0, 0.0],
        "note": "표준 전해액 베이스 — 부피분율 가중 평균 유효 매질 근사",
    },
]

SOLVENTS_BY_ID = {s["id"]: s for s in SOLVENTS}

# 소재 프리셋 — 바인더/전해액 첨가제 후보 모노머.
# 2량체/3량체는 비닐 중합 head-to-tail 반복 단위를 수소로 캡핑한 구조.
MATERIALS = [
    {
        "id": "vdf", "name": "비닐리덴 플루오라이드 (VDF)", "abbr": "VDF",
        "formula": "C2H2F2",
        "smiles": {
            "모노머": "C=C(F)F",
            "2량체": "CC(F)(F)CC(F)F",
            "3량체": "CC(F)(F)CC(F)(F)CC(F)F",
        },
        "note": "PVDF 바인더 반복 단위",
    },
    {
        "id": "aa", "name": "아크릴산 (AA)", "abbr": "AA",
        "formula": "C3H4O2",
        "smiles": {
            "모노머": "C=CC(=O)O",
            "2량체": "CC(C(=O)O)CCC(=O)O",
            "3량체": "CC(C(=O)O)CC(C(=O)O)CCC(=O)O",
        },
        "note": "수계 바인더(PAA) 반복 단위",
    },
    {
        "id": "styrene", "name": "스타이렌 (Styrene)", "abbr": "ST",
        "formula": "C8H8",
        "smiles": {
            "모노머": "C=Cc1ccccc1",
            "2량체": "CC(c1ccccc1)CCc1ccccc1",
            "3량체": "CC(c1ccccc1)CC(c1ccccc1)CCc1ccccc1",
        },
        "note": "SBR 바인더 구성 단위",
    },
    {
        "id": "an", "name": "아크릴로나이트릴 (AN)", "abbr": "AN",
        "formula": "C3H3N",
        "smiles": {
            "모노머": "C=CC#N",
            "2량체": "CC(C#N)CCC#N",
            "3량체": "CC(C#N)CC(C#N)CCC#N",
        },
        "note": "PAN 바인더 반복 단위",
    },
    {
        "id": "mma", "name": "메틸 메타크릴레이트 (MMA)", "abbr": "MMA",
        "formula": "C5H8O2",
        "smiles": {
            "모노머": "C=C(C)C(=O)OC",
            "2량체": "CC(C)(C(=O)OC)CC(C)C(=O)OC",
            "3량체": "CC(C)(C(=O)OC)CC(C)(C(=O)OC)CC(C)C(=O)OC",
        },
        "note": "PMMA 바인더 반복 단위",
    },
]

MATERIALS_BY_ID = {m["id"]: m for m in MATERIALS}

ENV_TYPES = [
    {"id": "사용자 정의", "desc": "용매(용매 라이브러리 연동)·온도·기준 전극 직접 선택"},
    {"id": "진공·기체", "desc": "vacuum · isolated molecule · 분자 자체 전자구조"},
]

# 혼합 용매 부피 가중 평균 시 물의 SMD 파라미터 (DB의 -1 센티널을 실측값으로 대체)
WATER_SMD_FOR_MIX = [1.3328, 1.3323, 0.82, 0.35, 103.6, 78.355, 0.0, 0.0]

# 정확도 프리셋 → 실제 계산 파라미터.
#  - n_conf: RDKit ETKDG conformer 수 (역장 최적화 후 후보 선별)
#  - n_dft_rank: 상위 conformer 몇 개를 DFT 단일점으로 재순위화할지
#  - do_opt: DFT 구조 최적화 여부 (기체상, geomeTRIC/pyberny)
#  - do_thermo: 진동수 계산 기반 열역학 보정 (ZPE·엔탈피·깁스, 설정 온도 반영)
#  - basis_opt / basis_sp: 최적화·진동수 / 최종 단일점 basis
#  - conf_sens: 전위 conformer 민감도 — 상위 몇 개 conformer 에서 IP/EA 를 다시 낼지
#               (v2.0 P0-5. 0 이면 지배 conformer 한 값만)
#  - li_model / li_max_sites: Li⁺ 상호작용 모델 (v2.0 P0-6) — bare: 고립 Li⁺ 결합,
#               competition: Li(solv)n⁺ 용매 경쟁 ΔE_exchange. site 는 MEP 최소점 +
#               헤테로원자 부위를 몇 곳까지 볼지
ACCURACY = {
    "빠름": {"n_conf": 5, "n_dft_rank": 1, "do_opt": False, "do_thermo": False,
             "ensemble": False, "conf_sens": 0, "li_model": "bare", "li_max_sites": 1,
             "basis_opt": "def2-svp", "basis_sp": "def2-svp",
             "basis_anion": None,
             "desc": "conformer 5 · MMFF 구조 + DFT 단일점(def2-SVP) · 음이온 diffuse 없음 — 사전 스크리닝"},
    "표준": {"n_conf": 15, "n_dft_rank": 3, "do_opt": True, "do_thermo": True,
             "ensemble": False, "conf_sens": 3, "li_model": "bare", "li_max_sites": 1,
             "basis_opt": "def2-svp", "basis_sp": "def2-tzvp",
             "basis_anion": "ma-def2-tzvp",
             "desc": "conformer 15 · DFT 재순위 3 · 최적화(def2-SVP) + 진동수·qRRHO 열보정 "
                     "+ 단일점(def2-TZVP) · 음이온 ma-def2-TZVP · 전위 conformer 민감도 3"},
    "정밀": {"n_conf": 30, "n_dft_rank": 5, "do_opt": True, "do_thermo": True,
             "ensemble": True, "conf_sens": 5, "li_model": "competition", "li_max_sites": 3,
             "basis_opt": "def2-tzvp", "basis_sp": "def2-tzvp",
             "basis_anion": "def2-tzvpd",
             "desc": "conformer 30 · DFT 재순위 5 · Boltzmann 앙상블 가중 · 최적화·진동수(qRRHO)·"
                     "단일점 def2-TZVP · 음이온 def2-TZVPD · 전위 conformer 민감도 5 · "
                     "Li⁺ 용매 경쟁(site 3)"},
}

# 범함수별 진동수 스케일 인자 (문헌 대표값 — 조화근사 과대평가 보정, basis 의존성 있음)
FREQ_SCALE = {
    "PBE0-D3(BJ)": 0.957,
    "B3LYP-D3(BJ)": 0.961,
    "PBE-D3(BJ)": 0.986,
    "M06-2X": 0.947,
    "HF": 0.899,
}

# 범함수 표기 → (PySCF xc, 분산 보정)
FUNCTIONALS = {
    "PBE0-D3(BJ)": ("pbe0", "d3bj"),
    "B3LYP-D3(BJ)": ("b3lyp", "d3bj"),
    "PBE-D3(BJ)": ("pbe", "d3bj"),
    "M06-2X": ("m062x", None),
    "HF": ("hf", None),
}

# 음이온·EA 계산에는 diffuse 함수를 포함한 기저가 필요하다 (v2.0 P0-1)
BASIS_SETS = ["def2-svp", "def2-tzvp", "ma-def2-tzvp", "def2-tzvpd",
              "def2-svpd", "6-31g*", "sto-3g"]
DIFFUSE_BASIS_SETS = ["ma-def2-tzvp", "def2-tzvpd", "def2-svpd"]

PURPOSES = [
    "전자구조(구조 최적화)",
    "전자구조 + 산화/환원 전위",
    "물성 지문 (확장 기술자 전체)",
    # "건식 음극 바인더 스크리닝" 목적은 현 단계에서 쓰지 않아 선택지에서 제외
    # (엔진·판정 로직은 남아 있어 목록에 되살리면 그대로 동작한다)
]

# 스크리닝 레이더(물성 지문) 축 — (기술자 키, 표시명, 단위, 낮을수록 좋음)
FINGERPRINT_AXES = [
    ("gap_ev", "HOMO-LUMO gap", "eV", False),
    ("dipole_debye", "쌍극자 모멘트", "D", False),
    ("oxidation_potential_v", "산화 전위", "V", False),
    ("lumo_ev", "LUMO 에너지", "eV", False),
    ("homo_ev", "HOMO 에너지", "eV", True),
    ("li_binding_kj", "Li⁺ 결합 에너지", "kJ/mol", True),
]

DEFAULT_SETTINGS = {
    "envType": "사용자 정의",
    "solventId": "sol-ecdmc",
    "temperature": 298.15,
    "atmosphere": "불활성",  # 기록용 메타데이터 (분자 DFT 해밀토니안에는 미반영)
    "structure": "모노머",
    "accuracy": "표준",
    "purpose": "전자구조(구조 최적화)",
    "referenceElectrode": "Li/Li+",
    "expert": {
        "charge": 0,
        "multiplicity": 1,
        "nConformers": None,     # None → 정확도 프리셋 값
        "functional": "PBE0-D3(BJ)",
        "basis": None,           # None → 정확도 프리셋 값
        "optimizeGeometry": None,  # None → 정확도 프리셋 값
        "thermochemistry": None,   # None → 정확도 프리셋 값
        "redoxAdiabatic": None,    # None → 구조 최적화 여부 따름 (단열 전위)
        "nonequilibriumSolvation": None,  # None → 용매 있는 수직 전위에 자동 적용
        "boltzmannEnsemble": None,        # None → 정확도 프리셋 값 (정밀에서 활성)
        "conformerSensitivity": None,     # None → 정확도 프리셋 값 (표준 3 · 정밀 5 · 빠름 없음)
        "liModel": None,                  # None → 프리셋 (정밀: competition, 그 외 bare)
        "liCoordination": None,           # None → 4 (Li(solv)n⁺ 의 n)
        "liMaxSites": None,               # None → 프리셋 (정밀 3, 그 외 1)
        "freqScale": None,                # None → 범함수별 문헌 스케일 인자
        "scfTol": 1e-8,
    },
}
