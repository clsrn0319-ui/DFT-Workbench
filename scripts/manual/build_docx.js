// DFT-Workbench 사용 설명서 Word 파일 생성기
//   원본: web/manual_content.js (프로그램 안 «사용 설명서» 페이지와 같은 파일)
//   실행: cd scripts/manual && npm install && node build_docx.js
//   결과: docs/07_DFT-Workbench_사용설명서.docx
//   서버(Python)에는 필요 없다. 설명서 본문을 고친 뒤 Word 파일을 갱신할 때만 Node.js 로 실행한다.
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell,
  WidthType, ShadingType, AlignmentType, BorderStyle, LevelFormat, PageBreak,
  TableOfContents, PageNumber, Footer, Header, VerticalAlign,
} = require("docx");

const ROOT = path.resolve(__dirname, "..", "..");
const CONTENT = process.argv[2] || path.join(ROOT, "web", "manual_content.js");
const OUT = process.argv[3] || path.join(ROOT, "docs", "07_DFT-Workbench_사용설명서.docx");

function loadContent(file) {
  const text = fs.readFileSync(file, "utf8");
  const i = text.indexOf("window.RB_MANUAL");
  const j = text.indexOf("=", i);
  const body = text.slice(j + 1).trim().replace(/;\s*$/, "");
  return JSON.parse(body);
}
const M = loadContent(CONTENT);

const FONT = "Malgun Gothic", MONO = "Consolas";
const ACCENT = "0F766E", GREY = "6B7280", SHADE = "F3F4F6", HEAD_SHADE = "E6F2F0";
const PAGE_W = 11906, PAGE_H = 16838, MARGIN = 1250, CONTENT_W = PAGE_W - 2 * MARGIN;
const border = { style: BorderStyle.SINGLE, size: 4, color: "D1D5DB" };
const borders = { top: border, bottom: border, left: border, right: border };
const BASE = 21;

function runs(text, opts = {}) {
  const out = [], re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0, m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), ...opts }));
    const t = m[0];
    if (t.startsWith("**")) out.push(new TextRun({ text: t.slice(2, -2), bold: true, ...opts }));
    else out.push(new TextRun({ text: t.slice(1, -1), font: MONO, size: (opts.size || BASE) - 2, shading: { type: ShadingType.CLEAR, fill: SHADE, color: "auto" }, ...opts }));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), ...opts }));
  return out;
}
const P = (t, o = {}) => new Paragraph({ children: runs(t, o.run || {}), spacing: { after: 140, line: 340 }, ...(o.para || {}) });
const H1 = (t) => new Paragraph({ text: t, heading: HeadingLevel.HEADING_1, pageBreakBefore: true, spacing: { before: 0, after: 240 } });
const H2 = (t) => new Paragraph({ text: t, heading: HeadingLevel.HEADING_2, spacing: { before: 340, after: 150 } });
const H3 = (t) => new Paragraph({ text: t, heading: HeadingLevel.HEADING_3, spacing: { before: 240, after: 100 } });
const Bullet = (t) => new Paragraph({ children: runs(t), numbering: { reference: "bullets", level: 0 }, spacing: { after: 90, line: 330 } });
let stepSeq = 0; const numRefs = [];
function Steps(items) {
  const ref = "steps" + (++stepSeq); numRefs.push(ref);
  return items.map(t => new Paragraph({ children: runs(t), numbering: { reference: ref, level: 0 }, spacing: { after: 100, line: 330 } }));
}
function Box(title, text, color = ACCENT, fill = "F0FDFA") {
  return new Paragraph({
    children: [new TextRun({ text: title + "  ", bold: true, color, size: BASE }), ...runs(text, { size: BASE - 1, color: "374151" })],
    spacing: { before: 60, after: 180, line: 320 }, indent: { left: 240, right: 120 },
    border: { left: { style: BorderStyle.SINGLE, size: 20, color, space: 10 } },
    shading: { type: ShadingType.CLEAR, fill, color: "auto" },
  });
}
const Tip = (t) => Box("TIP", t);
const Warn = (t) => Box("주의", t, "B45309", "FFF7ED");
function Code(lines) {
  return lines.map(l => new Paragraph({ children: [new TextRun({ text: l, font: MONO, size: BASE - 2 })], shading: { type: ShadingType.CLEAR, fill: SHADE, color: "auto" }, spacing: { after: 0, line: 280 }, indent: { left: 240, right: 240 } }))
    .concat([new Paragraph({ text: "", spacing: { after: 120 } })]);
}
function Tbl(headers, rows, widths, opts = {}) {
  const total = widths.reduce((a, b) => a + b, 0);
  const cols = widths.map(w => Math.round(w / total * CONTENT_W));
  const size = opts.size || BASE - 1;
  const cell = (text, head, w, fill) => new TableCell({
    width: { size: w, type: WidthType.DXA }, borders, verticalAlign: VerticalAlign.CENTER,
    shading: (head || fill) ? { type: ShadingType.CLEAR, fill: head ? HEAD_SHADE : fill, color: "auto" } : undefined,
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    children: [new Paragraph({ children: runs(String(text), { size, bold: head }), spacing: { after: 0, line: 290 } })],
  });
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: cols,
    rows: [new TableRow({ tableHeader: true, children: headers.map((h, i) => cell(h, true, cols[i])) }),
      ...rows.map(r => new TableRow({ children: r.map((c, i) => cell(c, false, cols[i], opts.firstColFill !== false && i === 0 ? "FAFAF9" : undefined)) }))],
  });
}
const Gap = (n = 120) => new Paragraph({ text: "", spacing: { after: n } });

