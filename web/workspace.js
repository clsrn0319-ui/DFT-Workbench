/* ------------------------------------------------------------------
   결과 워크스페이스 — B타입 탭 기반 상세 분석형 (기획서 «QuantumLab B타입 DFT 계산결과 화면»)
     · 헤더(분자·상태·방법·환경·Download·Compare·오비탈 비교) · QC 배지 줄
     · 탭: Summary / Geometry / Orbitals / Frequencies / Spectra / Thermodynamics / Charge & Reactivity / Files & Logs
     · Geometry: Optimized Geometry 뷰어(선택·측정·라벨·전체화면·PNG) · Molecular Orbitals 뷰어(HOMO−1/HOMO/LUMO/LUMO+1·
       전자밀도·ESP, 문턱·불투명도·카메라 동기화) · Orbital Information · XYZ 표 · 궤도 준위도 · Additional Views
     · Orbitals: 오비탈 비교 화면(4분할·준위도·특성표·전이 분석)을 그대로 내장 — «오비탈 비교» 메뉴와 같은 코드
     · 궤도·전자밀도는 격자(/api/jobs/{id}/grids)가 있으면 등가면(isosurface.js · marching tetrahedra · 조명)으로,
       없으면(이전 결과·배치) 점 구름으로 그린다
     · 원자 클릭 상세 카드, 원자 2~4개 측정(거리·각도·이면각)
   app.js 뒤에 로드되어 showResult / render3D 를 정의한다 ($, esc, fmt, svg* 는 app.js 전역).
   ------------------------------------------------------------------ */

/* ── 뷰어 상태 (재렌더 사이에 유지) ── */
const WS = {tool: "select", labels: false, sel: null, measure: [], yaw: 0.6, pitch: -0.4, zoom: 1,
            iso: 0.03, alpha: 0.7, tab: "geometry",
            // Geometry 탭 두 번째 뷰어(Molecular Orbitals) 상태 — 자체 카메라, 구조 뷰어와 동기화 가능
            mo: {mode: "homo", iso: 0.03, alpha: 0.7, style: "iso", labels: false, sync: true, cam: {yaw: 0.6, pitch: -0.4, zoom: 1}},
            redraw: null, moRedraw: null};
const WS_MODES = [
  ["element", "구조"], ["homo", "HOMO"], ["lumo", "LUMO"], ["cloud", "전자밀도"],
  ["mep", "정전위(ESP)"], ["charge", "부분 전하"]];
const RB_PREFS_KEY = "rb-prefs";
function rbPrefs() { try { return JSON.parse(localStorage.getItem(RB_PREFS_KEY) || "{}") || {}; } catch (e) { return {}; } }
function rbSavePrefs(p) { try { localStorage.setItem(RB_PREFS_KEY, JSON.stringify(p)); } catch (e) {} }
/* 에너지 단위 환산 (설정 → 에너지 단위) */
function fmtE(ev) {
  if (ev == null) return "—";
  const u = rbPrefs().energyUnit || "eV";
  if (u === "Hartree") return (ev / 27.211386).toFixed(4);
  if (u === "kJ/mol") return (ev * 96.485).toFixed(1);
  return fmt(ev);
}
function unitE() { return rbPrefs().energyUnit || "eV"; }

function parseXyz(xyz) {
  const atoms = [];
  const lines = (xyz || "").trim().split("\n");
  for (let i = 2; i < lines.length; i++) {
    const t = lines[i].trim().split(/\s+/);
    if (t.length >= 4) atoms.push({el: t[0], x: +t[1], y: +t[2], z: +t[3]});
  }
  return atoms;
}
const RCOV = {H:.31,C:.76,N:.71,O:.66,F:.57,S:1.05,P:1.07,Cl:1.02,Br:1.2,I:1.39,Li:1.28};
function bondList(atoms) {
  const rad = el => RCOV[el] ?? .8, bonds = [];
  for (let i = 0; i < atoms.length; i++) for (let j = i + 1; j < atoms.length; j++) {
    const a = atoms[i], b = atoms[j], dd = Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
    if (dd < (rad(a.el) + rad(b.el)) * 1.25 && dd > 0.4) bonds.push([i, j, dd]);
  }
  return bonds;
}
function vAngle(a, b, c) {   // b 가 꼭짓점
  const u = [a.x - b.x, a.y - b.y, a.z - b.z], v = [c.x - b.x, c.y - b.y, c.z - b.z];
  const d = u[0] * v[0] + u[1] * v[1] + u[2] * v[2], n = Math.hypot(...u) * Math.hypot(...v) || 1;
  return Math.acos(Math.max(-1, Math.min(1, d / n))) * 180 / Math.PI;
}
function vDihedral(p0, p1, p2, p3) {
  const b0 = [p0.x - p1.x, p0.y - p1.y, p0.z - p1.z], b1 = [p2.x - p1.x, p2.y - p1.y, p2.z - p1.z], b2 = [p3.x - p2.x, p3.y - p2.y, p3.z - p2.z];
  const n1 = Math.hypot(...b1) || 1, b1n = b1.map(v => v / n1);
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const v = b0.map((x, i) => x - dot(b0, b1n) * b1n[i]), w = b2.map((x, i) => x - dot(b2, b1n) * b1n[i]);
  const cross = [b1n[1] * v[2] - b1n[2] * v[1], b1n[2] * v[0] - b1n[0] * v[2], b1n[0] * v[1] - b1n[1] * v[0]];
  return Math.atan2(dot(cross, w), dot(v, w)) * 180 / Math.PI;
}

/* ── 3D 렌더러 — 뷰어 · 썸네일 · 궤도 미리보기 공용 ── */
function render3D(r, opts = {}) {
  const box = opts.box || $("viewer3d");
  if (!box) return;
  const mode = opts.mode || VIEW_MODE;
  const isStatic = !!opts.static;
  const V = opts.view || WS;                 // 표시 옵션(iso · alpha · style · labels)
  const cam = opts.cam || WS;                // 카메라(yaw · pitch · zoom) — 같은 객체를 주면 뷰어끼리 동기화
  const isMain = box.id === "viewer3d";
  const atoms = parseXyz(r.structure_xyz);
  if (!atoms.length) { box.style.display = "none"; return; }
  const charges = r.mulliken_charges || [];
  const qmax = Math.max(...charges.map(Math.abs), 0.01);
  const solventIdx = new Set();
  if (r.fragments && r.fragments.length > 1) for (const f of r.fragments.slice(1)) for (let i = f.start; i < f.end; i++) solventIdx.add(i);
  const mepPts = r.descriptors?.mep_points;
  const cloud = r.density_cloud;
  const orb = ORB_MODES.has(mode) ? (r.orbital_clouds || {})[mode] : null;
  // 등가면 격자 — /api/jobs/{id}/grids 에서 받아 r.grids 에 붙여 둔다 (wsLoadGrids). 없으면 점 구름으로 그린다.
  const G = r.grids || null;
  const gridOrb = G && ORB_MODES.has(mode) ? G[mode] : null;
  const gridRho = G && (mode === "cloud" || mode === "mep") ? G.density : null;
  const useIso = !!(window.rbIso && (gridOrb || gridRho) && V.style !== "cloud" && V.style !== "none");
  const bonds = bondList(atoms);
  const cx = atoms.reduce((s, a) => s + a.x, 0) / atoms.length, cy = atoms.reduce((s, a) => s + a.y, 0) / atoms.length, cz = atoms.reduce((s, a) => s + a.z, 0) / atoms.length;
  const span = Math.max(...atoms.map(a => Math.hypot(a.x - cx, a.y - cy, a.z - cz)), 1.5);
  // 정전위 근사: 밀도 구름의 각 점을 가장 가까운 원자의 부분 전하 색으로 (MEP 격자 저장 없이 표현)
  let mepColor = null;
  if (mode === "mep" && cloud) {
    mepColor = cloud.points.map(p => {
      let best = 0, bd = 1e9;
      for (let i = 0; i < atoms.length; i++) { const d = Math.hypot(p[0] - atoms[i].x, p[1] - atoms[i].y, p[2] - atoms[i].z); if (d < bd) { bd = d; best = i; } }
      return charges[best] ?? 0;
    });
  }

  if (!isStatic && isMain) {
    const note = $("viewer3d-note"), legend = $("viewer3d-legend");
    const base = solventIdx.size ? "선명한 분자 = 용질 · 흐린 분자 = 명시적 주변 분자 · " : "";
    const notes = {
      element: "드래그 회전 · 휠 확대 · 원자 클릭 = 상세 카드 (측정 도구: 원자 2~4개 선택)",
      charge: "부분 전하(Mulliken): 파랑 = 음전하(친핵 부위) · 빨강 = 양전하(친전자 부위)",
      cloud: cloud ? "전자구름: 점의 밀집도 ∝ 전자 밀도 ρ(r)" : (r.slimmed ? "배치 결과는 용량 절약을 위해 점 데이터를 저장하지 않습니다 — «계산»에서 단건으로 다시 계산하면 표시됩니다." : "이 결과에는 전자밀도 데이터가 없습니다 (이전 버전 계산). 다시 계산하면 표시됩니다."),
      ...Object.fromEntries(ORB_ORDER.map(k => [k, orb ? `${ORB_LABEL[k]} ${fmt(orb.energy_ev)} eV · 붉은 점 = + 위상, 파란 점 = − 위상 · 점 크기 ∝ |ψ|` : "이 결과에는 궤도 데이터가 없습니다 (이전 버전 계산 또는 배치 결과). 다시 계산하면 표시됩니다."])),
      mep: cloud ? "정전위(ESP) 근사: 전자밀도 표면을 가까운 원자의 부분 전하로 색칠 · MEP−/MEP+ 극값은 표식으로" : "정전위 표면을 그리려면 전자밀도 데이터가 필요합니다.",
    };
    if (note) note.textContent = base + (notes[mode] || notes.element);
    if (legend) {
      if (mode === "element") legend.innerHTML = [...new Set(atoms.map(a => a.el))].map(el => `<span class="legend-item"><span class="legend-swatch" style="background:${COLOR[el] ?? "#888"};border:1px solid rgba(0,0,0,.15)"></span>${esc(el)}</span>`).join("");
      else if (mode === "charge" || mode === "mep") legend.innerHTML = `<span class="legend-item"><span class="legend-swatch" style="background:rgb(75,145,216)"></span>음전하 · MEP−</span><span class="legend-item"><span class="legend-swatch" style="background:#fff;border:1px solid var(--border)"></span>중성</span><span class="legend-item"><span class="legend-swatch" style="background:rgb(214,45,40)"></span>양전하 · MEP+</span>`;
      else if (ORB_MODES.has(mode)) legend.innerHTML = `<span class="legend-item"><span class="legend-swatch" style="background:#e0663e"></span>+ lobe</span><span class="legend-item"><span class="legend-swatch" style="background:#2a78d6"></span>− lobe</span>`;
      else legend.innerHTML = `<span class="legend-item">점이 촘촘할수록 전자 밀도 ρ(r)가 높은 영역</span>`;
    }
  }

  box.innerHTML = "";
  const canvas = document.createElement("canvas");
  canvas.style.width = "100%"; canvas.style.height = "100%"; canvas.style.cursor = isStatic ? "default" : "grab";
  box.appendChild(canvas);
  const ctx = canvas.getContext("2d");
  let yaw = isStatic ? 0.5 : cam.yaw, pitch = isStatic ? -0.45 : cam.pitch, zoom = isStatic ? 1.05 : cam.zoom;
  let proj = [];
  const rad = el => RCOV[el] ?? .8;

  function project(x, y, z, W, H, scale) {
    const cyaw = Math.cos(yaw), syaw = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
    const x0 = x - cx, y0 = y - cy, z0 = z - cz;
    const x1 = x0 * cyaw + z0 * syaw, z1 = -x0 * syaw + z0 * cyaw;
    const y2 = y0 * cp - z1 * sp, z2 = y0 * sp + z1 * cp;
    return {sx: W / 2 + x1 * scale, sy: H / 2 - y2 * scale, z: z2};
  }
  function draw() {
    if (!isStatic) { yaw = cam.yaw; pitch = cam.pitch; zoom = cam.zoom; }   // 동기화된 다른 뷰어가 바꾼 카메라 반영
    const dpr = window.devicePixelRatio || 1;
    const W = box.clientWidth || 100, H = box.clientHeight || 100;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const scale = Math.min(W, H) / (span * (isStatic ? 2.3 : 2.6)) * zoom;
    proj = atoms.map((a, i) => ({i, el: a.el, ...project(a.x, a.y, a.z, W, H, scale)}));
    const cloudMode = mode === "cloud" || mode === "mep" || ORB_MODES.has(mode);
    for (const [i, j] of bonds) {
      const p = proj[i], q = proj[j], faded = solventIdx.has(i) || solventIdx.has(j);
      ctx.strokeStyle = faded ? "rgba(140,140,140,.45)" : (useIso ? "rgba(70,70,70,.9)" : cloudMode ? "rgba(60,60,60,.55)" : "rgba(90,90,90,.9)");
      ctx.lineWidth = faded ? 1.4 : (useIso ? (isStatic ? 1.6 : 2.4) : cloudMode ? 1.4 : (isStatic ? 1.6 : 2.6));
      ctx.beginPath(); ctx.moveTo(p.sx, p.sy); ctx.lineTo(q.sx, q.sy); ctx.stroke();
    }
    // 점 구름: 전자밀도 / 정전위 / 궤도
    if ((mode === "cloud" || mode === "mep") && cloud && !useIso) {
      const rmax = cloud.rho_max || 1;
      const pts = cloud.points.map((q, i) => ({...project(q[0], q[1], q[2], W, H, scale), rho: cloud.rho[i], q: mepColor ? mepColor[i] : 0})).sort((a, b) => a.z - b.z);
      for (const q of pts) {
        const t = Math.min(1, Math.pow(q.rho / rmax, 0.28));
        ctx.globalAlpha = (0.10 + 0.42 * t) * V.alpha / 0.7;
        ctx.fillStyle = mode === "mep" ? chargeColor(q.q, qmax) : `rgb(${Math.round(70 + 120 * (1 - t))},${Math.round(120 + 60 * (1 - t))},${Math.round(200 + 40 * (1 - t))})`;
        ctx.beginPath(); ctx.arc(q.sx, q.sy, (1.1 + 2.6 * t) * (isStatic ? 0.7 : 1), 0, Math.PI * 2); ctx.fill();
      }
      ctx.globalAlpha = 1;
    }
    if (orb && V.style !== "none" && !useIso) {
      const amax = orb.abs_max || 1, thr = 0.12 * (V.iso / 0.03), solid = V.style === "solid";
      const pts = orb.points.map((q, i) => ({...project(q[0], q[1], q[2], W, H, scale), v: orb.value[i]})).filter(p => Math.abs(p.v) / amax >= thr * 0.5).sort((a, b) => a.z - b.z);
      for (const p of pts) {
        const t = Math.min(1, Math.abs(p.v) / amax);
        ctx.globalAlpha = Math.min(1, (0.18 + 0.5 * t) * V.alpha / 0.7 * (solid ? 1.8 : 1));
        ctx.fillStyle = p.v >= 0 ? "#e0663e" : "#2a78d6";
        ctx.beginPath(); ctx.arc(p.sx, p.sy, (1.2 + 3.2 * t) * (isStatic ? 0.75 : 1) * (solid ? 1.6 : 1), 0, Math.PI * 2); ctx.fill();
      }
      ctx.globalAlpha = 1;
    }
    if (mepPts && (mode === "charge" || mode === "mep") && !isStatic) {
      for (const [kind, pos] of [["min", mepPts.min], ["max", mepPts.max]]) {
        if (!pos) continue;
        const p = project(pos[0], pos[1], pos[2], W, H, scale);
        ctx.setLineDash([3, 2]); ctx.strokeStyle = kind === "min" ? "#2a78d6" : "#e34948"; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(p.sx, p.sy, 9, 0, Math.PI * 2); ctx.stroke(); ctx.setLineDash([]);
        ctx.fillStyle = ctx.strokeStyle; ctx.font = "10px 'Pretendard Variable', system-ui, sans-serif"; ctx.textAlign = "center";
        ctx.fillText(kind === "min" ? "MEP− (Li⁺ 배위)" : "MEP+", p.sx, p.sy - 12);
      }
    }
    // ── 등가면: 격자 → 삼각형(캐시) → 회전·투영·조명, 뒷면 제거 ──
    let tris = null, surfAlpha = 1;
    if (useIso) {
      const isoV = gridOrb ? V.iso : V.iso / 10;                       // 밀도 등가면은 1/10 스케일(기본 0.003 e/bohr³)
      let meshes;
      try { meshes = gridOrb ? [[window.rbIso.mesh(gridOrb, isoV, 1), "+"], [window.rbIso.mesh(gridOrb, isoV, -1), "-"]] : [[window.rbIso.mesh(gridRho, isoV, 1), mode]]; }
      catch (e) { console.warn("isosurface", e); meshes = []; }
      const cy_ = Math.cos(yaw), sy_ = Math.sin(yaw), cp_ = Math.cos(pitch), sp_ = Math.sin(pitch);
      const Lx = -0.35, Ly = 0.55, Lz = 0.76;                            // 조명(화면 왼쪽 위 앞)
      const hl = Math.hypot(Lx, Ly, Lz + 1), Hx = Lx / hl, Hy = Ly / hl, Hz = (Lz + 1) / hl;
      const alphaOrb = Math.min(1, 0.3 + 0.6 * V.alpha), alphaRho = Math.min(0.92, 0.45 + 0.5 * V.alpha);   // 기본 0.7 → lobe 0.72 · 밀도 0.8 (안의 ball-and-stick 이 비친다)
      tris = [];
      for (const [m, kind] of meshes) {
        if (!m || !m.n) continue;
        const base = kind === "+" ? [226, 72, 56] : kind === "-" ? [44, 108, 226] : [206, 211, 220];
        surfAlpha = kind === "+" || kind === "-" ? alphaOrb : alphaRho;
        if (kind === "mep" && !m._q) {                                   // 정전위 근사: 주변 원자 부분 전하의 거리 가중 평균(σ 1.2 Å) — 경계가 부드럽다
          m._q = new Float32Array(m.n * 3);
          for (let v = 0; v < m.n * 3; v++) { let sw = 0, sq = 0; const x = m.pos[3 * v], y = m.pos[3 * v + 1], z = m.pos[3 * v + 2];
            for (let i = 0; i < atoms.length; i++) { const d2 = (x - atoms[i].x) ** 2 + (y - atoms[i].y) ** 2 + (z - atoms[i].z) ** 2; const w = Math.exp(-d2 / 1.44); sw += w; sq += w * (charges[i] ?? 0); }
            m._q[v] = sw > 1e-9 ? sq / sw : 0; }
        }
        for (let t = 0; t < m.n; t++) {
          const o = t * 9;
          let nx = m.nrm[o] + m.nrm[o + 3] + m.nrm[o + 6], ny = m.nrm[o + 1] + m.nrm[o + 4] + m.nrm[o + 7], nz = m.nrm[o + 2] + m.nrm[o + 5] + m.nrm[o + 8];
          const x1 = nx * cy_ + nz * sy_, z1 = -nx * sy_ + nz * cy_, ry = ny * cp_ - z1 * sp_, rz = ny * sp_ + z1 * cp_, rx = x1;
          const nl = Math.hypot(rx, ry, rz) || 1;
          if (rz / nl <= 0.02) continue;                                 // 뒷면
          const p0 = project(m.pos[o], m.pos[o + 1], m.pos[o + 2], W, H, scale), p1 = project(m.pos[o + 3], m.pos[o + 4], m.pos[o + 5], W, H, scale), p2 = project(m.pos[o + 6], m.pos[o + 7], m.pos[o + 8], W, H, scale);
          const diff = Math.max(0, (rx * Lx + ry * Ly + rz * Lz) / nl), spec = Math.pow(Math.max(0, (rx * Hx + ry * Hy + rz * Hz) / nl), 30);
          let b = base;
          if (kind === "mep") { const c = chargeColor((m._q[3 * t] + m._q[3 * t + 1] + m._q[3 * t + 2]) / 3, qmax * 0.45).match(/\d+/g); b = c ? c.slice(0, 3).map(Number) : base; }   // 가중 평균으로 옅어진 값을 되살려 대비를 키운다
          const k = 0.36 + 0.64 * diff, sp = spec * 110;
          const col = `rgb(${Math.min(255, Math.round(b[0] * k + sp))},${Math.min(255, Math.round(b[1] * k + sp))},${Math.min(255, Math.round(b[2] * k + sp))})`;
          tris.push({z: (p0.z + p1.z + p2.z) / 3, x0: p0.sx, y0: p0.sy, x1: p1.sx, y1: p1.sy, x2: p2.sx, y2: p2.sy, col});
        }
      }
    }
    const order = [...proj].sort((a, b) => a.z - b.z);
    const drawAtom = p => {
      const faded = solventIdx.has(p.i), shrink = cloudMode ? (useIso ? 0.55 : 0.35) : 1;   // 등가면 안에서도 ball-and-stick 이 보이게
      const rr = Math.max((rad(p.el) * 0.45 + 0.18) * scale * (faded ? 0.7 : 1) * shrink, 2);
      ctx.globalAlpha = faded ? 0.45 : 1;
      ctx.beginPath(); ctx.arc(p.sx, p.sy, rr, 0, Math.PI * 2);
      ctx.fillStyle = mode === "charge" && charges[p.i] !== undefined ? chargeColor(charges[p.i], qmax) : (COLOR[p.el] ?? "#888");
      ctx.fill();
      ctx.strokeStyle = mode === "charge" ? "rgba(60,60,60,.5)" : "rgba(255,255,255,.6)"; ctx.lineWidth = 1; ctx.stroke();
      if (!isStatic && (WS.sel === p.i || WS.measure.includes(p.i))) { ctx.strokeStyle = "var(--accent)"; ctx.strokeStyle = "#0f766e"; ctx.lineWidth = 2.5; ctx.beginPath(); ctx.arc(p.sx, p.sy, rr + 4, 0, Math.PI * 2); ctx.stroke(); }
      if (!isStatic && !faded) {
        if (mode === "charge" && charges[p.i] !== undefined && p.el !== "H") { ctx.fillStyle = "#333"; ctx.font = "10px ui-monospace,monospace"; ctx.textAlign = "center"; ctx.fillText(charges[p.i].toFixed(2), p.sx, p.sy - rr - 3); }
        else if (V.labels && p.el !== "H") { ctx.fillStyle = "#333"; ctx.font = "600 10px ui-monospace,monospace"; ctx.textAlign = "center"; ctx.fillText(p.el + (p.i + 1), p.sx, p.sy - rr - 3); }
      }
      ctx.globalAlpha = 1;
    };
    for (const p of order) drawAtom(p);
    if (tris && tris.length) {
      // 등가면은 오프스크린에 불투명하게(이음새 없이) 그린 뒤 반투명으로 합성 — 안의 ball-and-stick 이 비쳐 보인다
      tris.sort((a, b) => a.z - b.z);
      const off = document.createElement("canvas"); off.width = W * dpr; off.height = H * dpr;
      const oc = off.getContext("2d"); oc.setTransform(dpr, 0, 0, dpr, 0, 0); oc.lineJoin = "round"; oc.lineWidth = 0.8;
      for (const q of tris) { oc.fillStyle = q.col; oc.strokeStyle = q.col; oc.beginPath(); oc.moveTo(q.x0, q.y0); oc.lineTo(q.x1, q.y1); oc.lineTo(q.x2, q.y2); oc.closePath(); oc.fill(); oc.stroke(); }
      ctx.globalAlpha = surfAlpha; ctx.drawImage(off, 0, 0, W, H); ctx.globalAlpha = 1;
    }
    // 측정 표시
    if (!isStatic && WS.measure.length >= 2) {
      const m = WS.measure.map(i => proj[i]);
      ctx.strokeStyle = "#d97706"; ctx.lineWidth = 2; ctx.setLineDash([4, 3]);
      ctx.beginPath(); ctx.moveTo(m[0].sx, m[0].sy); for (const p of m.slice(1)) ctx.lineTo(p.sx, p.sy); ctx.stroke(); ctx.setLineDash([]);
      const A = WS.measure.map(i => atoms[i]);
      let txt = "";
      if (A.length === 2) txt = `${Math.hypot(A[0].x - A[1].x, A[0].y - A[1].y, A[0].z - A[1].z).toFixed(3)} Å`;
      else if (A.length === 3) txt = `∠ ${vAngle(A[0], A[1], A[2]).toFixed(1)}°`;
      else txt = `이면각 ${vDihedral(A[0], A[1], A[2], A[3]).toFixed(1)}°`;
      const mid = m[Math.floor(m.length / 2)];
      ctx.font = "600 12px 'Pretendard Variable', system-ui, sans-serif"; ctx.textAlign = "center";
      const tw = ctx.measureText(txt).width;
      ctx.fillStyle = "rgba(255,255,255,.9)"; ctx.fillRect(mid.sx - tw / 2 - 5, mid.sy - 30, tw + 10, 18);
      ctx.fillStyle = "#b45309"; ctx.fillText(txt, mid.sx, mid.sy - 17);
    }
  }
  draw();
  if (isStatic) return draw;
  if (isMain) WS.redraw = draw;
  // 카메라 공유 뷰어 등록 — 한 뷰어를 돌리면 같은 cam 을 쓰는 뷰어가 함께 다시 그려진다
  draw.box = box;
  const prev = RB_VIEWS.get(box);
  if (prev && prev.cam._draws) prev.cam._draws = prev.cam._draws.filter(f => f !== prev.draw);
  RB_VIEWS.set(box, {cam, draw});
  cam._draws = (cam._draws || []).filter(f => f.box && f.box.isConnected && f !== draw);
  cam._draws.push(draw);
  const drawLinked = () => cam._draws.forEach(f => { try { f(); } catch (e) {} });
  let dragging = false, moved = false, px = 0, py = 0;
  canvas.addEventListener("mousedown", e => { dragging = true; moved = false; px = e.clientX; py = e.clientY; });
  const up = () => { dragging = false; };
  const move = e => {
    if (!dragging) return;
    if (Math.abs(e.clientX - px) + Math.abs(e.clientY - py) > 2) moved = true;
    cam.yaw = yaw += (e.clientX - px) * 0.01; cam.pitch = pitch = Math.max(-1.5, Math.min(1.5, pitch + (e.clientY - py) * 0.01));
    px = e.clientX; py = e.clientY; drawLinked();
  };
  window.addEventListener("mouseup", up); window.addEventListener("mousemove", move);
  canvas.addEventListener("click", e => {
    if (moved) return;
    const rect = canvas.getBoundingClientRect(), mx = e.clientX - rect.left, my = e.clientY - rect.top;
    let best = null, bd = 1e9;
    for (const p of proj) { const d = Math.hypot(p.sx - mx, p.sy - my); if (d < 14 && d < bd) { bd = d; best = p.i; } }
    if (best == null) return;
    if (WS.tool === "measure") {
      if (WS.measure.length >= 4 || WS.measure.includes(best)) WS.measure = [];
      WS.measure.push(best);
    } else { WS.sel = best; }
    draw();
    if (opts.onPick) opts.onPick(best);
  });
  canvas.addEventListener("wheel", e => { e.preventDefault(); cam.zoom = zoom = Math.max(0.3, Math.min(5, zoom * (e.deltaY < 0 ? 1.1 : 0.9))); drawLinked(); }, {passive: false});
  return draw;
}

