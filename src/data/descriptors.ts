// 부록 D. 분자/DFT descriptor 사전 — 16개 필드, 7개 그룹
// direction: 레이더 정규화 방향 (higher = 값이 클수록 바깥, lower = 작을수록(더 음수) 바깥, none = 방향 평가 금지)

export interface DescriptorDef {
  key: string
  label: string
  unit: string
  group: string
  definition: string
  caution: string
  direction: 'higher' | 'lower' | 'none'
  radarMin: number
  radarMax: number
  interfacial?: boolean // 계면/실험 항목 — 단일 분자 DFT 값으로 제공 금지
}

export const DESCRIPTOR_GROUPS = [
  '전자구조',
  '전기화학',
  '정전기·전하',
  '열화학·반응',
  '이온 결합',
  '재료 결합',
  '계면·실험',
] as const

export const DESCRIPTORS: DescriptorDef[] = [
  {
    key: 'binder_homo',
    label: 'HOMO 에너지',
    unit: 'eV',
    group: '전자구조',
    definition: '최고 점유 분자궤도 에너지. 산화 경향의 보조 지표.',
    caution: '계산 방법·용매·구조에 종속. 실제 개시전위와 동일하지 않음.',
    direction: 'lower',
    radarMin: -9,
    radarMax: -5,
  },
  {
    key: 'binder_lumo',
    label: 'LUMO 에너지',
    unit: 'eV',
    group: '전자구조',
    definition: '최저 비점유 분자궤도 에너지. 환원 경향의 보조 지표.',
    caution: 'diffuse basis, 전하 상태, 용매에 민감.',
    direction: 'higher',
    radarMin: -1.5,
    radarMax: 1.5,
  },
  {
    key: 'binder_homo_lumo_gap',
    label: 'HOMO-LUMO gap',
    unit: 'eV',
    group: '전자구조',
    definition: 'LUMO − HOMO. 전자 여기·반응성 경향의 상대 지표.',
    caution: '전기화학 안정 전압 범위와 동일하지 않음.',
    direction: 'higher',
    radarMin: 4,
    radarMax: 10,
  },
  {
    key: 'binder_ionization_energy',
    label: '이온화 에너지 (VIP)',
    unit: 'eV',
    group: '전기화학',
    definition: 'E(cation) − E(neutral). vertical/adiabatic 구분 저장.',
    caution: '구조 이완·용매·thermal correction 여부를 함께 기록.',
    direction: 'higher',
    radarMin: 5,
    radarMax: 11,
  },
  {
    key: 'binder_electron_affinity',
    label: '전자친화도 (VEA)',
    unit: 'eV',
    group: '전기화학',
    definition: 'E(neutral) − E(anion). 환원 성향 해석에 사용.',
    caution: '음의 값은 자발적 전자 수용이 불리함을 의미.',
    direction: 'none',
    radarMin: -2,
    radarMax: 2,
  },
  {
    key: 'binder_oxidation_potential',
    label: '산화 전위',
    unit: 'V vs 기준전극',
    group: '전기화학',
    definition: 'neutral→cation 자유에너지 차이를 기준 전극으로 변환.',
    caution: 'solvent, T, standard state, 기준 전극, vertical/adiabatic 구분 필수.',
    direction: 'higher',
    radarMin: 3,
    radarMax: 8,
  },
  {
    key: 'binder_reduction_potential',
    label: '환원 전위',
    unit: 'V vs 기준전극',
    group: '전기화학',
    definition: 'neutral→anion 자유에너지 차이 기반. 안정 전압 범위의 하한.',
    caution: '산화 전위와 함께 전기화학 안정 전압 범위를 구성.',
    direction: 'lower',
    radarMin: -1,
    radarMax: 2,
  },
  {
    key: 'binder_meps_max_positive',
    label: 'MEP 최대 양전위',
    unit: 'kcal/mol',
    group: '정전기·전하',
    definition: '전자밀도 등가면(0.001 e/Bohr³) 위 최대 정전기 퍼텐셜.',
    caution: 'surface/isovalue 정의 필수. 친핵체 접근 후보 부위.',
    direction: 'none',
    radarMin: 5,
    radarMax: 60,
  },
  {
    key: 'binder_meps_min_negative',
    label: 'MEP 최소 음전위',
    unit: 'kcal/mol',
    group: '정전기·전하',
    definition: '등가면 위 최소 정전기 퍼텐셜. Li⁺·H-bond donor 결합 후보 부위.',
    caution: 'surface/isovalue 정의 필수.',
    direction: 'lower',
    radarMin: -70,
    radarMax: -5,
  },
  {
    key: 'binder_dipole_moment',
    label: '쌍극자 모멘트',
    unit: 'D',
    group: '정전기·전하',
    definition: '전하 분리 정도. 방향 벡터를 3D 구조에 표시 가능.',
    caution: 'conformer와 solvent에 의존.',
    direction: 'none',
    radarMin: 0,
    radarMax: 8,
  },
  {
    key: 'binder_nbo_charge_cationic_site',
    label: '양이온성 부위 NBO 전하',
    unit: 'e',
    group: '정전기·전하',
    definition: 'NBO 분석의 원자별 전하 중 지정된 cationic site 값.',
    caution: 'site atom ID, NBO version과 전체 charge state 저장.',
    direction: 'none',
    radarMin: 0,
    radarMax: 1,
  },
  {
    key: 'binder_enthalpy',
    label: '반응 엔탈피 (Li⁺ 배위)',
    unit: 'kJ/mol',
    group: '열화학·반응',
    definition: '정의된 반응(Li⁺(sol) + B → [Li·B]⁺)의 ΔH.',
    caution: '절대 H의 조성 간 직접 비교 금지. ZPE·thermal correction·표준상태 저장.',
    direction: 'lower',
    radarMin: -120,
    radarMax: 0,
  },
  {
    key: 'binder_gibbs_free_energy_ion_exchange',
    label: '이온교환 Gibbs 자유에너지',
    unit: 'kJ/mol',
    group: '열화학·반응',
    definition: '정의된 교환 반응의 ΔG. 반응식·기준 상태와 함께 저장.',
    caution: '교환 전후 종, charge/spin, solvent, 농도 기준 필수.',
    direction: 'lower',
    radarMin: -60,
    radarMax: 10,
  },
  {
    key: 'binder_solvation_free_energy',
    label: '용매화 자유에너지',
    unit: 'kJ/mol',
    group: '열화학·반응',
    definition: '선택한 용매 모델에서의 ΔG_solv. 용매 친화성·redox·ion binding 해석에 사용.',
    caution: '용매 모델·온도에 종속. 기체상 계산에서는 산출되지 않음.',
    direction: 'lower',
    radarMin: -60,
    radarMax: 0,
  },
  {
    key: 'binder_li_binding_energy',
    label: 'Li⁺ 결합 에너지',
    unit: 'kJ/mol',
    group: '이온 결합',
    definition: 'Li⁺-binder 복합체의 결합 에너지. 더 음수 = 해당 프로토콜에서 강한 결합.',
    caution: 'coordination site·conformer 다중 탐색, Li-O/N 거리 표시.',
    direction: 'lower',
    radarMin: -180,
    radarMax: -20,
  },
  {
    key: 'binder_pf6_binding_energy',
    label: 'PF₆⁻ 결합 에너지',
    unit: 'kJ/mol',
    group: '이온 결합',
    definition: 'ΔE = E(complex) − E(binder) − E(PF₆⁻).',
    caution: '초기 모티프, counterpoise/BSSE, solvent, charge/spin 필요.',
    direction: 'lower',
    radarMin: -80,
    radarMax: 0,
  },
  {
    key: 'binder_binder_hbond_energy',
    label: 'Binder-Binder 수소결합 에너지',
    unit: 'kJ/mol',
    group: '재료 결합',
    definition: '두 binder 분자의 dimer 형성 에너지.',
    caution: 'donor/acceptor motif, BSSE, solvent 저장. 자기응집 경향의 일부만 설명.',
    direction: 'lower',
    radarMin: -60,
    radarMax: 0,
  },
  {
    key: 'binder_si_binding_energy',
    label: 'Si 결합 에너지',
    unit: 'kJ/mol',
    group: '재료 결합',
    definition: 'Si 모델(cluster/slab)과의 결합 에너지.',
    caution: 'Si 모델(atom/cluster/slab/passivated)이 다르면 값 비교 금지.',
    direction: 'lower',
    radarMin: -160,
    radarMax: -10,
  },
  {
    key: 'binder_surface_charge_density',
    label: '표면 전하 밀도',
    unit: 'C/m²',
    group: '계면·실험',
    definition: '표면/입자 모델의 순전하 또는 부분전하를 면적으로 정규화.',
    caution: 'surface model, 면적 정의, pH/전해질 조건 없이 제공 불가.',
    direction: 'none',
    radarMin: 0,
    radarMax: 1,
    interfacial: true,
  },
  {
    key: 'binder_zeta_potential',
    label: '제타 전위',
    unit: 'mV',
    group: '계면·실험',
    definition: '실험 또는 계면 모델 기반 값.',
    caution: 'pH, ionic strength, solvent, T, particle size, slip plane 정의 없이 단일 분자 DFT 값으로 제공 금지.',
    direction: 'none',
    radarMin: -60,
    radarMax: 60,
    interfacial: true,
  },
]

export const descriptorByKey = (key: string) => DESCRIPTORS.find((d) => d.key === key)

// 물성 지문 5축 스크리닝 프리셋 (안정성·Si 접착·극성·내산화성·용매화)
export const SCREENING_RADAR_PRESET = [
  'binder_homo_lumo_gap',
  'binder_si_binding_energy',
  'binder_dipole_moment',
  'binder_oxidation_potential',
  'binder_solvation_free_energy',
]

// 활물질 표면 흡착에너지 보조 키 (descriptor 사전 외 — 표면 모델 명시 전제의 보기용)
export const SURFACE_ADHESION_KEYS: { key: string; surface: string }[] = [
  { key: 'binder_adhesion_graphite', surface: 'Graphite' },
  { key: 'binder_adhesion_si', surface: 'Si' },
  { key: 'binder_adhesion_nmc811', surface: 'NMC811' },
  { key: 'binder_adhesion_lfp', surface: 'LFP' },
]

// DFT로 산출되는 항목 (계면·실험 제외) = 16개 중 계산 가능 셋
export const COMPUTED_KEYS = DESCRIPTORS.filter((d) => !d.interfacial).map((d) => d.key)