function block(b) {
  switch (b.t) {
    case "p": return [P(b.text)];
    case "h2": return [H2(b.title)];
    case "h3": return [H3(b.title)];
    case "ul": return b.items.map(Bullet);
    case "ol": return Steps(b.items);
    case "tip": return [Tip(b.text)];
    case "warn": return [Warn(b.text)];
    case "code": return Code(b.lines);
    case "table": return [Tbl(b.headers, b.rows, b.widths, { firstColFill: !b.plain })];
    case "qa": return [P("**Q. " + b.q + "**", { para: { spacing: { before: 200, after: 60 } } }), P(b.a)];
    default: throw new Error("unknown block type " + b.t);
  }
}
function chapterTitle(ch) {
  return /^[A-Z]$/.test(ch.num) ? "부록 " + ch.num + ". " + ch.title : ch.num + ". " + ch.title;
}

const body = [];
const add = (...x) => body.push(...x.flat());
const ver = M.version + " (" + M.date + ")";

// 표지 · 차례
add(
  new Paragraph({ text: "", spacing: { before: 2800 } }),
  new Paragraph({ children: [new TextRun({ text: "DFT-Workbench", size: 64, bold: true, color: ACCENT })], spacing: { after: 160 } }),
  new Paragraph({ children: [new TextRun({ text: "사용 설명서", size: 40, bold: true })], spacing: { after: 360 } }),
  new Paragraph({ children: [new TextRun({ text: M.subtitle, size: 24, color: GREY })], spacing: { after: 100 } }),
  new Paragraph({ children: [new TextRun({ text: M.tagline, size: 24, color: GREY })], spacing: { after: 2400 } }),
  Tbl(["", ""], [["문서 버전", ver], ["대상", M.audience], ["기본 접속 주소", M.url]], [1, 3], { firstColFill: false }),
  new Paragraph({ children: [new PageBreak()] }),
  new Paragraph({ text: "차례", heading: HeadingLevel.HEADING_1, spacing: { after: 240 } }),
  new TableOfContents("차례", { hyperlink: true, headingStyleRange: "1-2" }),
  Gap(200),
  Tip("Word에서 열었을 때 «필드를 업데이트하시겠습니까?»가 뜨면 «예»를 누르세요. 차례의 쪽 번호가 채워집니다."),
);
M.chapters.forEach(ch => {
  add(H1(chapterTitle(ch)));
  ch.blocks.forEach(b => add(block(b)));
});

const numbering = { config: [
  { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 520, hanging: 300 } } } }] },
  ...numRefs.map(ref => ({ reference: ref, levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1", alignment: AlignmentType.LEFT,
    style: { run: { bold: true, color: ACCENT }, paragraph: { indent: { left: 560, hanging: 380 } } } }] })),
] };
const doc = new Document({
  creator: "DFT-Workbench", title: M.title,
  styles: {
    default: { document: { run: { font: FONT, size: BASE } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 38, bold: true, color: ACCENT, font: FONT }, paragraph: { spacing: { before: 240, after: 240 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 27, bold: true, color: "111827", font: FONT }, paragraph: { spacing: { before: 340, after: 150 }, outlineLevel: 1, border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "D1D5DB", space: 4 } } } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 23, bold: true, color: "374151", font: FONT }, paragraph: { spacing: { before: 240, after: 100 }, outlineLevel: 2 } },
    ],
  },
  numbering, features: { updateFields: true },
  sections: [{
    properties: { page: { size: { width: PAGE_W, height: PAGE_H }, margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN } } },
    headers: { default: new Header({ children: [new Paragraph({ children: [new TextRun({ text: M.title + " v" + M.version, size: 16, color: GREY })], alignment: AlignmentType.RIGHT })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ children: [new TextRun({ children: [PageNumber.CURRENT], size: 16, color: GREY })], alignment: AlignmentType.CENTER })] }) },
    children: body,
  }],
});
Packer.toBuffer(doc).then(buf => { fs.writeFileSync(OUT, buf); console.log("written", OUT, buf.length, "bytes"); });