/* ── 원자 상세 카드 (기획서 3.3) ── */
function wsAtomCard(r, i) {
  const box = $("ws-atom"); if (!box) return;
  const atoms = parseXyz(r.structure_xyz); const a = atoms[i]; if (!a) { box.style.display = "none"; return; }
  const q = (r.mulliken_charges || [])[i];
  const ml = (r.atomic_charges?.meta_lowdin || r.charge_models?.meta_lowdin || r.meta_lowdin_charges || [])[i];
  const nb = bondList(atoms).filter(b => b[0] === i || b[1] === i).map(b => { const j = b[0] === i ? b[1] : b[0]; return `${atoms[j].el}${j + 1} ${b[2].toFixed(3)} Å`; });
  const near = atoms.filter((b, j) => j !== i && Math.hypot(b.x - a.x, b.y - a.y, b.z - a.z) <= 3).length;
  const fk = r.descriptors?.fukui_plus?.[i], fm = r.descriptors?.fukui_minus?.[i];
  box.innerHTML = `<button class="btn ghost sm" type="button" id="ws-atom-x" style="position:absolute;top:4px;right:6px">✕</button>
    <h4>${esc(a.el)} (원자 ${i + 1})</h4>
    <table><tr><td>좌표 x / y / z (Å)</td><td>${a.x.toFixed(3)} / ${a.y.toFixed(3)} / ${a.z.toFixed(3)}</td></tr>
    <tr><td>Mulliken</td><td>${q != null ? (q > 0 ? "+" : "") + q.toFixed(3) + " e" : "—"}</td></tr>
    <tr><td>meta-Löwdin</td><td>${ml != null ? (ml > 0 ? "+" : "") + Number(ml).toFixed(3) + " e" : "—"}</td></tr>
    ${fk != null || fm != null ? `<tr><td>Fukui f⁺ / f⁻</td><td>${fk != null ? fmt(fk) : "—"} / ${fm != null ? fmt(fm) : "—"}</td></tr>` : ""}
    <tr><td>결합</td><td>${nb.join("<br>") || "—"}</td></tr><tr><td>3 Å 이내</td><td>${near} 원자</td></tr></table>`;
  box.style.display = "";
  $("ws-atom-x").onclick = () => { WS.sel = null; box.style.display = "none"; WS.redraw && WS.redraw(); };
}

/* ── 계산 설정(Input) 패널 ── */
function wsInputPanel(job, r) {
  const s = job.settings || {}, e = s.expert || {}, c = r.conditions || {};
  const sol = c.solvent_model || (s.solventId ? s.solventId : "vacuum");
  const rows = [
    ["Method", e.functional || c.method?.split("/")[0] || "—"],
    ["Basis Set", (c.method || "").split("/")[1] || e.basis || "(프리셋)"],
    ["Solvent", sol], ["Charge · Multiplicity", `${e.charge ?? 0} · ${e.multiplicity ?? 1}`],
    ["정확도 · 목적", `${s.accuracy || "—"} · ${s.purpose || "—"}`],
    ["온도 · 기준 전극", `${c.temperature_k ?? s.temperature ?? "—"} K · ${c.reference_electrode || s.referenceElectrode || "—"}`],
  ];
  const adv = Object.entries(e).filter(([k, v]) => v != null && v !== "" && !["functional", "basis", "charge", "multiplicity", "scfTol"].includes(k));
  return `<div class="ws-panel"><div class="ws-ph">계산 설정 (Input)<span class="sp"><button class="btn ghost sm" type="button" data-ws-rerun="${esc(job.id)}" title="이 조건을 «계산» 화면에 채워 넣습니다">같은 조건으로 재계산</button></span></div>
    <div class="ws-pb"><table class="ws-kv">${rows.map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(String(v))}</td></tr>`).join("")}</table>
    ${adv.length ? `<details><summary class="small muted">고급 설정 보기 (${adv.length})</summary><table class="ws-kv small">${adv.map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(JSON.stringify(v))}</td></tr>`).join("")}</table></details>` : ""}
    ${r.provenance?.protocol_hash ? `<div class="small muted">프로토콜 해시 <span class="mono">${esc(String(r.provenance.protocol_hash).slice(0, 10))}</span></div>` : ""}</div></div>`;
}

/* ── 계산 진행 상황 (monitor.sections 요약) ── */
function wsProgressPanel(job, r) {
  const mon = job.monitor || {}, secs = mon.sections || [], wall = r.wall_time_s;
  const fmtT = t => t == null ? "" : (t >= 60 ? `${Math.floor(t / 60)}m ${String(Math.round(t % 60)).padStart(2, "0")}s` : `${t.toFixed(1)}s`);
  const items = secs.map((s, i) => { const end = i + 1 < secs.length ? secs[i + 1].t : wall; return `<li class="done"><i>✓</i>${esc(s.name)}<span class="t">${fmtT(end != null && s.t != null ? Math.max(0, end - s.t) : null)}</span></li>`; }).join("");
  const grade = (job.validation || r.validation || {}).grade;
  const scf = mon.scf || {};
  const finished = job.finishedAt ? new Date(job.finishedAt * 1000).toLocaleString("ko-KR", {hour12: false}) : "";
  return `<div class="ws-panel"><div class="ws-ph">계산 진행 상황<span class="sp"><span class="badge ${grade === "PASS" ? "published" : grade === "REVIEW" ? "review" : grade ? "failed" : "queued"}">${esc(grade ? "검증 " + grade : job.status)}</span></span></div>
    <div class="ws-pb">
      <div class="ws-done"><span class="ok">✓</span><div><b>${job.status === "PUBLISHED" ? "Completed" : esc(job.status)}</b><div class="small muted">${esc(finished)}</div></div><span class="mono" style="margin-left:auto">${wall != null ? fmtT(wall) : ""}</span></div>
      ${items ? `<ul class="ws-steps">${items}</ul>` : `<div class="small muted">단계 기록 없음 (이전 버전 계산)</div>`}
      ${scf.runs ? `<div class="small muted">SCF ${scf.runs}회 · 자동 복구 ${scf.recovered || 0} · 실패 ${scf.failed || 0}${mon.freq?.n_imag != null ? ` · 허수 진동수 ${mon.freq.n_imag}` : ""}</div>` : ""}
      <button class="btn ghost sm" type="button" onclick="window.rbOpenMonitor('${esc(job.id)}')" style="align-self:flex-start">계산 모니터에서 원본 로그 보기 →</button>
    </div></div>`;
}

