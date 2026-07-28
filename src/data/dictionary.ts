// 내장 물질 사전 (기획서 4.2.2 검색 1순위 경로)
// 상용 버전에서는 백엔드 검색 프록시(PubChem 캐시)가 이 사전을 보강한다.

export interface DictEntry {
  dictId: string
  name: string
  korName: string
  casNo: string
  smiles: string
  formula: string
  mw: number
  type: '바인더 모노머' | '용매' | '첨가제' | '염' | '기타'
  synonyms: string[]
  functionalGroups: string[] // 작용기 자동 인식 결과 (SMARTS 서버 검출 대체)
  trends: string[] // 구조 기반 물성 경향 (해석 계층)
  cautions: string[] // 구조만으로 확정 불가 항목
  // 모의 엔진 기준값 (B3LYP/def2-TZVP·기체상 기준의 데모용 근사치)
  base: {
    homo: number
    lumo: number
    dipole: number
    alpha: number
    liBind: number // kJ/mol
    hbd: number
    hba: number
  }
}

export const DICTIONARY: DictEntry[] = [
  {
    dictId: 'vdf',
    name: 'Vinylidene fluoride (PVDF monomer)',
    korName: '비닐리덴 플루오라이드',
    casNo: '75-38-7',
    smiles: 'C=C(F)F',
    formula: 'C2H2F2',
    mw: 64.03,
    type: '바인더 모노머',
    synonyms: ['VDF', 'PVDF', '1,1-difluoroethylene'],
    functionalGroups: ['C=C 비닐기', 'C–F 결합 ×2'],
    trends: ['불소로 인한 낮은 HOMO — 내산화성 우수 가능성', '낮은 극성 표면 에너지', 'H-bond 공여 부위 없음'],
    cautions: ['결정성·압전성 등 고분자 벌크 물성은 단량체 계산으로 확정 불가'],
    base: { homo: -8.72, lumo: 0.94, dipole: 1.39, alpha: 24.1, liBind: -68, hbd: 0, hba: 0 },
  },
  {
    dictId: 'tfe',
    name: 'Tetrafluoroethylene (PTFE monomer)',
    korName: '테트라플루오로에틸렌',
    casNo: '116-14-3',
    smiles: 'FC(F)=C(F)F',
    formula: 'C2F4',
    mw: 100.02,
    type: '바인더 모노머',
    synonyms: ['TFE', 'PTFE'],
    functionalGroups: ['C=C 비닐기', 'C–F 결합 ×4'],
    trends: ['전불소화 — 매우 낮은 HOMO, 넓은 안정 범위 기대', '무극성, 흡착·용매화 약함'],
    cautions: ['피브릴화 등 공정 물성은 계산 범위 밖'],
    base: { homo: -9.61, lumo: 0.81, dipole: 0.0, alpha: 27.9, liBind: -42, hbd: 0, hba: 0 },
  },
  {
    dictId: 'styrene',
    name: 'Styrene (SBR monomer)',
    korName: '스타이렌',
    casNo: '100-42-5',
    smiles: 'C=Cc1ccccc1',
    formula: 'C8H8',
    mw: 104.15,
    type: '바인더 모노머',
    synonyms: ['SBR', 'vinylbenzene'],
    functionalGroups: ['C=C 비닐기', '방향족 고리(벤젠)'],
    trends: ['공액 π계 — 높은 HOMO, 산화에 상대적으로 민감', '분산(π–π) 상호작용으로 흑연 친화 가능성'],
    cautions: ['SBR 공중합 조성비에 따른 물성은 별도 계산 필요'],
    base: { homo: -6.68, lumo: -0.38, dipole: 0.42, alpha: 84.3, liBind: -74, hbd: 0, hba: 0 },
  },
  {
    dictId: 'aa',
    name: 'Acrylic acid (PAA monomer)',
    korName: '아크릴산',
    casNo: '79-10-7',
    smiles: 'C=CC(=O)O',
    formula: 'C3H4O2',
    mw: 72.06,
    type: '바인더 모노머',
    synonyms: ['PAA', 'prop-2-enoic acid'],
    functionalGroups: ['C=C 비닐기', '카복실산 –COOH', '카보닐 C=O'],
    trends: ['카복실기 — 강한 H-bond 공여/수용', 'O 주변 음전위 집중 — Li⁺ 배위 후보', '높은 극성·수계 친화'],
    cautions: ['탈양성자화 상태(pH 의존)는 별도 화학 상태로 계산'],
    base: { homo: -7.43, lumo: -0.41, dipole: 1.88, alpha: 40.6, liBind: -122, hbd: 1, hba: 2 },
  },
  {
    dictId: 'liacrylate',
    name: 'Lithium acrylate (LiPAA monomer)',
    korName: '아크릴산 리튬',
    casNo: '13270-28-5',
    smiles: 'C=CC(=O)[O-].[Li+]',
    formula: 'C3H3LiO2',
    mw: 78.0,
    type: '바인더 모노머',
    synonyms: ['LiPAA'],
    functionalGroups: ['C=C 비닐기', '카복실레이트 –COO⁻', '이온쌍(Li⁺)'],
    trends: ['음이온성 — 매우 강한 음전위, Li⁺ 강배위', '이온성 응집·수계 분산'],
    cautions: ['이온쌍 해리 상태는 용매·농도 의존 — 명시적 용매 검토 권장'],
    base: { homo: -6.94, lumo: 0.22, dipole: 6.71, alpha: 44.8, liBind: -152, hbd: 0, hba: 2 },
  },
  {
    dictId: 'an',
    name: 'Acrylonitrile (PAN monomer)',
    korName: '아크릴로니트릴',
    casNo: '107-13-1',
    smiles: 'C=CC#N',
    formula: 'C3H3N',
    mw: 53.06,
    type: '바인더 모노머',
    synonyms: ['PAN', 'AN', 'vinyl cyanide'],
    functionalGroups: ['C=C 비닐기', '니트릴 –C≡N'],
    trends: ['니트릴 극성기 — 큰 쌍극자', '낮은 LUMO — 환원 민감 가능성', 'N 고립전자쌍 Li⁺ 배위 후보'],
    cautions: ['전기화학 환원 분해 경로는 반응 계산으로 확인 필요'],
    base: { homo: -8.03, lumo: -0.62, dipole: 3.92, alpha: 38.2, liBind: -95, hbd: 0, hba: 1 },
  },
  {
    dictId: 'nvp',
    name: 'N-vinylpyrrolidone (PVP monomer)',
    korName: 'N-비닐피롤리돈',
    casNo: '88-12-0',
    smiles: 'C=CN1CCCC1=O',
    formula: 'C6H9NO',
    mw: 111.14,
    type: '바인더 모노머',
    synonyms: ['PVP', 'NVP'],
    functionalGroups: ['C=C 비닐기', '락탐(고리 아마이드)', '카보닐 C=O'],
    trends: ['아마이드 O 음전위 — Li⁺ 배위·H-bond 수용', '높은 극성, 수계·NMP 겸용 분산'],
    cautions: ['분산제 성능은 입자·용매 조건 의존'],
    base: { homo: -6.61, lumo: 0.18, dipole: 4.12, alpha: 74.5, liBind: -118, hbd: 0, hba: 1 },
  },
  {
    dictId: 'va',
    name: 'Vinyl alcohol (PVA unit)',
    korName: '비닐 알코올',
    casNo: '557-75-5',
    smiles: 'C=CO',
    formula: 'C2H4O',
    mw: 44.05,
    type: '바인더 모노머',
    synonyms: ['PVA'],
    functionalGroups: ['C=C 비닐기', '하이드록실 –OH'],
    trends: ['–OH H-bond 공여·수용 — 접착·수계 친화', '중간 극성'],
    cautions: ['실제 PVA는 초산비닐 가수분해물 — 잔류 아세테이트 영향 별도'],
    base: { homo: -7.08, lumo: 0.53, dipole: 1.67, alpha: 27.3, liBind: -98, hbd: 1, hba: 1 },
  },
  {
    dictId: 'cmc-unit',
    name: 'Carboxymethyl glucose (CMC unit)',
    korName: '카복시메틸 글루코스 단위',
    casNo: '',
    smiles: 'OCC1OC(OCC(=O)O)C(O)C(O)C1O',
    formula: 'C8H14O8',
    mw: 240.2,
    type: '바인더 모노머',
    synonyms: ['CMC'],
    functionalGroups: ['카복실산 –COOH', '하이드록실 –OH ×4', '에테르 고리(피라노스)'],
    trends: ['다중 –OH/–COOH — 매우 강한 H-bond 네트워크', '수계 증점·강한 표면 흡착 가능성'],
    cautions: ['치환도(DS)에 따른 실제 CMC 물성 분포는 단위 구조로 확정 불가'],
    base: { homo: -7.21, lumo: 0.31, dipole: 3.86, alpha: 132.4, liBind: -138, hbd: 5, hba: 8 },
  },
  {
    dictId: 'mma',
    name: 'Methyl methacrylate',
    korName: '메틸 메타크릴레이트',
    casNo: '80-62-6',
    smiles: 'CC(=C)C(=O)OC',
    formula: 'C5H8O2',
    mw: 100.12,
    type: '바인더 모노머',
    synonyms: ['MMA', 'PMMA'],
    functionalGroups: ['C=C 비닐기', '에스터 –C(=O)O–', '카보닐 C=O'],
    trends: ['에스터 O 음전위 — Li⁺ 배위 후보', '중간 극성, 유기용매 친화'],
    cautions: ['가수분해 안정성은 조건 의존'],
    base: { homo: -7.31, lumo: 0.12, dipole: 1.96, alpha: 58.9, liBind: -108, hbd: 0, hba: 2 },
  },
  {
    dictId: 'ec',
    name: 'Ethylene carbonate',
    korName: '에틸렌 카보네이트',
    casNo: '96-49-1',
    smiles: 'O=C1OCCO1',
    formula: 'C3H4O3',
    mw: 88.06,
    type: '용매',
    synonyms: ['EC'],
    functionalGroups: ['고리형 카보네이트', '카보닐 C=O'],
    trends: ['카보닐 O 강한 음전위 — Li⁺ 용매화 주역', '높은 유전율·점도'],
    cautions: ['SEI 형성 경로는 환원 분해 반응 계산 필요'],
    base: { homo: -8.41, lumo: 0.47, dipole: 5.35, alpha: 44.2, liBind: -128, hbd: 0, hba: 3 },
  },
  {
    dictId: 'dmc',
    name: 'Dimethyl carbonate',
    korName: '다이메틸 카보네이트',
    casNo: '616-38-6',
    smiles: 'COC(=O)OC',
    formula: 'C3H6O3',
    mw: 90.08,
    type: '용매',
    synonyms: ['DMC'],
    functionalGroups: ['선형 카보네이트', '카보닐 C=O'],
    trends: ['낮은 점도 — 혼합 용매의 유동성 담당', 'EC 대비 약한 Li⁺ 배위'],
    cautions: [],
    base: { homo: -8.15, lumo: 0.61, dipole: 0.91, alpha: 47.6, liBind: -102, hbd: 0, hba: 3 },
  },
  {
    dictId: 'vc',
    name: 'Vinylene carbonate',
    korName: '비닐렌 카보네이트',
    casNo: '872-36-6',
    smiles: 'O=C1OC=CO1',
    formula: 'C3H2O3',
    mw: 86.05,
    type: '첨가제',
    synonyms: ['VC'],
    functionalGroups: ['고리형 카보네이트', 'C=C(고리 내)', '카보닐 C=O'],
    trends: ['공액으로 낮은 LUMO — 우선 환원(SEI 첨가제) 후보'],
    cautions: ['첨가제 성능은 농도·조합 의존'],
    base: { homo: -7.62, lumo: -0.45, dipole: 4.57, alpha: 41.8, liBind: -112, hbd: 0, hba: 3 },
  },
]

export function searchDictionary(query: string): DictEntry[] {
  const q = query.trim().toLowerCase()
  if (!q) return []
  return DICTIONARY.filter(
    (e) =>
      e.name.toLowerCase().includes(q) ||
      e.korName.includes(query.trim()) ||
      e.casNo === q ||
      e.smiles.toLowerCase() === q ||
      e.synonyms.some((s) => s.toLowerCase().includes(q)),
  )
}

// CAS 형식·확인 숫자 검증 (기획서 4.2.4)
export function validateCas(cas: string): boolean {
  const m = cas.match(/^(\d{2,7})-(\d{2})-(\d)$/)
  if (!m) return false
  const digits = (m[1] + m[2]).split('').reverse()
  const sum = digits.reduce((s, d, i) => s + parseInt(d) * (i + 1), 0)
  return sum % 10 === parseInt(m[3])
}
