import type { SolventPreset } from '../types'

// 기본 용매 라이브러리 (기획서 4.4)
export const BUILTIN_SOLVENTS: SolventPreset[] = [
  {
    id: 'sol-ec',
    kind: 'single',
    name: 'Ethylene carbonate',
    abbr: 'EC',
    smiles: 'O=C1OCCO1',
    formula: 'C3H4O3',
    modelKey: 'smd:ec',
    version: '1.0',
    builtin: true,
  },
  {
    id: 'sol-dmc',
    kind: 'single',
    name: 'Dimethyl carbonate',
    abbr: 'DMC',
    smiles: 'COC(=O)OC',
    formula: 'C3H6O3',
    modelKey: 'smd:dmc',
    version: '1.0',
    builtin: true,
  },
  {
    id: 'sol-emc',
    kind: 'single',
    name: 'Ethyl methyl carbonate',
    abbr: 'EMC',
    smiles: 'CCOC(=O)OC',
    formula: 'C4H8O3',
    modelKey: 'smd:emc',
    version: '1.0',
    builtin: true,
  },
  {
    id: 'sol-water',
    kind: 'single',
    name: 'Water',
    abbr: 'H2O',
    smiles: 'O',
    formula: 'H2O',
    modelKey: 'smd:water',
    version: '1.0',
    note: '수계 바인더 공정',
    builtin: true,
  },
  {
    id: 'sol-nmp',
    kind: 'single',
    name: 'N-Methyl-2-pyrrolidone',
    abbr: 'NMP',
    smiles: 'CN1CCCC1=O',
    formula: 'C5H9NO',
    modelKey: 'smd:nmp',
    version: '1.0',
    note: 'PVDF 등 유기계 공정',
    builtin: true,
  },
  {
    id: 'sol-ecdmc',
    kind: 'mixed',
    name: 'EC/DMC 1:1',
    abbr: 'EC/DMC',
    components: [
      { abbr: 'EC', ratio: 1 },
      { abbr: 'DMC', ratio: 1 },
    ],
    ratioBasis: '부피비',
    modelKey: 'smd:ec-dmc-11',
    version: '1.0',
    note: '표준 전해액 베이스',
    builtin: true,
  },
]

export function bumpVersion(v: string): string {
  const [major, minor] = v.split('.').map(Number)
  return `${major}.${(minor || 0) + 1}`
}