/* ── 결과 요약 패널 ── */
function wsSummaryPanel(job, r) {
  const d = r.descriptors, mon = job.monitor || {}, scf = mon.scf || {};
  const u = unitE();
  const orbCard = (key, label, cls) => d[key] == null ? "" : `<div class="ws-rc orb ${cls}" data-ws-mode="${cls}" title="클릭 → 뷰어에 궤도 표면">
      <div><div class="l" style="color:var(--${cls})">${label}</div><div class="v">${fmtE(d[key])}<span class="u">${esc(u)}</span></div><div class="s">${(r.orbital_clouds || {})[cls] ? "클릭 → 3D 궤도 표면" : "궤도 데이터 없음"}</div></div>
      <div class="ws-thumb" data-thumb="${cls}"></div></div>`;
  const oc = r.orbital_clouds || {};
  const extra = (k, cls) => oc[k] ? `<div class="ws-rc orb ${cls}" data-ws-mode="${k}" title="클릭 → Geometry 탭 MO 뷰어"><div><div class="l" style="color:var(--${cls})">${ORB_LABEL[k]}</div><div class="v">${fmtE(oc[k].energy_ev)}<span class="u">${esc(u)}</span></div><div class="s">클릭 → 3D 궤도 표면</div></div><div class="ws-thumb" data-thumb="${k}"></div></div>` : "";
  const cards = extra("homo-1", "homo") + orbCard("homo_ev", "HOMO", "homo") + orbCard("lumo_ev", "LUMO", "lumo") + extra("lumo+1", "lumo")
    + (d.gap_ev != null ? `<div class="ws-rc"><div class="l">Band gap</div><div class="v">${fmtE(d.gap_ev)}<span class="u">${esc(u)}</span></div><div class="s">HOMO–LUMO · 클수록 안정</div></div>` : "")
    + (d.dipole_debye != null ? `<div class="ws-rc"><div class="l">Dipole moment</div><div class="v">${fmt(d.dipole_debye)}<span class="u">D</span></div><div class="s">${Array.isArray(d.dipole_xyz) ? d.dipole_xyz.map((v, i) => "xyz"[i] + " " + fmt(v)).join(" · ") : "분자 극성"}</div></div>` : "")
    + (d.total_energy_hartree != null ? `<div class="ws-rc"><div class="l">Total energy</div><div class="v" style="font-size:15px">${Number(d.total_energy_hartree).toFixed(4)}<span class="u">Ha</span></div><div class="s">${d.gibbs_energy_hartree != null ? "G(298 K) " + Number(d.gibbs_energy_hartree).toFixed(4) + " Ha" : "전자 에너지"}</div></div>` : "")
    + `<div class="ws-rc"><div class="l">SCF 수렴</div><div class="v" style="font-size:15px;color:${scf.failed ? "var(--danger)" : "var(--ok)"}">${scf.runs ? (scf.failed ? "Failed" : "Converged") : "—"}</div><div class="s">${scf.runs ? `${scf.runs} run · 최근 ${scf.cycle ?? "?"}회 · tol ${scf.conv_tol ?? "1e-8"}` : "기록 없음"}</div></div>`;
  return `<div class="ws-panel"><div class="ws-ph">결과 요약<span class="sp"><span class="badge ${wsQcClass(job, r)}">${esc(wsQcLabel(job, r))}</span></span></div>
    <div class="ws-pb"><div class="ws-cards">${cards}</div>
    <div class="rtabs" id="ws-tabs"><button class="on" type="button" data-p="conv">수렴 그래프</button><button type="button" data-p="el">전자 준위</button><button type="button" data-p="vib">진동 스펙트럼</button><button type="button" data-p="uv">UV-Vis</button><button type="button" data-p="esw">안정 창</button></div>
    <div id="ws-p-conv"><div class="small muted">불러오는 중…</div></div>
    <div id="ws-p-el" hidden></div><div id="ws-p-vib" hidden></div><div id="ws-p-uv" hidden></div><div id="ws-p-esw" hidden></div>
    ${wsQcList(job, r)}</div></div>`;
}
function wsQcLabel(job, r) { const g = (job.validation || r.validation || {}).grade; return g === "PASS" ? "QC Green" : g === "REVIEW" ? "QC Warning" : g ? "QC Failed" : "QC 없음"; }
function wsQcClass(job, r) { const g = (job.validation || r.validation || {}).grade; return g === "PASS" ? "published" : g === "REVIEW" ? "review" : g ? "failed" : "queued"; }
function wsQcList(job, r) {
  const v = job.validation || r.validation; if (!v || !Array.isArray(v.checks)) return "";
  const dot = s => s === "PASS" ? "" : s === "REVIEW" ? "w" : s === "FAIL" ? "b" : "g";
  return `<div class="ws-qc">${v.checks.slice(0, 8).map(c => `<div><i class="${dot(c.status)}"></i>${esc(c.label || c.key)}${c.detail ? ` <span class="muted">— ${esc(c.detail)}</span>` : ""}</div>`).join("")}</div>`;
}

/* ── 진동 스펙트럼 (IR 스틱, 진동수만 있을 때는 스틱 높이 균일) ── */
function svgVibSpectrum(freqs, intens) {
  if (!Array.isArray(freqs) || !freqs.length) return '<p class="muted small">진동수 데이터가 없습니다 (표준·정밀에서 열보정을 켠 작업에 표시).</p>';
  const W = 320, H = 120, L = 34, R = 8, T = 10, B = 26, fmax = Math.max(4000, ...freqs);
  const x = f => L + (W - L - R) * (f / fmax), imax = intens ? Math.max(...intens, 1e-9) : 1;
  let sv = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto"><line x1="${L}" y1="${H - B}" x2="${W - R}" y2="${H - B}" class="baseline"/>`;
  freqs.forEach((f, i) => { const h = intens ? (H - B - T) * (intens[i] / imax) : (H - B - T) * 0.6; sv += `<line x1="${x(f)}" y1="${H - B}" x2="${x(f)}" y2="${H - B - h}" stroke="${f < 0 ? "var(--danger)" : "var(--accent)"}" stroke-width="1.5"><title>${f.toFixed(1)} cm⁻¹</title></line>`; });
  [0, 1000, 2000, 3000, 4000].forEach(v => { sv += `<text x="${x(v)}" y="${H - 8}" text-anchor="middle" class="axis-label">${v}</text>`; });
  return sv + `<text x="${W / 2}" y="${H}" text-anchor="middle" class="axis-label">진동수 (cm⁻¹) · ${freqs.length}개 모드</text></svg>`;
}

/* ── 궤도 키 · 공용 유틸 (B타입 결과 화면 · 오비탈 비교 화면) ── */
const ORB_ORDER = ["homo-1", "homo", "lumo", "lumo+1"];
const ORB_MODES = new Set(ORB_ORDER);
const ORB_LABEL = {"homo-1": "HOMO−1", homo: "HOMO", lumo: "LUMO", "lumo+1": "LUMO+1"};
const ORB_BY_LABEL = {"HOMO−1": "homo-1", HOMO: "homo", LUMO: "lumo", "LUMO+1": "lumo+1"};
const RB_VIEWS = new WeakMap();                     // 뷰어 상자 → {cam, draw} (카메라 동기화용)
// 다음 프레임에 그리기 — 탭이 가려져 rAF 가 멈춰도(백그라운드 탭·숨은 창) 잠시 뒤 반드시 한 번 실행한다
function rbNextFrame(cb) { let done = false; const run = () => { if (done) return; done = true; try { cb(); } catch (e) { console.warn(e); } }; requestAnimationFrame(run); setTimeout(run, 150); }
const RB_GRIDS = {};                                // jobId → 격자 (JOBS_CACHE 가 2초마다 갈려도 다시 받지 않게)
function wsLoadGrids(job) {
  const r = job && job.result; if (!r) return Promise.resolve(null);
  if (RB_GRIDS[job.id]) { r.grids = RB_GRIDS[job.id]; return Promise.resolve(r.grids); }
  if (!r.grids_available) { r.grids = null; return Promise.resolve(null); }
  if (RB_GRIDS["_p_" + job.id]) return RB_GRIDS["_p_" + job.id];
  const pr = fetch(`/api/jobs/${encodeURIComponent(job.id)}/grids`).then(res => res.ok ? res.json() : null)
    .then(g => { if (g) { RB_GRIDS[job.id] = g; r.grids = g; } return g; }).catch(() => null).finally(() => { delete RB_GRIDS["_p_" + job.id]; });
  RB_GRIDS["_p_" + job.id] = pr;
  return pr;
}
function hillFormula(atoms) {
  const n = {}; atoms.forEach(a => { n[a.el] = (n[a.el] || 0) + 1; });
  const sub = k => String(k).replace(/\d/g, d => "₀₁₂₃₄₅₆₇₈₉"[d]);
  const keys = Object.keys(n).filter(k => k !== "C" && k !== "H").sort();
  return (n.C ? "C" + (n.C > 1 ? sub(n.C) : "") : "") + (n.H ? "H" + (n.H > 1 ? sub(n.H) : "") : "") + keys.map(k => k + (n[k] > 1 ? sub(n[k]) : "")).join("");
}
function downloadText(name, text, type = "text/plain") {
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([text], {type})); a.download = name; document.body.appendChild(a); a.click(); a.remove();
}
function contribText(c) { return c && c.atoms && c.atoms.length ? c.atoms.map(a => `${a.atom} ${a.pct}%`).join(" · ") : "데이터 없음"; }
function locSummary(c) {
  if (!c || !c.atoms || !c.atoms.length) return "데이터 없음";
  const byEl = {}; c.atoms.forEach(a => { const el = a.atom.replace(/\d+$/, ""); byEl[el] = (byEl[el] || 0) + a.pct; });
  return Object.entries(byEl).sort((a, b) => b[1] - a[1]).map(([el, p]) => `${el} ${p.toFixed(0)}%`).join(" · ") + (c.atoms.length ? ` (상위 ${c.atoms.length}원자 기준)` : "");
}
function orbLevelsOf(r) {
  // orbital_levels 가 없는 이전 결과는 점 구름의 에너지로 최소 준위 목록을 만든다
  if (r.orbital_levels && r.orbital_levels.levels) return r.orbital_levels;
  const oc = r.orbital_clouds || {}, levels = ORB_ORDER.filter(k => oc[k]).map(k => ({index: oc[k].index, label: ORB_LABEL[k], energy_ev: oc[k].energy_ev, occ: oc[k].occ ?? (k.startsWith("homo") ? 2 : 0)}));
  if (!levels.length && r.descriptors) { if (r.descriptors.homo_ev != null) levels.push({index: null, label: "HOMO", energy_ev: r.descriptors.homo_ev, occ: 2}); if (r.descriptors.lumo_ev != null) levels.push({index: null, label: "LUMO", energy_ev: r.descriptors.lumo_ev, occ: 0}); }
  return levels.length ? {homo_index: null, spin: "restricted", levels} : null;
}

/* ── 궤도 에너지 준위도 (기획서 B타입 «Orbital Energy Levels» · 오비탈 비교 «에너지 준위도») ── */
function svgOrbitalLevels(lv, o = {}) {
  const levels = lv && lv.levels;
  if (!levels || !levels.length) return '<p class="muted small">준위 데이터가 없습니다 (이전 버전 계산 또는 배치 결과) — 다시 계산하면 표시됩니다.</p>';
  const H = o.height || 240, W = 330, L = 46, T = 14, B = 14, u = unitE();
  const es = levels.map(l => l.energy_ev);
  let e0 = Math.min(...es), e1 = Math.max(...es); const pad = Math.max(0.6, (e1 - e0) * 0.08); e0 -= pad; e1 += pad;
  const y = e => T + (e1 - e) / (e1 - e0) * (H - T - B);
  const homo = levels.find(l => l.label === "HOMO"), lumo = levels.find(l => l.label === "LUMO");
  const range = e1 - e0, step = range > 14 ? 4 : range > 7 ? 2 : 1;
  let s = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;display:block"><line x1="${L}" y1="${T}" x2="${L}" y2="${H - B}" class="baseline"/>`;
  for (let e = Math.ceil(e0 / step) * step; e <= e1; e += step) s += `<text x="${L - 5}" y="${y(e) + 3.5}" text-anchor="end" class="axis-label">${e}</text><line x1="${L - 3}" y1="${y(e)}" x2="${L}" y2="${y(e)}" class="baseline"/>`;
  const KEY = new Set(["HOMO−1", "HOMO", "LUMO", "LUMO+1"]);
  let lastY = -1e9;
  for (const l of [...levels].sort((a, b) => b.energy_ev - a.energy_ev)) {
    const key = KEY.has(l.label), on = l.label === o.active, occ = l.occ > 0, col = occ ? "#2a78d6" : "#e0663e", yy = y(l.energy_ev);
    const showLabel = (key || Math.abs(yy - lastY) > 12) && (!o.compact || key);
    s += `<g data-lv="${esc(l.label)}" style="cursor:${ORB_BY_LABEL[l.label] ? "pointer" : "default"}"><title>${esc(l.label)} · ${fmtE(l.energy_ev)} ${esc(u)} · 점유 ${l.occ}${l.index != null ? " · MO " + (l.index + 1) : ""}</title>
      <line x1="${L + 14}" y1="${yy}" x2="${L + 104}" y2="${yy}" stroke="${col}" stroke-width="${on ? 4 : 2}" opacity="${key ? 1 : .55}"/>
      <line x1="${L + 104}" y1="${yy}" x2="${L + 120}" y2="${yy}" stroke="${col}" stroke-dasharray="2 2" opacity=".6"/>
      ${showLabel ? `<text x="${L + 124}" y="${yy + 3.5}" font-size="${o.compact ? 10 : 11}" fill="${col}" font-weight="${on ? 800 : 500}">${esc(l.label)} (${fmtE(l.energy_ev)} ${esc(u)})</text>` : ""}</g>`;
    if (showLabel) lastY = yy;
  }
  if (homo && lumo && !o.compact) {
    const x = L + 60, y0 = y(lumo.energy_ev), y1 = y(homo.energy_ev);
    s += `<defs><marker id="ol-ar" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto-start-reverse"><path d="M0,0 L6,3 L0,6 z" fill="var(--text-1)"/></marker></defs>
      <line x1="${x}" y1="${y0 + 3}" x2="${x}" y2="${y1 - 3}" stroke="var(--text-1)" stroke-width="1.4" marker-start="url(#ol-ar)" marker-end="url(#ol-ar)"/>
      <text x="${x + 8}" y="${(y0 + y1) / 2 + 4}" font-size="11" fill="var(--text-1)" font-weight="700">ΔE = ${fmtE(lumo.energy_ev - homo.energy_ev)} ${esc(u)}</text>`;
  }
  return s + "</svg>";
}

/* ── Orbital Information 표 (Geometry 탭 세 번째 열) ── */
function orbInfoTable(r, key) {
  const oc = (r.orbital_clouds || {})[key], lv = orbLevelsOf(r);
  if (!ORB_MODES.has(key)) {
    const desc = {cloud: "전자밀도 ρ(r) — 점의 밀집도 ∝ 밀도", mep: "정전위(ESP) 근사 — 전자밀도 표면을 부분 전하로 색칠", charge: "부분 전하 — 파랑 음전하 · 빨강 양전하"};
    return `<table class="ws-kv"><tr><th>표면</th><td>${esc((WS_MODES.find(m => m[0] === key) || [key, key])[1])}</td></tr><tr><th>설명</th><td>${esc(desc[key] || "")}</td></tr><tr><th>데이터</th><td>${r.density_cloud ? "저장됨" : '<span class="muted">없음 — 다시 계산하면 표시</span>'}</td></tr></table>`;
  }
  if (!oc) return `<table class="ws-kv"><tr><th>Orbital</th><td>${esc(ORB_LABEL[key])}</td></tr><tr><th>상태</th><td class="muted">궤도 데이터 없음 — 이전 버전 계산 또는 배치 결과입니다. «같은 조건으로 재계산»하면 저장됩니다.</td></tr></table>`;
  const c = oc.contributions;
  return `<table class="ws-kv">
    <tr><th>Orbital</th><td><b>${esc(oc.label || ORB_LABEL[key])}</b> <span class="mono muted">(MO ${oc.index + 1})</span></td></tr>
    <tr><th>Spin</th><td>${lv && lv.spin === "alpha" ? "α (열린 껍질 · UKS)" : "restricted (α = β)"}</td></tr>
    <tr><th>Energy</th><td>${fmtE(oc.energy_ev)} ${esc(unitE())} <span class="muted small">(${(oc.energy_ev / 27.211386).toFixed(4)} Ha)</span></td></tr>
    <tr><th>Occupation</th><td>${oc.occ != null ? oc.occ : (key.startsWith("homo") ? 2 : 0)}</td></tr>
    <tr><th>Symmetry</th><td class="muted">데이터 없음 (점군 분석 미수행)</td></tr>
    <tr><th>Character</th><td>${esc(locSummary(c))}</td></tr>
    <tr><th>Contribution</th><td>${esc(contribText(c))}${c ? `<div class="muted small">${esc(c.method)} population · 원자별 |S^½C|² 비율</div>` : ""}</td></tr>
    <tr><th>등가면</th><td>${(r.grids || {})[key] ? `±${WS.mo.iso.toFixed(3)} a.u. <span class="muted small">(붉은 = + 위상 · 파란 = − 위상 · 위상 부호는 전하 부호가 아님)</span>` : `<span class="muted">격자 없음 — 점 구름으로 표시 (문턱 ${(0.12 * WS.mo.iso / 0.03).toFixed(2)} × |ψ|max)</span>`}</td></tr>
  </table>`;
}

