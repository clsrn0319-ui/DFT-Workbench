# -*- coding: utf-8 -*-
"""벤치마크 세트 만들기 — 유지민 외, 전기화학회지 16(3) 177 (2013).

4가지 바인더(PAM·PMA·PVDF·PHFP)를 단량체~사량체로 계산한 HOMO·이온화 에너지를
B3LYP/6-31+G(d,p) 기체상에서 비교한다. 논문은 좌표를 공개하지 않았으므로 RDKit 으로
시작 구조를 만들고 프로토콜에서 구조 최적화를 켠다 (논문도 각 구조를 최적화했다).

실행: ./.venv/bin/python scripts/make_bench_yu2013.py
"""
import json
from pathlib import Path

from server.geometry import oligomerize, smiles_to_xyz

UNITS = {                        # 반복단위 (* 는 사슬 연결 자리)
    "PAM": ("*CC(*)C(N)=O", "poly(acryl amide)"),
    "PMA": ("*CC(*)C(=O)OC", "poly(methyl acrylate)"),
    "PVDF": ("*CC(*)(F)F", "poly(vinylidene fluoride)"),
    "PHFP": ("*C(F)(F)C(*)(F)C(F)(F)F", "poly(hexafluoropropylene)"),
}
# Table 1 의 B3LYP/6-31+G(d,p) 열 — (HOMO, IP) eV, n = 1·2·3·4
REF = {
    "PAM": [(-7.3, 9.2), (-7.1, 8.8), (-6.9, 8.7), (-6.6, 8.2)],
    "PMA": [(-7.8, 9.7), (-7.7, 9.2), (-7.6, 9.0), (-7.6, 8.6)],
    "PVDF": [(-7.7, 10.2), (-9.6, 11.2), (-9.6, 11.0), (-9.2, 10.5)],
    "PHFP": [(-8.4, 10.5), (-10.2, 11.7), (-10.2, 11.5), (-10.5, 11.7)],
}
LSV = {"PAM": 4.92, "PMA": 4.94, "PVDF": 4.97, "PHFP": 4.99}   # 실험 산화분해 전위 (V vs Li)

entries = []
for key, (unit, full) in UNITS.items():
    for n, (homo, ip) in enumerate(REF[key], start=1):
        smiles = oligomerize(unit, n)
        atoms, _ = smiles_to_xyz(smiles, n_conformers=5)
        entries.append({
            "id": f"{key.lower()}_n{n}",
            "name": f"{key} {['단량체', '이량체', '삼량체', '사량체'][n - 1]}",
            "model": f"{full} · 반복단위 {n}개",
            "formula": "",
            "smiles": smiles,
            "atoms": [[a[0], round(a[1], 6), round(a[2], 6), round(a[3], 6)] for a in atoms],
            "reference": {"homo_ev": homo, "ip_vertical_ev": ip},
            "note": f"LSV 산화분해 {LSV[key]} V vs Li (중합체 기준, 사슬 길이 무관)",
        })

doc = {
    "id": "yu2013_hv_binders",
    "title": "고전압 바인더 HOMO·이온화 에너지 — PAM · PMA · PVDF · PHFP (유지민 외 2013)",
    "description": (
        "단량체부터 사량체까지 네 바인더의 HOMO 와 이온화 에너지를 B3LYP/6-31+G(d,p) 기체상에서 "
        "계산한 논문값과 비교한다. 논문은 PHFP > PVDF > PMA > PAM 순으로 내산화성이 크다고 보고했고, "
        "같은 순서가 LSV 실험(4.99 · 4.97 · 4.94 · 4.92 V vs Li)과 일치했다. 좌표가 공개되지 않아 "
        "시작 구조는 RDKit 으로 만들고 프로토콜에서 구조 최적화를 켠다 — 논문도 각 구조를 최적화했다."),
    "source": {
        "citation": ("유지민, Alexey Kashaev, 이맹은. 고전압용 리튬이차전지 바인더 개발을 위한 시뮬레이션 및 "
                     "전기화학 평가 비교를 통한 산화분해전압 예측 연구. 전기화학회지 16(3), 177-183 (2013)"),
        "doi": "10.5229/JKES.2013.16.3.177",
        "figure": "Table 1 · Fig. 2 · Fig. 3",
        "data": "본문 Table 1 (좌표 비공개)",
        "method": ("구조·에너지: Gaussian09 B3LYP/6-31+G(d,p) 기체상 (분산 보정 없음). "
                   "IP = E(양이온) − E(중성). 같은 논문의 PM3(VAMP)·GGA-PBE(DMol3) 결과는 비교 대상에서 제외. "
                   "실험: LSV, Pt disk, 1M LiPF6 / EC:EMC:DEC = 3:5:2, Li quasi-reference"),
    },
    "protocol": {
        "functional": "B3LYP (분산 보정 없음)",
        "basis": "6-31+g**",
        "envType": "진공·기체",
        "accuracy": "표준",
        "optimizeGeometry": True,
        "thermochemistry": False,
        "purpose": "전자구조 + 산화/환원 전위",
        "note": ("Gaussian 의 B3LYP(VWN3)에 맞춰 분산 보정을 끈다. 6-31+G(d,p) = 6-31+g**. "
                 "IP 는 수직 이온화 에너지로 비교한다 — 논문은 단열/수직을 명시하지 않았다."),
    },
    "quantities": [["homo_ev", "HOMO", "eV"], ["ip_vertical_ev", "이온화 에너지(수직)", "eV"]],
    "tolerance_ev": {"pass": 0.2, "review": 0.5},
}

path = Path(__file__).resolve().parent.parent / "server" / "benchmarks" / "yu2013_hv_binders.json"
path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"wrote {path} — {len(entries)} entries")
for e in entries:
    print(f"  {e['id']:10s} {len(e['atoms']):3d}원자  {e['smiles']}")
