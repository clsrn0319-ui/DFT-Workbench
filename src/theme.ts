import type { ThemeTokens } from './types'

// 기본 상용 테마: 순백 배경 + 옅은 회색 테두리 + 딥 틸 + 앰버 pin (기획서 9.1·14.1)
export const DEFAULT_THEME: ThemeTokens = {
  mode: 'light',
  background: '#ffffff',
  card: '#ffffff',
  border: '#e5e5e0',
  accent: '#0f766e',
  pin: '#d97706',
  chartSeries: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948'],
  mepNegative: '#2a78d6',
  mepPositive: '#e34948',
}

export const COLORBLIND_PRESET: Partial<ThemeTokens> = {
  chartSeries: ['#0072b2', '#e69f00', '#009e73', '#cc79a7', '#56b4e9', '#d55e00', '#f0e442', '#000000'],
}

export const DARK_PRESET: Partial<ThemeTokens> = {
  mode: 'dark',
  background: '#111110',
  card: '#1a1a19',
  border: '#2c2c2a',
  chartSeries: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'],
}

export function applyTheme(t: ThemeTokens) {
  const root = document.documentElement
  const dark = t.mode === 'dark'
  root.dataset.mode = t.mode
  const set = (k: string, v: string) => root.style.setProperty(k, v)
  set('--page', t.background)
  set('--surface', t.card)
  set('--border', t.border)
  set('--accent', t.accent)
  set('--pin', t.pin)
  set('--mep-neg', t.mepNegative)
  set('--mep-pos', t.mepPositive)
  t.chartSeries.forEach((c, i) => set(`--series-${i + 1}`, c))
  if (t.mode === 'high-contrast') {
    set('--text-1', '#000000')
    set('--text-2', '#000000')
    set('--muted', '#333333')
    set('--grid', '#999999')
    set('--border', '#000000')
  } else if (dark) {
    set('--text-1', '#ffffff')
    set('--text-2', '#c3c2b7')
    set('--muted', '#898781')
    set('--grid', '#2c2c2a')
  } else {
    set('--text-1', '#171716')
    set('--text-2', '#52514e')
    set('--muted', '#898781')
    set('--grid', '#ececea')
  }
}

// WCAG 상대 휘도 기반 대비 검사 (기획서 14.4)
export function contrastRatio(hex1: string, hex2: string): number {
  const lum = (hex: string) => {
    const m = hex.replace('#', '')
    const full = m.length === 3 ? m.split('').map((c) => c + c).join('') : m
    const [r, g, b] = [0, 2, 4].map((i) => {
      const v = parseInt(full.slice(i, i + 2), 16) / 255
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)
    })
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
  }
  const [a, b] = [lum(hex1), lum(hex2)]
  return +((Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)).toFixed(2)
}