/* ── B타입 결과 화면 — 헤더 · QC 배지 ── */
function wsHeader(job, r) {
  const atoms = parseXyz(r.structure_xyz), d = r.descriptors || {}, e = job.settings?.expert || {};
  const grade = (job.validation || r.validation || {}).grade;
  const fin = job.finishedAt ? new Date(job.finishedAt * 1000).toLocaleString("ko-KR", {hour12: false}) : "";
  const formula = job.material.formula || hillFormula(atoms);
  const st = job.status === "PUBLISHED" ? "Completed" : job.status;
  return `<div class="ws-head">
    <div class="ws-head-main"><h2>${esc(job.material.name)} <span class="f mono">${esc(formula)}</span>
        <span class="badge ${job.status === "PUBLISHED" ? "published" : "queued"}">${esc(st)}</span>
        ${grade ? `<span class="badge ${wsQcClass(job, r)}">검증 ${esc(grade)}</span>` : ""}${r.slimmed ? '<span class="badge queued">배치 결과 (슬림)</span>' : ""}</h2>
      <div class="ws-meta"><b>${esc(r.conditions.method)}</b><span>|</span><span>${esc(r.conditions.solvent_model)}</span><span>|</span><span>전하 ${e.charge ?? 0} · 다중도 ${e.multiplicity ?? 1}</span><span>|</span><span>${esc(String(r.conditions.temperature_k))} K</span><span>|</span><span>${esc(fin)}</span><span>|</span><span class="mono">${esc(job.id)}</span>${r.wall_time_s != null ? `<span>|</span><span>wall ${r.wall_time_s}s</span>` : ""}</div></div>
    <div class="ws-head-acts">
      <button class="btn" type="button" data-ws-tab-go="files" title="입력 설정 · 로그 · 재현성 정보">🗎 계산 정보</button>
      <details class="ws-dl"><summary class="btn primary">⬇ Download ▾</summary><div class="ws-dlm">
        <button type="button" data-dl="xyz">XYZ 좌표 (.xyz)</button>
        <button type="button" data-dl="orbcsv">궤도 표 (.csv)</button>
        <a href="/api/export?format=json&ids=${encodeURIComponent(job.id)}">결과 JSON</a>
        <a href="/api/export?format=csv&ids=${encodeURIComponent(job.id)}">물성 CSV</a>
        <a href="/api/export?format=html&ids=${encodeURIComponent(job.id)}">HTML 사본 (서버 없이 열림)</a></div></details>
      <button class="btn" type="button" data-ws-compare="1" title="이 결과를 «물질 비교» 선택에 추가">⇄ Compare</button>
      <button class="btn" type="button" data-ws-orbital="1" title="HOMO−1 · HOMO · LUMO · LUMO+1 4분할 비교">⚛ 오비탈 비교</button>
      <button class="btn ghost" type="button" data-ws-close="1">닫기</button>
    </div></div>`;
}
function wsQcRow(job, r) {
  const mon = job.monitor || {}, scf = mon.scf || {}, d = r.descriptors || {}, v = job.validation || r.validation;
  const chk = (re) => (v && v.checks || []).find(c => re.test(c.key || "") || re.test(c.label || ""));
  const b = (cls, txt, title) => `<span class="badge ${cls}" title="${esc(title || "")}">${txt}</span>`;
  const st = s => { s = String(s || "").toUpperCase(); return s === "PASS" ? "published" : s === "REVIEW" ? "review" : s === "FAIL" ? "failed" : "queued"; };
  const opt = chk(/opt|최적화|geometry|구조/i), n_imag = d.n_imaginary_freqs ?? mon.freq?.n_imag;
  return `<div class="ws-qcrow">
    ${scf.runs ? b(scf.failed ? "failed" : "published", `SCF ${scf.failed ? "Failed" : "Converged"} · ${scf.runs} run${scf.cycle != null ? " · " + scf.cycle + "회" : ""}`, "마지막 SCF 반복 횟수") : b("queued", "SCF 기록 없음")}
    ${opt ? b(st(opt.status), `구조 최적화 ${opt.status}${opt.detail ? " · " + esc(opt.detail) : ""}`) : b("queued", "구조 최적화 —", "검증 항목 없음")}
    ${n_imag != null ? b(n_imag > 0 ? "failed" : "published", `${n_imag} imaginary frequenc${n_imag === 1 ? "y" : "ies"}`) : b("queued", "진동수 미계산", "열보정을 켠 작업에 표시")}
    ${b("queued", `단위: ${esc(unitE())} · Å · kcal/mol · ${esc(r.conditions.solvent_model)}`, "설정 → 에너지 단위에서 바꿀 수 있습니다")}
    <button class="btn ghost sm" type="button" data-ws-tab-go="files">Provenance ▾</button>
  </div>`;
}

