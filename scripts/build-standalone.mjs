// dist/ 빌드 결과(JS·CSS)를 하나의 자립형 HTML 파일로 합친다.
// 사용법: npm run build && node scripts/build-standalone.mjs
// 결과: dft-workbench.html — 서버 없이 브라우저로 바로 열거나 어디든 호스팅 가능.
import { readFileSync, writeFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const assetsDir = join(root, 'dist', 'assets')
const files = readdirSync(assetsDir)
const cssFile = files.find((f) => f.endsWith('.css'))
const jsFile = files.find((f) => f.endsWith('.js'))
if (!cssFile || !jsFile) {
  console.error('dist/assets 에서 CSS/JS 를 찾지 못했습니다. 먼저 `npm run build` 를 실행하세요.')
  process.exit(1)
}

const css = readFileSync(join(assetsDir, cssFile), 'utf8')
let js = readFileSync(join(assetsDir, jsFile), 'utf8')
// 인라인 스크립트 안에서 </script> 조기 종료 방지
js = js.replaceAll('</script>', '<\\/script>')

const html = `<!doctype html>
<html lang="ko">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>바인더 분자 물성 · DFT 워크벤치</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>⚗️</text></svg>" />
<style>${css}</style>
</head>
<body>
<div id="root"></div>
<script type="module">${js}</script>
</body>
</html>
`

const out = join(root, 'dft-workbench.html')
writeFileSync(out, html)
const kb = (Buffer.byteLength(html) / 1024).toFixed(0)
console.log(`생성 완료: dft-workbench.html (${kb} KB) — 브라우저로 바로 열 수 있는 단일 파일`)