/* ── 탭 본문 ── */
function tabSummaryHtml(job, r) {
  const d = r.descriptors, ref = d.potential_reference;
  let html = `${r.binder_report ? binderScorecard(r.binder_report) : ""}
    <div class="ws-sum"><div>${wsSummaryPanel(job, r)}</div><div class="ws-col">${wsInputPanel(job, r)}${wsProgressPanel(job, r)}</div></div>`;
  const radar = svgRadar(d);
  if (radar) {
    html += `<div class="grid-2" style="margin-top:16px"><div><h3 style="font-size:13px;color:var(--accent)">물성 지문 (축 선택 가능)</h3><div id="fp-axis-picker"></div><div id="fp-radar">${radar}</div>
      <p class="muted small" style="margin:4px 0 0">저장된 PUBLISHED 결과 전체 범위로 min-max 정규화 · 점에 마우스를 올리면 원값·단위 표시 · 바깥쪽일수록 스크리닝에 유리한 방향</p></div>`;
    if (d.surface_adsorption) html += `<div><h3 style="font-size:13px;color:var(--accent)">활물질 표면 흡착 에너지</h3>${svgAdsorption(d.surface_adsorption)}<p class="muted small" style="margin:4px 0 0">막대가 길수록 해당 표면에 강하게 흡착 (E_ad 음수 방향) · 대용 클러스터 모델 전제 — 다른 표면 모델·문헌 절대값과 비교 금지</p></div>`;
    html += "</div>";
  } else if (d.surface_adsorption) html += `<h3 style="font-size:13px;color:var(--accent);margin-top:16px">활물질 표면 흡착 에너지</h3>${svgAdsorption(d.surface_adsorption)}`;
  if (r.validation) html += htmlValidationCard(r.validation, job.id);
  const shown = new Set(["potential_reference", "conformer_populations", "conformer_sensitivity", "li_interaction", "mep_points", "surface_adsorption", "bde_all", "bde_weakest_bond", "uvvis_states"]);
  const ordered = [...PINNED, ...KV_GROUPS.flatMap(g => g[1]), ...Object.keys(d)];
  let listRows = ""; const seen = new Set();
  for (const k of ordered) {
    if (seen.has(k) || shown.has(k) || d[k] == null || typeof d[k] === "object") continue;
    seen.add(k);
    const [label, unit] = DESC_LABELS[k] || [k, ""], star = PINNED.has(k), suffix = k.includes("potential") && ref ? ` vs ${ref}` : "";
    listRows += `<tr${star ? ' style="background:color-mix(in srgb,var(--pin) 7%,transparent)"' : ""}><td style="width:30px"><button class="pin-btn ${star ? "on" : ""}" data-pin="${esc(k)}" title="클릭하면 ★ 고정 — 레이더 축으로 사용됩니다">${star ? "★" : "☆"}</button></td><td><b>${esc(label)}</b></td><td class="small muted">${esc(unit)}${suffix}</td><td class="num" style="text-align:right;font-variant-numeric:tabular-nums">${fmt(d[k])}</td></tr>`;
  }
  html += `<h3 style="font-size:13px;color:var(--accent);margin-top:18px">물성 전체 목록 <span class="muted small">(★를 클릭하면 고정 — 레이더 축이 됩니다)</span></h3>
    <div class="scroll-x"><table class="table" style="min-width:520px"><tr><th></th><th>물성</th><th>단위</th><th class="num" style="text-align:right">값</th></tr>${listRows}</table></div><div class="form-error" id="pin-msg"></div>
    <h3 style="font-size:13px;color:var(--accent);margin-top:14px">주의사항</h3><ul class="log-list">${(r.notes || []).map(n => `<li>${esc(n)}</li>`).join("")}</ul>`;
  return html;
}
function tabGeometryHtml(job, r) {
  const atoms = parseXyz(r.structure_xyz), oc = r.orbital_clouds || {};
  const moOpts = ORB_ORDER.map(k => `<option value="${k}" ${!oc[k] ? 'disabled' : ""}>${ORB_LABEL[k]}${oc[k] ? ` (${fmtE(oc[k].energy_ev)} ${esc(unitE())})` : " — 데이터 없음"}</option>`).join("")
    + `<option value="cloud">전자밀도</option><option value="mep">정전위(ESP)</option><option value="charge">부분 전하</option>`;
  const addv = [...ORB_ORDER.map(k => [k, ORB_LABEL[k], !!oc[k]]), ["cloud", "전자밀도", !!r.density_cloud], ["mep", "ESP", !!r.density_cloud], ["charge", "부분 전하", true]]
    .map(([k, l, ok]) => `<button class="ws-q ${k === WS.mo.mode ? "on" : ""}" type="button" data-ws-mo="${k}" ${ok ? "" : 'disabled title="데이터 없음 — 다시 계산하면 표시"'}><div class="ws-thumb" data-thumb="${k}"></div>${l}</button>`).join("");
  return `<div class="ws-three">
    <div class="ws-panel"><div class="ws-ph">Optimized Geometry<span class="sp"><span class="seg" id="ws-geo-seg"><button class="on" type="button" data-geo="element">Ball &amp; Stick</button><button type="button" data-geo="charge">부분 전하</button></span></span></div>
      <div class="ws-tools">
        <button class="ws-tool on" type="button" data-ws-tool="select" title="원자 클릭 = 상세 카드 · 좌표 행 강조"><i>↖</i>선택</button>
        <button class="ws-tool" type="button" data-ws-tool="measure" title="원자 2개 = 거리 · 3개 = 각도 · 4개 = 이면각"><i>⟷</i>측정</button>
        <button class="ws-tool ${WS.labels ? "on" : ""}" type="button" data-ws-tool="label" title="원자 번호 표시"><i>Aa</i>라벨</button>
        <button class="ws-tool" type="button" data-ws-tool="zoomin"><i>＋</i>확대</button>
        <button class="ws-tool" type="button" data-ws-tool="zoomout"><i>－</i>축소</button>
        <button class="ws-tool" type="button" data-ws-tool="reset"><i>⌂</i>초기화</button>
        <button class="ws-tool" type="button" data-ws-tool="full" title="전체 화면"><i>⛶</i>전체</button>
        <button class="ws-tool" type="button" data-ws-tool="shot" title="현재 화면을 PNG 로 저장"><i>📷</i>저장</button>
      </div>
      <div id="viewer3d" style="position:relative;width:100%;height:340px;background:radial-gradient(ellipse at 50% 40%,color-mix(in srgb,var(--accent) 6%,var(--surface)) 0%,var(--grid) 90%)"></div>
      <div class="ws-atom" id="ws-atom" style="display:none"></div>
      <div class="legend" id="viewer3d-legend" style="padding:6px 12px 0"></div>
      <p class="muted small" id="viewer3d-note" style="margin:4px 12px 8px"></p></div>
    <div class="ws-panel"><div class="ws-ph">Molecular Orbitals<span class="sp"><select class="input" id="ws-mo-sel" style="padding:3px 6px;font-size:12px">${moOpts}</select></span></div>
      <div class="ws-tools" style="gap:10px">
        <label class="small muted" style="display:flex;gap:5px;align-items:center">등가면 <input type="range" id="ws-mo-iso" min="1" max="10" value="${Math.round(WS.mo.iso * 100)}" style="width:70px;accent-color:var(--accent)"><span class="mono" id="ws-mo-isov">${WS.mo.iso.toFixed(2)}</span></label>
        <label class="small muted" style="display:flex;gap:5px;align-items:center">불투명도 <input type="range" id="ws-mo-alpha" min="2" max="10" value="${Math.round(WS.mo.alpha * 10)}" style="width:70px;accent-color:var(--accent)"></label>
        <button class="ws-tool ${WS.mo.style !== "none" ? "on" : ""}" type="button" data-mo-tool="surface" title="등가면 → 점 구름 → 숨김 순으로 바뀝니다"><i>◐</i><span data-mo-style-label>${WS.mo.style === "cloud" ? "점 구름" : WS.mo.style === "none" ? "숨김" : "등가면"}</span></button>
        <button class="ws-tool ${WS.mo.sync ? "on" : ""}" type="button" data-mo-tool="sync" title="왼쪽 구조 뷰어와 카메라 각도 동기화"><i>⧉</i>동기화</button>
        <button class="ws-tool" type="button" data-mo-tool="reset"><i>⌂</i>초기화</button>
      </div>
      <div id="viewer3d-mo" style="position:relative;width:100%;height:340px;background:radial-gradient(ellipse at 50% 40%,color-mix(in srgb,var(--accent) 6%,var(--surface)) 0%,var(--grid) 90%)"></div>
      <div class="legend" style="padding:6px 12px 0"><span class="legend-item"><span class="legend-swatch" style="background:#e0663e"></span>+ 위상</span><span class="legend-item"><span class="legend-swatch" style="background:#2a78d6"></span>− 위상</span><span class="legend-item muted">위상 부호 ≠ 전하 부호</span></div>
      <p class="muted small" id="ws-mo-note" style="margin:4px 12px 8px"></p></div>
    <div class="ws-panel"><div class="ws-ph">Orbital Information</div><div class="ws-pb" id="ws-mo-info"></div></div>
  </div>
  <div class="ws-three ws-three-b">
    <div class="ws-panel"><div class="ws-ph">XYZ Coordinates (Å)<span class="sp"><button class="btn ghost sm" type="button" data-dl="xyzcsv">CSV</button><button class="btn ghost sm" type="button" data-dl="xyz">XYZ</button></span></div>
      <div style="max-height:280px;overflow:auto"><table class="table ws-xyz" id="ws-xyz"><tr><th>#</th><th>Atom</th><th class="num">X</th><th class="num">Y</th><th class="num">Z</th></tr>
        ${atoms.map((a, i) => `<tr data-atom="${i}"><td>${i + 1}</td><td>${esc(a.el)}</td><td class="num">${a.x.toFixed(3)}</td><td class="num">${a.y.toFixed(3)}</td><td class="num">${a.z.toFixed(3)}</td></tr>`).join("")}</table></div>
      <p class="muted small" style="margin:6px 12px 8px">행 클릭 → 3D 원자 하이라이트 · 최종 최적화 구조 (${atoms.length}원자)</p></div>
    <div class="ws-panel"><div class="ws-ph">Orbital Energy Levels<span class="sp small muted">${esc(unitE())} · 준위 클릭 → 뷰어 변경</span></div><div class="ws-pb" id="ws-levels"></div></div>
    <div class="ws-panel"><div class="ws-ph">Additional Views<span class="sp small muted">클릭 → MO 뷰어 변경</span></div><div class="ws-quick" style="border-top:none">${addv}</div><p class="muted small" style="margin:0 12px 8px">전자밀도·ESP 는 점 데이터가 저장된 결과에서만 활성</p></div>
  </div>`;
}
function tabFreqHtml(job, r) {
  const th = r.thermo, freqs = th && th.freqs_cm, d = r.descriptors || {};
  if (!freqs || !freqs.length) return `<div class="empty"><b>진동수 데이터 없음</b><span class="small">열보정(정확도 «표준» 이상)을 켠 작업에 표시됩니다.${d.zpe_kcal != null ? " 이 결과는 진동수 목록을 저장하기 전 버전에서 계산되었습니다 — «같은 조건으로 재계산»하면 표시됩니다." : ""}</span></div>`;
  const nImag = th.n_imaginary ?? d.n_imaginary_freqs ?? freqs.filter(f => f < 0).length;
  const kind = f => f < 0 ? '<span class="badge failed">허수</span>' : f < 100 ? '<span class="badge review">저진동수</span>' : "";
  return `<div class="ws-qcrow" style="margin-bottom:10px"><span class="badge ${nImag ? "failed" : "published"}">${nImag} imaginary</span><span class="badge queued">${freqs.length} modes</span><span class="badge queued">최저 ${fmt(th.lowest_freq_cm ?? Math.min(...freqs))} cm⁻¹</span>${d.freq_scale_factor != null && d.freq_scale_factor !== 1 ? `<span class="badge queued">scale ${d.freq_scale_factor}</span>` : ""}${th.qrrho ? `<span class="badge queued" title="저진동수 모드의 조화 엔트로피 과대평가 보정">qRRHO ${th.qrrho.n_low_freq}개 &lt; ${Math.round(th.qrrho.cutoff_cm)} cm⁻¹ · ΔG ${th.qrrho.delta_g_kcal > 0 ? "+" : ""}${th.qrrho.delta_g_kcal} kcal/mol</span>` : ""}</div>
    <div class="grid-2"><div class="ws-panel"><div class="ws-ph">IR 스펙트럼 (조화 진동수)</div><div class="ws-pb">${svgVibSpectrum(freqs, th.ir_intensities)}<p class="muted small" style="margin:0">IR 세기가 저장되지 않아 스틱 높이는 균일합니다 · 허수 진동수는 붉은색</p></div></div>
      <div class="ws-panel"><div class="ws-ph">진동 모드 목록</div><div style="max-height:320px;overflow:auto"><table class="table"><tr><th>#</th><th class="num">진동수 (cm⁻¹)</th><th>구분</th></tr>${freqs.map((f, i) => `<tr><td>${i + 1}</td><td class="num">${f.toFixed(1)}</td><td>${kind(f)}</td></tr>`).join("")}</table></div></div></div>
    <p class="muted small">기체상 조화진동자 근사 · 허수 진동수가 있으면 안장점 — 엔진이 해당 모드로 변위 후 재최적화합니다. Normal mode 애니메이션은 저장하지 않습니다.</p>`;
}
function tabSpectraHtml(job, r) {
  const d = r.descriptors || {}, st = d.uvvis_states;
  let html = "";
  if (d.uvvis_lambda_max_nm != null) {
    html += `<div class="stat-row"><div class="stat-tile"><div class="stat-label">λmax (가장 밝은 상태)</div><div class="stat-value">${fmt(d.uvvis_lambda_max_nm)}<span class="stat-unit"> nm</span></div><div class="stat-sub">수직 여기 ${fmt(d.uvvis_excitation_ev)} eV · f = ${fmt(d.uvvis_osc_strength)}</div></div>
      ${d.gap_ev != null ? `<div class="stat-tile"><div class="stat-label">KS gap (비교용)</div><div class="stat-value">${fmtE(d.gap_ev)}<span class="stat-unit"> ${esc(unitE())}</span></div><div class="stat-sub">궤도 에너지 차이 — 여기 에너지와 다름</div></div>` : ""}</div>`;
    html += st && st.length ? `<div class="ws-panel"><div class="ws-ph">TD-DFT 여기상태 (${st.length}개)</div><div class="scroll-x"><table class="table"><tr><th>State</th><th class="num">ΔE (eV)</th><th class="num">λ (nm)</th><th class="num">f</th><th>주 기여</th><th class="num">가중치</th></tr>
      ${st.map(s => `<tr><td>S${s.state}</td><td class="num">${fmt(s.energy_ev)}</td><td class="num">${s.wavelength_nm != null ? fmt(s.wavelength_nm) : "—"}</td><td class="num">${fmt(s.osc_strength)}</td><td>${esc(s.transition || "—")}</td><td class="num">${s.weight_pct != null ? s.weight_pct + "%" : "—"}</td></tr>`).join("")}</table></div>
      <p class="muted small" style="margin:6px 12px 8px">수직 여기 · 진동 구조와 용매 재조직화 미포함 · 주 기여는 X 진폭이 가장 큰 궤도쌍</p></div>` : '<p class="muted small">상태별 목록은 이 버전 이후 계산에서 저장됩니다 — «같은 조건으로 재계산»하면 표시됩니다.</p>';
  } else html += `<div class="empty"><b>추가 계산 필요 — TD-DFT</b><span class="small">UV–Vis 여기 에너지·진동자 세기는 목적 «물성 지문»으로 계산한 작업에만 표시됩니다. KS HOMO–LUMO gap 은 여기 에너지가 아닙니다.</span><button class="btn" type="button" data-ws-rerun="${esc(job.id)}">이 구조·조건으로 재계산 (목적을 «물성 지문»으로)</button></div>`;
  const freqs = r.thermo && r.thermo.freqs_cm;
  if (freqs && freqs.length) html += `<h3 style="font-size:13px;color:var(--accent);margin-top:14px">IR (조화 진동수)</h3>${svgVibSpectrum(freqs, r.thermo.ir_intensities)}`;
  return html;
}
function tabThermoHtml(job, r) {
  const d = r.descriptors || {}, th = r.thermo || {}, K = 627.509;
  if (d.zpe_kcal == null && d.gibbs_energy_hartree == null) return `<div class="empty"><b>열역학 보정 없음</b><span class="small">정확도 «표준» 이상(열보정 포함)으로 계산한 작업에 표시됩니다.</span></div>`;
  const rows = [
    ["전자 에너지 E", d.total_energy_hartree != null ? `${Number(d.total_energy_hartree).toFixed(6)} Ha` : "—"],
    ["ZPE", d.zpe_kcal != null ? `${d.zpe_kcal} kcal/mol` : "—"],
    ["엔탈피 보정 H − E", th.h_corr_hartree != null ? `${(th.h_corr_hartree * K).toFixed(2)} kcal/mol` : "—"],
    ["엔트로피 S", d.entropy_cal_mol_k != null ? `${d.entropy_cal_mol_k} cal/mol·K` : "—"],
    ["깁스 보정 G − E", d.gibbs_correction_kcal != null ? `${d.gibbs_correction_kcal} kcal/mol` : "—"],
    ["G(T)", d.gibbs_energy_hartree != null ? `${Number(d.gibbs_energy_hartree).toFixed(6)} Ha` : "—"],
    ["온도 · 압력", `${r.conditions.temperature_k} K · 1 atm (101325 Pa)`],
    ["근사", "강체회전 · 조화진동자 · 이상기체" + (th.qrrho ? ` · qRRHO (저진동수 ${th.qrrho.n_low_freq}개 보정, ΔG ${th.qrrho.delta_g_kcal > 0 ? "+" : ""}${th.qrrho.delta_g_kcal} kcal/mol)` : "")],
    ["허수 진동수", th.n_imaginary ?? d.n_imaginary_freqs ?? "—"],
  ];
  return `<div class="ws-panel" style="max-width:720px"><div class="ws-ph">Thermodynamics<span class="sp small muted">${r.conditions.temperature_k} K · qRRHO</span></div><div class="ws-pb"><table class="ws-kv">${rows.map(([k, v]) => `<tr><th>${esc(k)}</th><td>${v}</td></tr>`).join("")}</table>
    <p class="muted small" style="margin:0">전위·결합 에너지 등 ΔG 기반 지표는 «Charge &amp; Reactivity» 탭에 있습니다. 표준 상태 보정(1 atm → 1 M)은 전위 계산에 포함됩니다.</p></div></div>`;
}
function tabChargeHtml(job, r) {
  const d = r.descriptors || {}, ref = d.potential_reference, atoms = parseXyz(r.structure_xyz);
  const mul = r.mulliken_charges || [], ml = (r.atomic_charges && r.atomic_charges.meta_lowdin) || [];
  const fk = d.fukui_plus, fm = d.fukui_minus;
  let html = `<div class="grid-2"><div class="ws-panel"><div class="ws-ph">원자별 부분 전하<span class="sp small muted">주값 ${esc((r.atomic_charges && r.atomic_charges.primary) || "mulliken")}${r.atomic_charges && r.atomic_charges.max_abs_diff != null ? ` · 모델 간 최대 차 ${r.atomic_charges.max_abs_diff} e` : ""}</span></div>
    <div style="max-height:320px;overflow:auto"><table class="table"><tr><th>원자</th><th class="num">Mulliken</th><th class="num">meta-Löwdin</th>${Array.isArray(fk) ? '<th class="num">f⁺</th><th class="num">f⁻</th>' : ""}</tr>
      ${atoms.map((a, i) => `<tr data-atom="${i}"><td>${esc(a.el)}${i + 1}</td><td class="num">${mul[i] != null ? (mul[i] > 0 ? "+" : "") + mul[i].toFixed(3) : "—"}</td><td class="num">${ml[i] != null ? (ml[i] > 0 ? "+" : "") + Number(ml[i]).toFixed(3) : "—"}</td>${Array.isArray(fk) ? `<td class="num">${fk[i] != null ? fmt(fk[i]) : "—"}</td><td class="num">${Array.isArray(fm) && fm[i] != null ? fmt(fm[i]) : "—"}</td>` : ""}</tr>`).join("")}</table></div>
    <p class="muted small" style="margin:6px 12px 8px">Mulliken 은 기저 의존성이 커 진단용 · meta-Löwdin 이 주값 · 뷰어 «부분 전하» 모드와 같은 값</p></div>`;
  const keys = Object.keys(d).filter(k => typeof d[k] === "number" && /potential|fukui|electrophil|nucleophil|hardness|softness|chemical_potential|ionization|affinity|mep|bde_weakest|li_|adsorption|dipole/.test(k) && !["potential_reference"].includes(k));
  html += `<div class="ws-panel"><div class="ws-ph">반응성 지표</div><div class="scroll-x"><table class="table"><tr><th>지표</th><th class="num">값</th><th>단위</th></tr>
    ${keys.length ? keys.map(k => { const [label, unit] = DESC_LABELS[k] || [k, ""]; return `<tr><td>${esc(label)}</td><td class="num">${fmt(d[k])}</td><td class="small muted">${esc(unit)}${k.includes("potential") && ref ? " vs " + esc(ref) : ""}</td></tr>`; }).join("") : '<tr><td colspan="3" class="muted small">전위·반응성 지표가 없는 작업입니다 (목적 «전자구조 + 산화/환원 전위» 이상에서 계산).</td></tr>'}</table></div></div></div>`;
  const red = d.reduction_potential_gibbs_v ?? d.reduction_potential_v, ox = d.oxidation_potential_gibbs_v ?? d.oxidation_potential_v;
  if (red != null && ox != null) html += `<h3 style="font-size:13px;color:var(--accent);margin-top:16px">전기화학 안정 창</h3>${svgEswBar(red, ox, ref || "Li/Li⁺")}<p class="muted small" style="margin:4px 0 0">ΔG(단열) 기반 · HOMO/LUMO 만으로 안정 전위를 단정하지 않습니다 — 계산 조건(용매·규약)을 함께 기록</p>`;
  if (Array.isArray(d.conformer_populations) && d.conformer_populations.length > 1) html += `<h3 style="font-size:13px;color:var(--accent);margin-top:16px">Conformer Boltzmann 분포 (상대 에너지 kcal/mol)</h3>${svgPops(d.conformer_populations)}`;
  if (d.conformer_sensitivity) html += `<h3 style="font-size:13px;color:var(--accent);margin-top:16px">전위 conformer 민감도 (P0-5)</h3>${htmlConfSens(d.conformer_sensitivity, ref)}`;
  if (d.li_interaction) html += `<h3 style="font-size:13px;color:var(--accent);margin-top:16px">Li⁺ 상호작용 — site 별 결합 · 용매 경쟁 (P0-6)</h3>${htmlLiInteraction(d.li_interaction)}`;
  if (d.bde_all) html += `<h3 style="font-size:13px;color:var(--accent);margin-top:16px">결합별 해리에너지 (BDE)</h3><div class="scroll-x"><table class="kv-table"><tr><th>결합</th><td>BDE 298 K</td><td>0 K (전자)</td><td>ZPE 보정</td><td>고정 구조</td><td>완화</td></tr>
    ${d.bde_all.map(bx => `<tr><th>${esc(bx.bond)}${bx.bond === d.bde_weakest_bond ? ' <span class="badge failed">최약</span>' : ""}</th><td><b>${bx.bde_298_kj != null ? fmt(bx.bde_298_kj) + " kJ/mol" : "—"}</b></td><td>${fmt(bx.bde_kj)}</td><td class="muted">${bx.zpe_correction_kj != null ? bx.zpe_correction_kj : "—"}</td><td class="muted">${bx.bde_frozen_kj ?? "—"}</td><td class="muted">${bx.relaxation_kj != null ? "−" + bx.relaxation_kj : "—"}</td></tr>`).join("")}</table>
    <p class="muted small" style="margin:4px 0 0">문헌 BDE와 직접 비교할 값은 <b>298 K</b> 열입니다 (ZPE + 열운동 + pV 포함). 0 K는 순수 전자에너지 차이입니다.</p></div>`;
  return html;
}
function tabFilesHtml(job, r) {
  let condRows = ""; for (const [k, v] of Object.entries(r.conditions || {})) condRows += `<tr><th>${esc(k)}</th><td>${esc(String(v))}</td></tr>`;
  let provRows = ""; for (const [k, v] of Object.entries(r.provenance || {})) provRows += `<tr><th>${esc(k)}</th><td>${esc(typeof v === "object" ? JSON.stringify(v) : String(v))}</td></tr>`;
  const files = [
    ["input (설정)", "계산 설정 · 프로토콜 카드", `<button class="btn ghost sm" type="button" data-ws-d="cond">보기</button>`],
    [`${esc(job.id)}.log`, "PySCF 원본 로그", `<button class="btn ghost sm" type="button" data-ws-d="raw">Raw log viewer</button> <button class="btn ghost sm" type="button" onclick="window.rbOpenMonitor('${esc(job.id)}')">계산 모니터 →</button>`],
    ["final.xyz", "최종 최적화 구조", `<button class="btn ghost sm" type="button" data-dl="xyz">내려받기</button>`],
    ["trajectory.xyz", "최적화 궤적", `<a class="btn ghost sm" href="/api/jobs/${encodeURIComponent(job.id)}/trajectory">내려받기</a>`],
    ["orbital clouds", `궤도 점 구름 ${ORB_ORDER.filter(k => (r.orbital_clouds || {})[k]).map(k => ORB_LABEL[k]).join(" · ") || "없음"}`, r.orbital_clouds ? `<button class="btn ghost sm" type="button" data-dl="orbcsv">궤도 표 CSV</button>` : '<span class="badge queued">미생성</span>'],
    ["result.json", "결과 전체 (JSON)", `<a class="btn ghost sm" href="/api/export?format=json&ids=${encodeURIComponent(job.id)}">내려받기</a>`],
  ];
  return `<div class="ws-panel" style="margin-bottom:12px"><div class="ws-ph">Files</div><div class="scroll-x"><table class="table"><tr><th>파일</th><th>내용</th><th></th></tr>${files.map(f => `<tr><td class="mono small">${f[0]}</td><td class="small">${f[1]}</td><td>${f[2]}</td></tr>`).join("")}</table></div>
    <p class="muted small" style="margin:6px 12px 8px">엔진 ${esc(r.conditions.engine || "PySCF")} · protocol hash <span class="mono">${esc(String(r.provenance?.protocol_hash || "—").slice(0, 12))}</span>${r.result_origin ? ` · ${esc(r.result_origin)}` : ""}</p></div>
    <div class="ws-drawer" id="ws-drawer" style="margin-top:0">
      <div class="dh"><button class="on" type="button" data-d="log">계산 로그</button><button type="button" data-d="raw">PySCF 원본 로그</button><button type="button" data-d="geom">좌표 · 결합 · 전하</button><button type="button" data-d="cond">계산 조건 전체</button><button type="button" data-d="prov">재현성 정보</button></div>
      <pre id="ws-d-log">${esc((job.logs || []).join("\n"))}</pre>
      <pre id="ws-d-raw" hidden>불러오는 중…</pre>
      <div id="ws-d-geom" hidden class="scroll-x"></div>
      <div id="ws-d-cond" hidden><table class="kv-table" style="margin:6px 0">${condRows}</table>${r.protocol_card ? `<details style="margin:6px 8px"><summary class="small muted">프로토콜 카드</summary><pre class="xyz">${esc(JSON.stringify(r.protocol_card, null, 2))}</pre></details>` : ""}</div>
      <div id="ws-d-prov" hidden>${provRows ? `<table class="kv-table" style="margin:6px 0">${provRows}</table>` : '<div class="small muted" style="padding:8px">재현성 정보 없음</div>'}<details style="margin:6px 0"><summary class="small muted">XYZ 좌표</summary><pre class="xyz">${esc(r.structure_xyz)}</pre></details></div>
    </div>`;
}

/* ── 결과 상세 (B타입 탭 기반 상세 분석형 — 기획서 «QuantumLab B타입 DFT 계산결과 화면») ── */
const WS_TABS = [["summary", "Summary"], ["geometry", "Geometry"], ["orbitals", "Orbitals"], ["freq", "Frequencies"], ["spectra", "Spectra"], ["thermo", "Thermodynamics"], ["charge", "Charge & Reactivity"], ["files", "Files & Logs"]];
function showResult(job) {
  const r = job.result;
  CURRENT_RESULT = r;
  VIEW_MODE = "element";
  WS.sel = null; WS.measure = []; WS.tool = "select";
  if (!ORB_MODES.has(WS.mo.mode) && !["cloud", "mep", "charge"].includes(WS.mo.mode)) WS.mo.mode = "homo";
  if (ORB_MODES.has(WS.mo.mode) && !(r.orbital_clouds || {})[WS.mo.mode]) WS.mo.mode = ORB_ORDER.find(k => (r.orbital_clouds || {})[k]) || "charge";
  const d = r.descriptors;
  $("result-title").textContent = `결과 상세 — ${job.material.name}`;
  const tab = WS.tab || "geometry";
  const need = {spectra: d.uvvis_lambda_max_nm == null ? "TD-DFT" : "", freq: r.thermo && r.thermo.freqs_cm ? "" : (d.zpe_kcal != null ? "" : "열보정")};
  let html = wsHeader(job, r) + wsQcRow(job, r)
    + `<div class="tabs ws-tabs" id="ws-maintabs">${WS_TABS.map(([k, l]) => `<button class="tab ${k === tab ? "active" : ""}" type="button" data-t="${k}">${l}${need[k] ? `<span class="need">${need[k]}</span>` : ""}</button>`).join("")}</div>`
    + WS_TABS.map(([k]) => `<div class="ws-tabpane" id="ws-t-${k}" ${k === tab ? "" : "hidden"}></div>`).join("");
  $("result-body").innerHTML = html;
  const body = $("result-body");
  const rendered = new Set();
  const renderTab = k => {
    if (rendered.has(k)) return; rendered.add(k);
    const pane = $("ws-t-" + k);
    try {
      if (k === "summary") { pane.innerHTML = tabSummaryHtml(job, r); wireSummary(job, r, pane); }
      else if (k === "geometry") { pane.innerHTML = tabGeometryHtml(job, r); wireGeometry(job, r, pane); }
      else if (k === "orbitals") { renderOrbitalCompare(job, pane, {embedded: true}); }
      else if (k === "freq") pane.innerHTML = tabFreqHtml(job, r);
      else if (k === "spectra") pane.innerHTML = tabSpectraHtml(job, r);
      else if (k === "thermo") pane.innerHTML = tabThermoHtml(job, r);
      else if (k === "charge") { pane.innerHTML = tabChargeHtml(job, r); pane.querySelectorAll("tr[data-atom]").forEach(tr => tr.addEventListener("click", () => { WS.sel = +tr.dataset.atom; WS.redraw && WS.redraw(); })); }
      else if (k === "files") { pane.innerHTML = tabFilesHtml(job, r); wireFiles(job, r, pane); }
    } catch (e) { console.error("tab", k, e); pane.innerHTML = `<p class="form-error">탭을 그리지 못했습니다: ${esc(e.message)}</p>`; }
    pane.querySelectorAll("[data-ws-rerun]").forEach(b => b.addEventListener("click", () => { if (window.rbPrefillCalc) window.rbPrefillCalc(job); }));
    pane.querySelectorAll("[data-dl]").forEach(b => b.addEventListener("click", () => wsDownload(job, r, b.dataset.dl)));
  };
  const goTab = k => {
    WS.tab = k;
    body.querySelectorAll("#ws-maintabs .tab").forEach(b => b.classList.toggle("active", b.dataset.t === k));
    WS_TABS.forEach(([x]) => { const p = $("ws-t-" + x); if (p) p.hidden = x !== k; });
    renderTab(k);
    if (k === "geometry" || k === "orbitals") rbNextFrame(() => { WS.redraw && WS.redraw(); if (WS.moRedraw) WS.moRedraw(); if (OB.redraw) OB.redraw(); body.querySelectorAll(`#ws-t-${k} .ws-thumb[data-thumb]`).forEach(t => render3D(r, {box: t, mode: t.dataset.thumb, static: true})); });
  };
  body.querySelectorAll("#ws-maintabs .tab").forEach(b => b.addEventListener("click", () => goTab(b.dataset.t)));
  body.querySelectorAll("[data-ws-tab-go]").forEach(b => b.addEventListener("click", () => { goTab(b.dataset.wsTabGo); const p = $("ws-t-" + b.dataset.wsTabGo); if (p) p.scrollIntoView({block: "start", behavior: "smooth"}); }));
  body.querySelectorAll("[data-dl]").forEach(b => b.addEventListener("click", () => wsDownload(job, r, b.dataset.dl)));
  const cmp = body.querySelector("[data-ws-compare]"); if (cmp) cmp.addEventListener("click", () => { COMPARE_SEL.add(job.id); if (window.rbToast) window.rbToast(`«${job.material.name}» 을 물질 비교에 추가했습니다 (${COMPARE_SEL.size}건)`); if (COMPARE_SEL.size >= 2 && window.rbOpenMode) window.rbOpenMode("compare", "물질 비교"); });
  const orbBtn = body.querySelector("[data-ws-orbital]"); if (orbBtn) orbBtn.addEventListener("click", () => { if (window.rbOpenOrbital) window.rbOpenOrbital(job.id); });
  const cls = body.querySelector("[data-ws-close]"); if (cls) cls.addEventListener("click", () => { $("result-card").style.display = "none"; if (typeof SELECTED_RESULT !== "undefined") SELECTED_RESULT = null; });
  $("result-card").style.display = "";
  r.grids = RB_GRIDS[job.id] || null;
  goTab(tab);
  if (!r.grids && r.grids_available) wsLoadGrids(job).then(g => { if (!g) return; WS.moRedraw && WS.moRedraw(); OB.redraw && OB.redraw(); body.querySelectorAll(".ws-thumb[data-thumb]").forEach(t => render3D(r, {box: t, mode: t.dataset.thumb, static: true})); const info = $("ws-mo-info"); if (info) info.innerHTML = orbInfoTable(r, WS.mo.mode); if (OB.refreshTrans) OB.refreshTrans(); });
}
function wsDownload(job, r, what) {
  const base = `rhobench-${job.id}`;
  if (what === "xyz") downloadText(`${base}.xyz`, r.structure_xyz, "chemical/x-xyz");
  else if (what === "xyzcsv") downloadText(`${base}-xyz.csv`, "index,atom,x,y,z\n" + parseXyz(r.structure_xyz).map((a, i) => `${i + 1},${a.el},${a.x},${a.y},${a.z}`).join("\n"), "text/csv");
  else if (what === "orbcsv") downloadText(`${base}-orbitals.csv`, orbitalCsv(job, r), "text/csv");
}
function orbitalCsv(job, r) {
  const lv = orbLevelsOf(r), oc = r.orbital_clouds || {};
  const rows = [["job", job.id], ["molecule", job.material.name], ["method", r.conditions.method], ["solvent", r.conditions.solvent_model], ["energy_unit", "eV"], []];
  rows.push(["label", "mo_index", "energy_ev", "occupation", "contribution_method", "top_atoms_pct"]);
  for (const l of (lv ? lv.levels : [])) { const k = ORB_BY_LABEL[l.label], c = k && oc[k] && oc[k].contributions; rows.push([l.label, l.index != null ? l.index + 1 : "", l.energy_ev, l.occ, c ? c.method : "", c ? c.atoms.map(a => `${a.atom} ${a.pct}`).join("; ") : ""]); }
  return rows.map(x => x.map(v => `"${String(v ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
}
function wireSummary(job, r, pane) {
  const d = r.descriptors, ref = d.potential_reference;
  pane.querySelectorAll("[data-pin]").forEach(b => b.addEventListener("click", () => { const msg = togglePin(b.dataset.pin); const box = $("pin-msg"); if (msg) { if (box) box.textContent = msg; return; } if (box) box.textContent = ""; WS.tab = "summary"; showResult(job); }));
  if ($("fp-axis-picker")) { const redraw = () => { renderAxisPicker("fp-axis-picker", redraw); $("fp-radar").innerHTML = svgRadar(d); }; redraw(); }
  pane.querySelectorAll("[data-ws-mode]").forEach(b => b.addEventListener("click", () => { WS.mo.mode = b.dataset.wsMode; WS.tab = "geometry"; showResult(job); }));
  const tabs = $("ws-tabs");
  if (tabs) tabs.querySelectorAll("button").forEach(b => b.addEventListener("click", () => { tabs.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b)); ["conv", "el", "vib", "uv", "esw"].forEach(k => { const el = $("ws-p-" + k); if (el) el.hidden = k !== b.dataset.p; }); }));
  if ($("ws-p-el")) $("ws-p-el").innerHTML = d.homo_ev != null && d.lumo_ev != null ? svgLevels(d.homo_ev, d.lumo_ev, d.gap_ev) + svgHomoLumoAxis([{name: job.material.name, homo: d.homo_ev, lumo: d.lumo_ev, idx: 0}]) + `<p class="muted small" style="margin:4px 0 0">막대 왼쪽 끝 = HOMO, 오른쪽 끝 = LUMO · 점선 = 전극 페르미 준위 근사 μ ≈ −(1.44 + V) eV</p>` : '<p class="muted small">준위 데이터 없음</p>';
  if ($("ws-p-vib")) $("ws-p-vib").innerHTML = svgVibSpectrum(r.thermo?.freqs_cm, r.thermo?.ir_intensities);
  if ($("ws-p-uv")) $("ws-p-uv").innerHTML = d.uvvis_lambda_max_nm != null ? `<div class="stat-row" style="margin:6px 0 0"><div class="stat-tile"><div class="stat-label">λmax</div><div class="stat-value">${fmt(d.uvvis_lambda_max_nm)}<span class="stat-unit"> nm</span></div><div class="stat-sub">수직 여기 ${fmt(d.uvvis_excitation_ev)} eV · f = ${fmt(d.uvvis_osc_strength)}</div></div></div>` : '<p class="muted small">TDDFT 결과가 없습니다 — «물성 지문» 목적으로 계산한 작업에 표시됩니다.</p>';
  const red = d.reduction_potential_gibbs_v ?? d.reduction_potential_v, ox = d.oxidation_potential_gibbs_v ?? d.oxidation_potential_v;
  if ($("ws-p-esw")) $("ws-p-esw").innerHTML = red != null && ox != null ? svgEswBar(red, ox, ref || "Li/Li⁺") : '<p class="muted small">전위가 계산되지 않은 작업입니다 (목적 «전자구조 + 산화/환원 전위» 이상).</p>';
  (async () => {
    const box = $("ws-p-conv"); if (!box) return;
    try {
      const res = await fetch(`/api/jobs/${encodeURIComponent(job.id)}/monitor`);
      if (!res.ok) throw new Error("HTTP " + res.status);
      const m = await res.json(), runs = m.scf_history?.runs || [], opt = m.opt_history?.runs || [];
      box.innerHTML = runs.length ? `<div class="ws-conv"><div>${svgScfRuns(runs)}</div><div class="ws-convdone"><b>${runs[runs.length - 1].converged === false ? "✗ 미수렴" : "✓ 수렴 완료"}</b>${(() => { const last = runs[runs.length - 1], c = last.cycles[last.cycles.length - 1] || {}; return `Final ΔE = ${c.delta_e != null ? Number(c.delta_e).toExponential(1) : "—"}<br>Iterations: ${last.cycles.length}<br>|g| ${c.gorb != null ? Number(c.gorb).toExponential(1) : "—"}<br>run ${runs.length}/${m.scf_history.total_runs}`; })()}</div></div>${opt.length ? `<div class="small muted" style="margin-top:6px">구조 최적화 ${opt.length} run</div>${svgOptRuns(opt)}` : ""}` : '<p class="muted small">SCF 이력이 없습니다 (이전 버전 계산 또는 배치 결과).</p>';
    } catch (e) { box.innerHTML = `<p class="muted small">수렴 이력을 불러오지 못했습니다 (${esc(e.message)}).</p>`; }
  })();
  rbNextFrame(() => pane.querySelectorAll(".ws-thumb[data-thumb]").forEach(t => render3D(r, {box: t, mode: t.dataset.thumb, static: true})));
}
function wireGeometry(job, r, pane) {
  const atoms = parseXyz(r.structure_xyz);
  const xyzHi = i => pane.querySelectorAll("#ws-xyz tr[data-atom]").forEach(tr => tr.classList.toggle("row-active", +tr.dataset.atom === i));
  const onPick = i => { if (WS.tool !== "measure") { wsAtomCard(r, i); xyzHi(i); } };
  const drawMain = () => render3D(r, {onPick});
  const drawMo = () => { WS.moRedraw = render3D(r, {box: $("viewer3d-mo"), mode: WS.mo.mode, view: WS.mo, cam: WS.mo.sync ? WS : WS.mo.cam, onPick}); };
  const setMo = m => {
    WS.mo.mode = m;
    const sel = $("ws-mo-sel"); if (sel) sel.value = m;
    pane.querySelectorAll("[data-ws-mo]").forEach(b => b.classList.toggle("on", b.dataset.wsMo === m));
    const info = $("ws-mo-info"); if (info) info.innerHTML = orbInfoTable(r, m);
    const oc = (r.orbital_clouds || {})[m], note = $("ws-mo-note");
    if (note) note.textContent = ORB_MODES.has(m) ? (oc ? `${ORB_LABEL[m]} ${fmtE(oc.energy_ev)} ${unitE()} · ${(r.grids || {})[m] ? "등가면 ±" + WS.mo.iso.toFixed(3) + " a.u. — 붉은 lobe = + 위상 · 파란 lobe = − 위상" : "점 구름(격자 없음) — 붉은 점 = + 위상 · 파란 점 = − 위상"}` : "궤도 데이터 없음 — 이전 버전 계산 또는 배치 결과") : (m === "cloud" ? "전자밀도 — 점의 밀집도 ∝ ρ(r)" : m === "mep" ? "정전위 근사 — 전자밀도 표면을 가까운 원자의 부분 전하로 색칠" : "부분 전하 — 파랑 음전하 · 빨강 양전하");
    const lv = $("ws-levels"); if (lv) { lv.innerHTML = svgOrbitalLevels(orbLevelsOf(r), {active: ORB_LABEL[m], compact: true, height: 210}); lv.querySelectorAll("[data-lv]").forEach(g => g.addEventListener("click", () => { const k = ORB_BY_LABEL[g.dataset.lv]; if (k && (r.orbital_clouds || {})[k]) setMo(k); })); }
    drawMo();
  };
  pane.querySelectorAll("[data-geo]").forEach(b => b.addEventListener("click", () => { VIEW_MODE = b.dataset.geo; pane.querySelectorAll("[data-geo]").forEach(x => x.classList.toggle("on", x === b)); drawMain(); }));
  pane.querySelectorAll("[data-ws-tool]").forEach(b => b.addEventListener("click", () => {
    const t = b.dataset.wsTool;
    if (t === "reset") { WS.yaw = 0.6; WS.pitch = -0.4; WS.zoom = 1; WS.sel = null; WS.measure = []; $("ws-atom").style.display = "none"; xyzHi(-1); }
    else if (t === "label") { WS.labels = !WS.labels; b.classList.toggle("on", WS.labels); }
    else if (t === "zoomin") WS.zoom = Math.min(5, WS.zoom * 1.2);
    else if (t === "zoomout") WS.zoom = Math.max(0.3, WS.zoom / 1.2);
    else if (t === "full") { const v = $("viewer3d"); if (v && v.requestFullscreen) v.requestFullscreen(); return; }
    else if (t === "shot") { const c = $("viewer3d").querySelector("canvas"); if (c) { const a = document.createElement("a"); a.href = c.toDataURL("image/png"); a.download = `rhobench-${job.id}-geometry.png`; a.click(); } return; }
    else { WS.tool = t; WS.measure = []; pane.querySelectorAll("[data-ws-tool='select'],[data-ws-tool='measure']").forEach(x => x.classList.toggle("on", x.dataset.wsTool === t)); }
    if (t === "label") { WS.redraw && WS.redraw(); WS.moRedraw && WS.moRedraw(); } else { drawMain(); drawMo(); }
  }));
  pane.querySelectorAll("#ws-xyz tr[data-atom]").forEach(tr => tr.addEventListener("click", () => { WS.sel = +tr.dataset.atom; WS.redraw && WS.redraw(); WS.moRedraw && WS.moRedraw(); wsAtomCard(r, WS.sel); xyzHi(WS.sel); }));
  const sel = $("ws-mo-sel"); if (sel) sel.addEventListener("change", e => setMo(e.target.value));
  pane.querySelectorAll("[data-ws-mo]").forEach(b => b.addEventListener("click", () => setMo(b.dataset.wsMo)));
  const iso = $("ws-mo-iso"); if (iso) iso.addEventListener("input", e => { WS.mo.iso = e.target.value / 100; const lab = $("ws-mo-isov"); if (lab) lab.textContent = WS.mo.iso.toFixed(2); WS.moRedraw && WS.moRedraw(); const info = $("ws-mo-info"); if (info) info.innerHTML = orbInfoTable(r, WS.mo.mode); });
  const al = $("ws-mo-alpha"); if (al) al.addEventListener("input", e => { WS.mo.alpha = e.target.value / 10; WS.moRedraw && WS.moRedraw(); });
  pane.querySelectorAll("[data-mo-tool]").forEach(b => b.addEventListener("click", () => {
    const t = b.dataset.moTool;
    if (t === "surface") { WS.mo.style = WS.mo.style === "iso" ? "cloud" : WS.mo.style === "cloud" ? "none" : "iso"; b.classList.toggle("on", WS.mo.style !== "none"); const lb = b.querySelector("[data-mo-style-label]"); if (lb) lb.textContent = WS.mo.style === "cloud" ? "점 구름" : WS.mo.style === "none" ? "숨김" : "등가면"; WS.moRedraw && WS.moRedraw(); }
    else if (t === "sync") { WS.mo.sync = !WS.mo.sync; b.classList.toggle("on", WS.mo.sync); if (WS.mo.sync) Object.assign(WS.mo.cam, {yaw: WS.yaw, pitch: WS.pitch, zoom: WS.zoom}); drawMo(); }
    else if (t === "reset") { Object.assign(WS.mo.cam, {yaw: 0.6, pitch: -0.4, zoom: 1}); if (WS.mo.sync) { WS.yaw = 0.6; WS.pitch = -0.4; WS.zoom = 1; drawMain(); } drawMo(); }
  }));
  drawMain();
  setMo(WS.mo.mode);
  rbNextFrame(() => pane.querySelectorAll(".ws-thumb[data-thumb]").forEach(t => render3D(r, {box: t, mode: t.dataset.thumb, static: true})));
}
function wireFiles(job, r, pane) {
  const drawer = $("ws-drawer");
  const open = async k => {
    drawer.querySelectorAll("[data-d]").forEach(x => x.classList.toggle("on", x.dataset.d === k));
    ["log", "raw", "geom", "cond", "prov"].forEach(x => { const el = $("ws-d-" + x); if (el) el.hidden = x !== k; });
    if (k === "raw" && $("ws-d-raw").dataset.loaded !== "1") {
      try { const res = await fetch(`/api/jobs/${encodeURIComponent(job.id)}/log?tail=200`); const t = await res.json(); $("ws-d-raw").textContent = t.exists ? (t.note ? "# " + t.note + "\n" : "") + t.text : (t.note || "원본 로그가 없습니다."); }
      catch (e) { $("ws-d-raw").textContent = "원본 로그를 불러오지 못했습니다."; }
      $("ws-d-raw").dataset.loaded = "1";
    }
    if (k === "geom" && !$("ws-d-geom").innerHTML) {
      const atoms = parseXyz(r.structure_xyz), bonds = bondList(atoms), q = r.mulliken_charges || [];
      $("ws-d-geom").innerHTML = `<table class="table" style="min-width:520px"><tr><th>원자</th><th class="num">x (Å)</th><th class="num">y (Å)</th><th class="num">z (Å)</th><th class="num">Mulliken</th><th>결합</th></tr>${atoms.map((a, i) => `<tr><td>${esc(a.el)}${i + 1}</td><td class="num">${a.x.toFixed(3)}</td><td class="num">${a.y.toFixed(3)}</td><td class="num">${a.z.toFixed(3)}</td><td class="num">${q[i] != null ? (q[i] > 0 ? "+" : "") + q[i].toFixed(3) : "—"}</td><td class="small">${bonds.filter(bb => bb[0] === i || bb[1] === i).map(bb => { const j = bb[0] === i ? bb[1] : bb[0]; return atoms[j].el + (j + 1) + " " + bb[2].toFixed(2); }).join(", ")}</td></tr>`).join("")}</table>`;
    }
  };
  drawer.querySelectorAll("[data-d]").forEach(b => b.addEventListener("click", () => open(b.dataset.d)));
  pane.querySelectorAll("[data-ws-d]").forEach(b => b.addEventListener("click", () => { open(b.dataset.wsD); drawer.scrollIntoView({block: "nearest", behavior: "smooth"}); }));
}

/* ── 분자 오비탈 비교 분석 (기획서 «QuantumLab 오비탈 비교 화면») ──
   4분할 뷰어(HOMO−1·HOMO·LUMO·LUMO+1) · 동기화 회전 · 준위도 · 특성표 · 전이 분석 · Redox/Li⁺ */
const OB = {cam: {yaw: 0.6, pitch: -0.4, zoom: 1}, cams: {}, views: {}, sync: true, style: "iso", alpha: 0.7, labels: false, active: "homo", jobId: null, trans: 0, redraw: null};
ORB_ORDER.forEach(k => { OB.cams[k] = {yaw: 0.6, pitch: -0.4, zoom: 1}; OB.views[k] = {iso: 0.03, alpha: 0.7, style: "iso", labels: false}; });
function obJobs() { return (typeof JOBS_CACHE !== "undefined" ? JOBS_CACHE : []).filter(j => j.status === "PUBLISHED" && j.result && j.result.orbital_clouds && ORB_ORDER.some(k => j.result.orbital_clouds[k])); }
function renderOrbitalCompare(job, box, opts = {}) {
  const r = job.result, d = r.descriptors || {}, oc = r.orbital_clouds || {}, lv = orbLevelsOf(r), u = unitE();
  OB.jobId = job.id; OB.draws = {};
  r.grids = RB_GRIDS[job.id] || r.grids || null;
  const q = id => box.querySelector("#" + id);   // 결과 탭에 내장될 때 전역 id 충돌을 피한다
  if (!oc[OB.active]) OB.active = ORB_ORDER.find(k => oc[k]) || "homo";
  const card = k => { const o = oc[k]; return `<div class="ob-card ${k === OB.active ? "on" : ""}" data-card="${k}">
      <div class="ob-h"><div><b>${ORB_LABEL[k]}</b>${o ? `<div class="e ${o.occ > 0 || k.startsWith("homo") ? "occ" : "vir"}">${fmtE(o.energy_ev)} ${esc(u)} <span class="muted small">· MO ${o.index + 1} · occ ${o.occ ?? (k.startsWith("homo") ? 2 : 0)}</span></div>` : '<div class="muted small">궤도 데이터 없음</div>'}</div>
        <div class="ics"><button class="ws-tool" type="button" data-ob-reset="${k}" title="시점 초기화"><i>⌂</i></button><button class="ws-tool" type="button" data-ob-shot="${k}" title="PNG 저장"><i>📷</i></button></div></div>
      <div class="ob-view" data-v="${k}">${o ? "" : `<div class="empty small" style="height:100%;justify-content:center">이 결과에는 ${ORB_LABEL[k]} 점 구름이 없습니다<br><span class="muted">이전 버전 계산 또는 배치 결과 — «같은 조건으로 재계산»하면 저장됩니다</span></div>`}</div>
      <div class="ob-iso"><span>등가면</span><input type="range" min="1" max="10" value="${Math.round(OB.views[k].iso * 100)}" data-ob-iso="${k}" ${o ? "" : "disabled"}><span class="mono val" data-ob-isov="${k}">${OB.views[k].iso.toFixed(2)}</span></div></div>`; };
  const propRows = ["lumo+1", "lumo", "homo", "homo-1"].map(k => { const o = oc[k]; return `<tr data-row="${k}" class="${k === OB.active ? "row-active" : ""}"><td style="color:${k.startsWith("homo") ? "#2a78d6" : "#e0663e"};font-weight:700">${ORB_LABEL[k]}</td><td class="num">${o ? fmtE(o.energy_ev) : "—"}</td><td class="num">${o ? (o.occ ?? (k.startsWith("homo") ? 2 : 0)) : "—"}</td><td class="small">${o ? esc(locSummary(o.contributions)) : "—"}</td><td class="small">${o ? esc(contribText(o.contributions)) : "—"}</td></tr>`; }).join("");
  const st = Array.isArray(d.uvvis_states) ? d.uvvis_states : null;
  const transRows = st ? st.map((s, i) => `<tr data-row="${i}" class="${i === OB.trans ? "row-active" : ""}"><td>S${s.state} · ${esc(s.transition || "—")}</td><td class="num">${fmt(s.energy_ev)}</td><td class="num">${s.wavelength_nm != null ? fmt(s.wavelength_nm) : "—"}</td><td class="num">${fmt(s.osc_strength)}</td><td class="num">${s.weight_pct != null ? s.weight_pct + "%" : "—"}</td><td class="small muted">${i === (st.reduce((b, x, j) => x.osc_strength > st[b].osc_strength ? j : b, 0)) ? "가장 밝은 전이" : s.osc_strength < 0.01 ? "약한 전이" : ""}</td></tr>`).join("") : "";
  const red = d.reduction_potential_gibbs_v ?? d.reduction_potential_v, ox = d.oxidation_potential_gibbs_v ?? d.oxidation_potential_v, li = d.li_interaction;
  box.innerHTML = `
    ${r.grids_available ? "" : `<div class="banner warn" style="margin:0 0 10px">이 결과에는 등가면 격자가 없어 궤도를 점 구름으로 보여 줍니다. «같은 조건으로 재계산»하면 논문 그림 같은 매끈한 lobe(등가면)로 표시됩니다.</div>`}
    ${opts.embedded ? "" : `<div class="ws-head" style="margin-bottom:10px"><div class="ws-head-main"><h2>${esc(job.material.name)} <span class="f mono">${esc(job.material.formula || hillFormula(parseXyz(r.structure_xyz)))}</span> <span class="badge published">Completed</span></h2>
        <div class="ws-meta"><b>${esc(r.conditions.method)}</b><span>|</span><span>${esc(r.conditions.solvent_model)}</span><span>|</span><span>${job.finishedAt ? new Date(job.finishedAt * 1000).toLocaleString("ko-KR", {hour12: false}) : ""}</span><span>|</span><span class="mono">${esc(job.id)}</span></div></div>
      <div class="ws-head-acts"><button class="btn" type="button" data-ob-info="1">🗎 계산 정보 (결과 상세)</button><button class="btn" type="button" data-dl="orbcsv">🗎 CSV 내보내기</button></div></div>`}
    <div class="ob-bar">
      <span class="small muted">보기 방식</span><span class="seg" id="ob-viewseg"><button class="on" type="button" data-v="3d">⊕ 3D</button><button type="button" data-v="x">X축</button><button type="button" data-v="y">Y축</button><button type="button" data-v="z">Z축</button></span>
      <span class="small muted">표시 모드</span><span class="seg" id="ob-modeseg"><button class="${OB.style === "iso" ? "on" : ""}" type="button" data-m="iso" title="격자가 있는 결과는 매끈한 등가면, 없으면 점 구름">등가면</button><button class="${OB.style === "cloud" ? "on" : ""}" type="button" data-m="cloud">점 구름</button><button class="${OB.style === "none" ? "on" : ""}" type="button" data-m="none">골격만</button></span>
      <button class="btn sm ${OB.sync ? "primary" : ""}" type="button" id="ob-sync">⧉ 동기화 회전 ${OB.sync ? "켜짐" : "꺼짐"}</button>
      <button class="btn sm ${OB.labels ? "primary" : ""}" type="button" id="ob-labels">Aa 원자 번호</button>
      <label class="small muted" style="margin-left:auto;display:flex;gap:6px;align-items:center">공통 등가면 <input type="range" id="ob-iso-all" min="1" max="10" value="3" style="width:90px;accent-color:var(--accent)"> <span class="mono" id="ob-iso-all-v">0.03</span></label>
      <label class="small muted" style="display:flex;gap:6px;align-items:center">불투명도 <input type="range" id="ob-alpha" min="2" max="10" value="${Math.round(OB.alpha * 10)}" style="width:70px;accent-color:var(--accent)"></label>
      <button class="btn sm" type="button" id="ob-full">⛶ 전체 화면</button>
    </div>
    <div class="ob-grid">
      <div>
        <div class="ob-quad" id="ob-quad">${ORB_ORDER.map(card).join("")}</div>
        <div class="ob-trans">
          <div class="ws-panel"><div class="ws-ph">전이 분석 <span class="muted small" style="font-weight:400">Transition Analysis</span><span class="sp">${st ? `<span class="badge published">TD-DFT ${st.length} states</span>` : '<span class="badge review">TD-DFT 결과 없음</span>'}</span></div>
            ${st ? `<div class="scroll-x"><table class="table" id="ob-ttable"><tr><th>전이</th><th class="num">ΔE (eV)</th><th class="num">파장 (nm)</th><th class="num">진동자 세기 f</th><th class="num">주 기여</th><th>비고</th></tr>${transRows}</table></div><p class="muted small" style="margin:6px 12px 8px">수직 여기(TD-DFT) · 주 기여 = X 진폭 최대 궤도쌍의 가중치 · KS gap 을 전이 에너지로 재사용하지 않습니다</p>`
              : `<div class="ws-pb"><p class="muted small" style="margin:0">전이 에너지·파장·진동자 세기는 여기상태(TD-DFT) 계산이 있을 때만 표시됩니다. 목적을 «물성 지문»으로 두고 다시 계산하세요.${d.gap_ev != null ? ` 참고: KS HOMO–LUMO gap ${fmtE(d.gap_ev)} ${esc(u)} 은 궤도 에너지 차이이며 광학 여기 에너지가 아닙니다.` : ""}</p><button class="btn" type="button" data-ws-rerun="${esc(job.id)}" style="align-self:flex-start">이 구조·조건으로 재계산 (목적 «물성 지문»)</button></div>`}</div>
          <div class="ws-panel"><div class="ws-ph">전이 시각화 <span class="mono small muted" id="ob-tv-lbl"></span></div><div class="ws-pb">
            <div class="ob-tviz"><div><div class="ob-mini" id="ob-tv-a"></div><div class="lab" id="ob-tv-a-l"></div></div><div><div class="ob-mini" id="ob-tv-b"></div><div class="lab" id="ob-tv-b-l"></div></div></div>
            <table class="ws-kv" id="ob-tv-info"></table></div></div>
        </div>
      </div>
      <div class="ws-col">
        <div class="ws-panel"><div class="ws-ph">에너지 준위도 <span class="muted small" style="font-weight:400">Energy Level Diagram</span><span class="sp small muted">${esc(u)} · 준위 클릭 → 카드 선택</span></div><div class="ws-pb" id="ob-levels"></div></div>
        <div class="ws-panel"><div class="ws-ph">오비탈 특성 비교 <span class="muted small" style="font-weight:400">Orbital Properties</span><span class="sp"><button class="btn ghost sm" type="button" data-dl="orbcsv">CSV</button></span></div>
          <div class="scroll-x"><table class="table" id="ob-ptable"><tr><th>오비탈</th><th class="num">에너지 (${esc(u)})</th><th class="num">점유</th><th>주요 국재화</th><th>기여 원자 (%)</th></tr>${propRows}</table></div>
          <p class="muted small" style="margin:6px 12px 8px">기여도 = Löwdin population (|S^½C|² 원자별 합) · 대칭성은 미분석 → 미표시 · ± 위상은 전하 부호가 아닙니다${lv && lv.spin === "alpha" ? " · 열린 껍질: α 궤도" : ""}</p></div>
        <div class="ws-panel"><div class="ws-ph">Redox / Li⁺ Interaction</div><div class="ws-pb"><table class="ws-kv">
          <tr><th>산화 전위</th><td>${ox != null ? `${fmt(ox)} V vs ${esc(d.potential_reference || "Li/Li⁺")}` : '<span class="muted">미계산</span>'}</td></tr>
          <tr><th>환원 전위</th><td>${red != null ? `${fmt(red)} V${d.conformer_sensitivity && d.conformer_sensitivity.rule ? ` · conformer 민감도 ${esc(d.conformer_sensitivity.rule)}` : ""}` : '<span class="muted">미계산</span>'}</td></tr>
          <tr><th>Li⁺ 결합</th><td>${(() => { if (!li || !Array.isArray(li.sites) || !li.sites.length) return '<span class="muted">미계산</span>'; const best = li.sites.find(x => x.label === li.strongest_site) || li.sites[0]; return `${fmt(best.binding_kj)} kJ/mol (${esc(best.label || "site 1")})${li.exchange_min_kj != null ? ` · ΔE_exchange ${fmt(li.exchange_min_kj)} kJ/mol (용매와 경쟁${li.exchange_min_site ? ", " + esc(li.exchange_min_site) : ""})` : ""}${li.verdict ? ` · ${esc(li.verdict)}` : ""}`; })()}</td></tr>
          <tr><th>KS gap</th><td>${d.gap_ev != null ? `${fmtE(d.gap_ev)} ${esc(u)}` : "—"} <span class="muted small">궤도 차이 — 안정 전압 아님</span></td></tr>
          <tr><th>가정</th><td class="small">${esc(r.conditions.solvent_model)} · ${r.conditions.temperature_k} K · ΔG(단열) · ${esc(d.potential_reference || "Li/Li⁺")} 규약</td></tr></table>
          <p class="muted small" style="margin:0">HOMO/LUMO 만으로 안정 전위를 단정하지 않습니다 — ΔSCF/ΔG 값과 계산 조건을 함께 기록합니다.</p></div></div>
      </div>
    </div>`;
  // ── 4분할 뷰어 ──
  const drawCard = k => { const v = box.querySelector(`.ob-view[data-v="${k}"]`); if (!v || !oc[k]) return; OB.views[k].style = OB.style; OB.views[k].alpha = OB.alpha; OB.views[k].labels = OB.labels; OB.draws[k] = render3D(r, {box: v, mode: k, view: OB.views[k], cam: OB.sync ? OB.cam : OB.cams[k]}); };
  const drawAll = () => ORB_ORDER.forEach(drawCard);
  OB.redraw = () => Object.values(OB.draws).forEach(f => { try { f(); } catch (e) {} });
  const setActive = k => {
    OB.active = k;
    box.querySelectorAll(".ob-card").forEach(c => c.classList.toggle("on", c.dataset.card === k));
    box.querySelectorAll("#ob-ptable tr[data-row]").forEach(tr => tr.classList.toggle("row-active", tr.dataset.row === k));
    const lvBox = q("ob-levels"); if (lvBox) { lvBox.innerHTML = svgOrbitalLevels(lv, {active: ORB_LABEL[k], height: 300}); lvBox.querySelectorAll("[data-lv]").forEach(g => g.addEventListener("click", () => { const kk = ORB_BY_LABEL[g.dataset.lv]; if (kk && oc[kk]) setActive(kk); })); }
  };
  box.querySelectorAll(".ob-card").forEach(c => c.addEventListener("click", e => { if (e.target.closest("input,button")) return; setActive(c.dataset.card); }));
  box.querySelectorAll("#ob-ptable tr[data-row]").forEach(tr => tr.addEventListener("click", () => setActive(tr.dataset.row)));
  box.querySelectorAll("[data-ob-iso]").forEach(sl => sl.addEventListener("input", () => { const k = sl.dataset.obIso; OB.views[k].iso = sl.value / 100; box.querySelector(`[data-ob-isov="${k}"]`).textContent = OB.views[k].iso.toFixed(2); OB.draws[k] && OB.draws[k](); }));
  box.querySelectorAll("[data-ob-reset]").forEach(b => b.addEventListener("click", () => { Object.assign(OB.sync ? OB.cam : OB.cams[b.dataset.obReset], {yaw: 0.6, pitch: -0.4, zoom: 1}); OB.redraw(); }));
  box.querySelectorAll("[data-ob-shot]").forEach(b => b.addEventListener("click", () => { const c = box.querySelector(`.ob-view[data-v="${b.dataset.obShot}"] canvas`); if (c) { const a = document.createElement("a"); a.href = c.toDataURL("image/png"); a.download = `rhobench-${job.id}-${b.dataset.obShot}.png`; a.click(); } }));
  const isoAll = q("ob-iso-all"); if (isoAll) isoAll.addEventListener("input", () => { ORB_ORDER.forEach(k => { OB.views[k].iso = isoAll.value / 100; const s = box.querySelector(`[data-ob-iso="${k}"]`); if (s) s.value = isoAll.value; const t = box.querySelector(`[data-ob-isov="${k}"]`); if (t) t.textContent = OB.views[k].iso.toFixed(2); }); const lv = q("ob-iso-all-v"); if (lv) lv.textContent = (isoAll.value / 100).toFixed(2); OB.redraw(); });
  const alpha = q("ob-alpha"); if (alpha) alpha.addEventListener("input", () => { OB.alpha = alpha.value / 10; ORB_ORDER.forEach(k => OB.views[k].alpha = OB.alpha); OB.redraw(); });
  box.querySelectorAll("#ob-viewseg button").forEach(b => b.addEventListener("click", () => { box.querySelectorAll("#ob-viewseg button").forEach(x => x.classList.toggle("on", x === b)); const v = b.dataset.v, p = v === "x" ? {yaw: Math.PI / 2, pitch: 0} : v === "y" ? {yaw: 0, pitch: -Math.PI / 2 + 0.01} : v === "z" ? {yaw: 0, pitch: 0} : {yaw: 0.6, pitch: -0.4}; Object.assign(OB.cam, p); ORB_ORDER.forEach(k => Object.assign(OB.cams[k], p)); OB.redraw(); }));
  box.querySelectorAll("#ob-modeseg button").forEach(b => b.addEventListener("click", () => { box.querySelectorAll("#ob-modeseg button").forEach(x => x.classList.toggle("on", x === b)); OB.style = b.dataset.m; ORB_ORDER.forEach(k => OB.views[k].style = OB.style); OB.redraw(); }));
  const syncBtn = q("ob-sync"); if (syncBtn) syncBtn.addEventListener("click", () => { OB.sync = !OB.sync; syncBtn.classList.toggle("primary", OB.sync); syncBtn.textContent = `⧉ 동기화 회전 ${OB.sync ? "켜짐" : "꺼짐"}`; if (!OB.sync) ORB_ORDER.forEach(k => Object.assign(OB.cams[k], OB.cam)); drawAll(); });
  const lab = q("ob-labels"); if (lab) lab.addEventListener("click", () => { OB.labels = !OB.labels; lab.classList.toggle("primary", OB.labels); ORB_ORDER.forEach(k => OB.views[k].labels = OB.labels); OB.redraw(); });
  const full = q("ob-full"); if (full) full.addEventListener("click", () => { const q = q("ob-quad"); if (q && q.requestFullscreen) q.requestFullscreen(); });
  if (!OB.fsHooked) { OB.fsHooked = true; document.addEventListener("fullscreenchange", () => setTimeout(() => { OB.redraw && OB.redraw(); WS.redraw && WS.redraw(); }, 60)); }
  const info = box.querySelector("[data-ob-info]"); if (info) info.addEventListener("click", () => { WS.tab = "files"; if (window.rbShowResultJob) window.rbShowResultJob(job.id); });
  box.querySelectorAll("[data-dl]").forEach(b => b.addEventListener("click", () => wsDownload(job, r, b.dataset.dl)));
  box.querySelectorAll("[data-ws-rerun]").forEach(b => b.addEventListener("click", () => { if (window.rbPrefillCalc) window.rbPrefillCalc(job); }));
  // ── 전이 시각화 ──
  const setTrans = i => {
    OB.trans = i;
    const t = st ? st[i] : null;
    const [fromL, toL] = t && t.transition ? t.transition.split(" → ") : ["HOMO", "LUMO"];
    const fk = ORB_BY_LABEL[fromL], tk = ORB_BY_LABEL[toL];
    box.querySelectorAll("#ob-ttable tr[data-row]").forEach(tr => tr.classList.toggle("row-active", +tr.dataset.row === i));
    q("ob-tv-lbl").textContent = `(${fromL} → ${toL})${t ? "" : " · KS 궤도 참고"}`;
    const mini = (id, k, l) => { const el = $(id); el.innerHTML = ""; if (k && oc[k]) render3D(r, {box: el, mode: k, static: true}); else el.innerHTML = `<div class="empty small" style="height:100%;justify-content:center">${esc(l)} 점 구름 없음</div>`; };
    mini("ob-tv-a", fk, fromL); mini("ob-tv-b", tk, toL);
    q("ob-tv-a-l").innerHTML = `<b style="color:#2a78d6">${esc(fromL)}</b>${fk && oc[fk] ? ` (${fmtE(oc[fk].energy_ev)} ${esc(u)})` : ""}`;
    q("ob-tv-b-l").innerHTML = `<b style="color:#e0663e">${esc(toL)}</b>${tk && oc[tk] ? ` (${fmtE(oc[tk].energy_ev)} ${esc(u)})` : ""}`;
    const dE = fk && tk && oc[fk] && oc[tk] ? oc[tk].energy_ev - oc[fk].energy_ev : null;
    q("ob-tv-info").innerHTML = t
      ? `<tr><th>여기 에너지</th><td>${fmt(t.energy_ev)} eV</td></tr><tr><th>파장</th><td>${t.wavelength_nm != null ? fmt(t.wavelength_nm) + " nm" : "—"}</td></tr><tr><th>진동자 세기</th><td>${fmt(t.osc_strength)}</td></tr><tr><th>주 기여</th><td>${esc(t.transition || "—")}${t.weight_pct != null ? ` (${t.weight_pct}%)` : ""}</td></tr><tr><th>궤도 차이</th><td>${dE != null ? `${fmtE(dE)} ${esc(u)} (KS)` : "—"} <span class="muted small">≠ 여기 에너지</span></td></tr><tr><th>근거</th><td class="small">TD-DFT 수직 여기 · 초기/최종 궤도 = 주 기여 궤도쌍</td></tr>`
      : `<tr><th>궤도 차이</th><td>${dE != null ? `${fmtE(dE)} ${esc(u)}` : "—"} <span class="muted small">KS gap — 광학 여기 에너지 아님</span></td></tr><tr><th>여기 에너지</th><td class="muted">TD-DFT 결과 없음</td></tr><tr><th>근거</th><td class="small muted">전이 세기·파장은 여기상태 계산 후 표시됩니다</td></tr>`;
  };
  box.querySelectorAll("#ob-ttable tr[data-row]").forEach(tr => tr.addEventListener("click", () => setTrans(+tr.dataset.row)));
  setActive(OB.active);
  OB.refreshTrans = () => setTrans(st && OB.trans < st.length ? OB.trans : 0);
  rbNextFrame(() => { drawAll(); OB.refreshTrans(); });
  if (!r.grids && r.grids_available) wsLoadGrids(job).then(g => { if (g && OB.jobId === job.id) { drawAll(); OB.refreshTrans(); } });
}
window.rbRenderOrbital = function () {
  const host = $("rbv-orbital"); if (!host) return;
  const jobs = obJobs();
  const cur = jobs.find(j => j.id === OB.jobId) || (typeof SELECTED_RESULT !== "undefined" && jobs.find(j => j.id === SELECTED_RESULT)) || jobs[0];
  const pick = jobs.map(j => `<option value="${esc(j.id)}" ${cur && j.id === cur.id ? "selected" : ""}>${esc(j.material.name)} · ${esc(j.result.conditions.method)} · ${esc(j.id)}</option>`).join("");
  host.innerHTML = `<h1>오비탈 비교</h1><p class="rb-note">HOMO−1 · HOMO · LUMO · LUMO+1 네 궤도를 같은 시점에서 나란히 보고, 에너지 준위·원자 기여도·전이(TD-DFT)를 한 화면에서 검토합니다. 값은 모두 이 컴퓨터의 PySCF 계산 결과입니다.</p>
    <div class="card"><div class="toolbar" style="margin-bottom:${cur ? 12 : 0}px"><label class="small muted">결과 선택</label><select class="input grow" id="ob-job">${pick || '<option value="">궤도 데이터가 있는 완료 결과가 없습니다</option>'}</select><span class="muted small">${jobs.length}건</span></div>
      <div id="ob-body">${cur ? "" : '<div class="empty"><b>표시할 결과가 없습니다</b><span class="small">«계산»에서 분자 하나를 계산하면 HOMO−1/HOMO/LUMO/LUMO+1 점 구름이 저장됩니다 (배치 스크리닝 결과는 용량 절약을 위해 저장하지 않음).</span></div>'}</div></div>`;
  const sel = $("ob-job"); if (sel) sel.addEventListener("change", () => { OB.jobId = sel.value; window.rbRenderOrbital(); });
  if (cur) renderOrbitalCompare(cur, $("ob-body"));
};
window.rbOrbitalSelect = function (jobId) { OB.jobId = jobId; window.rbRenderOrbital(); };

/* ── 물질 비교 보강 (기획서 7.1 · 7.3): 조건 호환성 검사 · 일괄 재계산 · 산점도 ── */
(function () {
  const orig = window.rbRenderCompare;
  if (typeof orig !== "function") return;
  const IS_SNAPSHOT = !!window.__RB_SNAPSHOT__;
  function condKey(j) { const c = j.result?.conditions || {}, e = j.settings?.expert || {}; return `${c.method || ""} | ${c.solvent_model || ""} | 전하 ${e.charge ?? 0} · 다중도 ${e.multiplicity ?? 1}`; }
  function numericKeys(chosen) {
    const keys = [];
    for (const j of chosen) for (const [k, v] of Object.entries(j.result.descriptors || {})) if (typeof v === "number" && !keys.includes(k)) keys.push(k);
    return keys;
  }
  function svgScatter(chosen, xk, yk) {
    const pts = chosen.map((j, i) => ({name: j.material.name, i, x: j.result.descriptors[xk], y: j.result.descriptors[yk]})).filter(p => typeof p.x === "number" && typeof p.y === "number");
    if (pts.length < 2) return '<p class="muted small">두 지표 모두 값이 있는 결과가 2개 이상이어야 합니다.</p>';
    const W = 420, H = 260, L = 56, R = 16, T = 14, B = 40;
    const xs = pts.map(p => p.x), ys = pts.map(p => p.y);
    const pad = (a, b) => { const d = (b - a) || 1; return [a - d * 0.12, b + d * 0.12]; };
    const [x0, x1] = pad(Math.min(...xs), Math.max(...xs)), [y0, y1] = pad(Math.min(...ys), Math.max(...ys));
    const sx = v => L + (v - x0) / (x1 - x0) * (W - L - R), sy = v => H - B - (v - y0) / (y1 - y0) * (H - T - B);
    const mx = axisMeta(xk), my = axisMeta(yk);
    let s = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:560px;height:auto">`;
    for (let k = 0; k <= 4; k++) { const gx = x0 + (x1 - x0) * k / 4, gy = y0 + (y1 - y0) * k / 4; s += `<line x1="${sx(gx)}" y1="${T}" x2="${sx(gx)}" y2="${H - B}" class="gridline"/><line x1="${L}" y1="${sy(gy)}" x2="${W - R}" y2="${sy(gy)}" class="gridline"/><text x="${sx(gx)}" y="${H - B + 14}" text-anchor="middle" class="axis-label">${fmt(gx)}</text><text x="${L - 6}" y="${sy(gy) + 4}" text-anchor="end" class="axis-label">${fmt(gy)}</text>`; }
    s += `<text x="${(L + W - R) / 2}" y="${H - 6}" text-anchor="middle" class="axis-label">${esc(mx.label)}${mx.unit ? ` (${esc(mx.unit)})` : ""}</text><text x="12" y="${T + 8}" class="axis-label">${esc(my.label)}${my.unit ? ` (${esc(my.unit)})` : ""}</text>`;
    for (const p of pts) s += `<circle cx="${sx(p.x)}" cy="${sy(p.y)}" r="6" fill="var(--series-${(p.i % 8) + 1})" opacity="0.9"><title>${esc(p.name)}: ${fmt(p.x)} / ${fmt(p.y)}</title></circle><text x="${sx(p.x) + 9}" y="${sy(p.y) + 4}" class="value-label">${esc(shortName(p.name, 14))}</text>`;
    return s + "</svg>";
  }
  async function rerunSameConditions(ref, others) {
    if (!confirm(`${others.length}개 결과를 «${ref.material.name}»의 조건(${condKey(ref)})으로 다시 계산합니다. 계속할까요?`)) return;
    let ok = 0, fail = [];
    for (const j of others) {
      const settings = {...ref.settings, structure: "모노머", expert: {...(ref.settings?.expert || {})}};
      const body = {customSmiles: j.material.smiles, customName: `${j.material.name} · 재계산`, settings};
      try { const r = await fetch("/api/jobs", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)}); if (r.ok) ok++; else fail.push(`${j.material.name}: ${(await r.json()).detail || r.status}`); }
      catch (e) { fail.push(`${j.material.name}: ${e.message}`); }
    }
    if (window.rbToast) window.rbToast(`재계산 제출 ${ok}건${fail.length ? " · 실패 " + fail.length : ""}`);
    if (fail.length) alert(fail.join("\n"));
  }
  function extras() {
    const box = $("compare-body"); if (!box) return;
    const chosen = JOBS_CACHE.filter(j => j.status === "PUBLISHED" && j.result && COMPARE_SEL.has(j.id));
    if (chosen.length < 2) return;
    const picker = box.querySelector(".mol-grid"); if (!picker) return;
    // 1) 조건 호환성 검사
    const keys = chosen.map(condKey), ref = chosen[0], mism = chosen.filter(j => condKey(j) !== keys[0]);
    const bar = document.createElement("div");
    bar.className = "banner " + (mism.length ? "warn" : "success");
    bar.style.cssText = "display:flex;gap:10px;align-items:center;flex-wrap:wrap";
    bar.innerHTML = mism.length
      ? `⚠ <b>계산 조건이 다른 결과가 섞여 있습니다</b> — ${mism.map(j => `<b>${esc(j.material.name)}</b> (${esc(condKey(j))})`).join(", ")} ↔ 기준 «${esc(ref.material.name)}» (${esc(condKey(ref))}). 직접 수치 비교에 주의하세요.`
        + (IS_SNAPSHOT ? "" : ` <button class="btn" type="button" id="cmp-rerun" style="margin-left:auto">같은 조건으로 일괄 재계산 (${mism.length})</button>`)
      : `✓ 선택한 ${chosen.length}개 결과의 계산 조건이 같습니다 — ${esc(keys[0])}`;
    picker.insertAdjacentElement("afterend", bar);
    if (mism.length && !IS_SNAPSHOT) $("cmp-rerun").addEventListener("click", () => rerunSameConditions(ref, mism));
    // 2) 산점도
    const nk = numericKeys(chosen);
    if (nk.length >= 2) {
      const prefs = rbPrefs(), xk = nk.includes(prefs.scatterX) ? prefs.scatterX : (nk.includes("homo_ev") ? "homo_ev" : nk[0]), yk = nk.includes(prefs.scatterY) ? prefs.scatterY : (nk.includes("lumo_ev") ? "lumo_ev" : nk[1]);
      const opt = sel => nk.map(k => `<option value="${esc(k)}" ${k === sel ? "selected" : ""}>${esc(axisMeta(k).label)}</option>`).join("");
      const sec = document.createElement("div");
      sec.innerHTML = `<h3 style="font-size:13px;color:var(--accent);margin:14px 0 4px">산점도 — 지표 두 개로 후보 배치</h3>
        <div class="toolbar" style="margin-bottom:6px"><label class="small">x <select class="input" id="cmp-sx">${opt(xk)}</select></label><label class="small">y <select class="input" id="cmp-sy">${opt(yk)}</select></label><span class="small muted">점 위에 마우스를 올리면 값 · 목적에 맞는 모서리를 찾으세요</span></div>
        <div id="cmp-scatter">${svgScatter(chosen, xk, yk)}</div>`;
      const anchor = box.querySelector(".stat-row") || bar;
      anchor.insertAdjacentElement("afterend", sec);
      const upd = () => { const p = rbPrefs(); p.scatterX = $("cmp-sx").value; p.scatterY = $("cmp-sy").value; rbSavePrefs(p); $("cmp-scatter").innerHTML = svgScatter(chosen, p.scatterX, p.scatterY); };
      $("cmp-sx").addEventListener("change", upd); $("cmp-sy").addEventListener("change", upd);
    }
  }
  window.rbRenderCompare = function () { orig(); try { extras(); } catch (e) { console.warn("compare extras", e); } };
})();
