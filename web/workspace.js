/* ------------------------------------------------------------------
   결과 워크스페이스 — 기획서(2.1 배치 · 3.1 뷰어 · 5.1 모니터 · 6.1 요약) 반영
     · 뷰어 하나: 구조 / HOMO / LUMO / 전자밀도 / 정전위 / 부분 전하 (하단 썸네일 탭)
     · 원자 클릭 상세 카드, 원자 2~4개 측정(거리·각도·이면각)
     · 오른쪽: 계산 설정(Input) · 계산 진행 상황 · 결과 요약(궤도 미리보기) · 탭 · QC
     · 하단 드로어: 계산 로그 · PySCF 원본 로그 · 좌표·결합·전하 · 재현성
   app.js 뒤에 로드되어 showResult / render3D 를 정의한다 ($, esc, fmt, svg* 는 app.js 전역).
   ------------------------------------------------------------------ */

/* ── 뷰어 상태 (재렌더 사이에 유지) ── */
const WS = {tool: "select", labels: false, sel: null, measure: [], yaw: 0.6, pitch: -0.4, zoom: 1,
            iso: 1.0, alpha: 0.7};
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
  const atoms = parseXyz(r.structure_xyz);
  if (!atoms.length) { box.style.display = "none"; return; }
  const charges = r.mulliken_charges || [];
  const qmax = Math.max(...charges.map(Math.abs), 0.01);
  const solventIdx = new Set();
  if (r.fragments && r.fragments.length > 1) for (const f of r.fragments.slice(1)) for (let i = f.start; i < f.end; i++) solventIdx.add(i);
  const mepPts = r.descriptors?.mep_points;
  const cloud = r.density_cloud;
  const orb = (mode === "homo" || mode === "lumo") ? (r.orbital_clouds || {})[mode] : null;
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

  if (!isStatic) {
    const note = $("viewer3d-note"), legend = $("viewer3d-legend");
    const base = solventIdx.size ? "선명한 분자 = 용질 · 흐린 분자 = 명시적 주변 분자 · " : "";
    const notes = {
      element: "드래그 회전 · 휠 확대 · 원자 클릭 = 상세 카드 (측정 도구: 원자 2~4개 선택)",
      charge: "부분 전하(Mulliken): 파랑 = 음전하(친핵 부위) · 빨강 = 양전하(친전자 부위)",
      cloud: cloud ? "전자구름: 점의 밀집도 ∝ 전자 밀도 ρ(r)" : (r.slimmed ? "배치 결과는 용량 절약을 위해 점 데이터를 저장하지 않습니다 — «계산»에서 단건으로 다시 계산하면 표시됩니다." : "이 결과에는 전자밀도 데이터가 없습니다 (이전 버전 계산). 다시 계산하면 표시됩니다."),
      homo: orb ? `HOMO ${fmt(orb.energy_ev)} eV · 붉은 점 = + 위상, 파란 점 = − 위상 · 점 크기 ∝ |ψ|` : "이 결과에는 궤도 데이터가 없습니다 (이전 버전 계산 또는 배치 결과). 다시 계산하면 표시됩니다.",
      lumo: orb ? `LUMO ${fmt(orb.energy_ev)} eV · 붉은 점 = + 위상, 파란 점 = − 위상 · 점 크기 ∝ |ψ|` : "이 결과에는 궤도 데이터가 없습니다 (이전 버전 계산 또는 배치 결과). 다시 계산하면 표시됩니다.",
      mep: cloud ? "정전위(ESP) 근사: 전자밀도 표면을 가까운 원자의 부분 전하로 색칠 · MEP−/MEP+ 극값은 표식으로" : "정전위 표면을 그리려면 전자밀도 데이터가 필요합니다.",
    };
    if (note) note.textContent = base + (notes[mode] || notes.element);
    if (legend) {
      if (mode === "element") legend.innerHTML = [...new Set(atoms.map(a => a.el))].map(el => `<span class="legend-item"><span class="legend-swatch" style="background:${COLOR[el] ?? "#888"};border:1px solid rgba(0,0,0,.15)"></span>${esc(el)}</span>`).join("");
      else if (mode === "charge" || mode === "mep") legend.innerHTML = `<span class="legend-item"><span class="legend-swatch" style="background:rgb(75,145,216)"></span>음전하 · MEP−</span><span class="legend-item"><span class="legend-swatch" style="background:#fff;border:1px solid var(--border)"></span>중성</span><span class="legend-item"><span class="legend-swatch" style="background:rgb(214,45,40)"></span>양전하 · MEP+</span>`;
      else if (mode === "homo" || mode === "lumo") legend.innerHTML = `<span class="legend-item"><span class="legend-swatch" style="background:#e0663e"></span>+ lobe</span><span class="legend-item"><span class="legend-swatch" style="background:#2a78d6"></span>− lobe</span>`;
      else legend.innerHTML = `<span class="legend-item">점이 촘촘할수록 전자 밀도 ρ(r)가 높은 영역</span>`;
    }
  }

  box.innerHTML = "";
  const canvas = document.createElement("canvas");
  canvas.style.width = "100%"; canvas.style.height = "100%"; canvas.style.cursor = isStatic ? "default" : "grab";
  box.appendChild(canvas);
  const ctx = canvas.getContext("2d");
  let yaw = isStatic ? 0.5 : WS.yaw, pitch = isStatic ? -0.45 : WS.pitch, zoom = isStatic ? 1.05 : WS.zoom;
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
    const dpr = window.devicePixelRatio || 1;
    const W = box.clientWidth || 100, H = box.clientHeight || 100;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const scale = Math.min(W, H) / (span * (isStatic ? 2.3 : 2.6)) * zoom;
    proj = atoms.map((a, i) => ({i, el: a.el, ...project(a.x, a.y, a.z, W, H, scale)}));
    const cloudMode = mode === "cloud" || mode === "mep" || mode === "homo" || mode === "lumo";
    for (const [i, j] of bonds) {
      const p = proj[i], q = proj[j], faded = solventIdx.has(i) || solventIdx.has(j);
      ctx.strokeStyle = faded ? "rgba(140,140,140,.45)" : (cloudMode ? "rgba(60,60,60,.55)" : "rgba(90,90,90,.9)");
      ctx.lineWidth = faded ? 1.4 : (cloudMode ? 1.4 : (isStatic ? 1.6 : 2.6));
      ctx.beginPath(); ctx.moveTo(p.sx, p.sy); ctx.lineTo(q.sx, q.sy); ctx.stroke();
    }
    // 점 구름: 전자밀도 / 정전위 / 궤도
    if ((mode === "cloud" || mode === "mep") && cloud) {
      const rmax = cloud.rho_max || 1;
      const pts = cloud.points.map((q, i) => ({...project(q[0], q[1], q[2], W, H, scale), rho: cloud.rho[i], q: mepColor ? mepColor[i] : 0})).sort((a, b) => a.z - b.z);
      for (const q of pts) {
        const t = Math.min(1, Math.pow(q.rho / rmax, 0.28));
        ctx.globalAlpha = (0.10 + 0.42 * t) * WS.alpha / 0.7;
        ctx.fillStyle = mode === "mep" ? chargeColor(q.q, qmax) : `rgb(${Math.round(70 + 120 * (1 - t))},${Math.round(120 + 60 * (1 - t))},${Math.round(200 + 40 * (1 - t))})`;
        ctx.beginPath(); ctx.arc(q.sx, q.sy, (1.1 + 2.6 * t) * (isStatic ? 0.7 : 1), 0, Math.PI * 2); ctx.fill();
      }
      ctx.globalAlpha = 1;
    }
    if (orb) {
      const amax = orb.abs_max || 1, thr = 0.12 * WS.iso;
      const pts = orb.points.map((q, i) => ({...project(q[0], q[1], q[2], W, H, scale), v: orb.value[i]})).filter(p => Math.abs(p.v) / amax >= thr * 0.5).sort((a, b) => a.z - b.z);
      for (const p of pts) {
        const t = Math.min(1, Math.abs(p.v) / amax);
        ctx.globalAlpha = (0.18 + 0.5 * t) * WS.alpha / 0.7;
        ctx.fillStyle = p.v >= 0 ? "#e0663e" : "#2a78d6";
        ctx.beginPath(); ctx.arc(p.sx, p.sy, (1.2 + 3.2 * t) * (isStatic ? 0.75 : 1), 0, Math.PI * 2); ctx.fill();
      }
      ctx.globalAlpha = 1;
    }
    if (mepPts && (mode === "charge" || mode === "mep") && !isStatic) {
      for (const [kind, pos] of [["min", mepPts.min], ["max", mepPts.max]]) {
        if (!pos) continue;
        const p = project(pos[0], pos[1], pos[2], W, H, scale);
        ctx.setLineDash([3, 2]); ctx.strokeStyle = kind === "min" ? "#2a78d6" : "#e34948"; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(p.sx, p.sy, 9, 0, Math.PI * 2); ctx.stroke(); ctx.setLineDash([]);
        ctx.fillStyle = ctx.strokeStyle; ctx.font = "10px system-ui"; ctx.textAlign = "center";
        ctx.fillText(kind === "min" ? "MEP− (Li⁺ 배위)" : "MEP+", p.sx, p.sy - 12);
      }
    }
    const order = [...proj].sort((a, b) => a.z - b.z);
    for (const p of order) {
      const faded = solventIdx.has(p.i), shrink = cloudMode ? 0.35 : 1;
      const rr = Math.max((rad(p.el) * 0.45 + 0.18) * scale * (faded ? 0.7 : 1) * shrink, 2);
      ctx.globalAlpha = faded ? 0.45 : 1;
      ctx.beginPath(); ctx.arc(p.sx, p.sy, rr, 0, Math.PI * 2);
      ctx.fillStyle = mode === "charge" && charges[p.i] !== undefined ? chargeColor(charges[p.i], qmax) : (COLOR[p.el] ?? "#888");
      ctx.fill();
      ctx.strokeStyle = mode === "charge" ? "rgba(60,60,60,.5)" : "rgba(255,255,255,.6)"; ctx.lineWidth = 1; ctx.stroke();
      if (!isStatic && (WS.sel === p.i || WS.measure.includes(p.i))) { ctx.strokeStyle = "var(--accent)"; ctx.strokeStyle = "#0f766e"; ctx.lineWidth = 2.5; ctx.beginPath(); ctx.arc(p.sx, p.sy, rr + 4, 0, Math.PI * 2); ctx.stroke(); }
      if (!isStatic && !faded) {
        if (mode === "charge" && charges[p.i] !== undefined && p.el !== "H") { ctx.fillStyle = "#333"; ctx.font = "10px ui-monospace,monospace"; ctx.textAlign = "center"; ctx.fillText(charges[p.i].toFixed(2), p.sx, p.sy - rr - 3); }
        else if (WS.labels && p.el !== "H") { ctx.fillStyle = "#333"; ctx.font = "600 10px ui-monospace,monospace"; ctx.textAlign = "center"; ctx.fillText(p.el + (p.i + 1), p.sx, p.sy - rr - 3); }
      }
      ctx.globalAlpha = 1;
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
      ctx.font = "600 12px system-ui"; ctx.textAlign = "center";
      const tw = ctx.measureText(txt).width;
      ctx.fillStyle = "rgba(255,255,255,.9)"; ctx.fillRect(mid.sx - tw / 2 - 5, mid.sy - 30, tw + 10, 18);
      ctx.fillStyle = "#b45309"; ctx.fillText(txt, mid.sx, mid.sy - 17);
    }
  }
  draw();
  if (isStatic) return;
  WS.redraw = draw;
  let dragging = false, moved = false, px = 0, py = 0;
  canvas.addEventListener("mousedown", e => { dragging = true; moved = false; px = e.clientX; py = e.clientY; });
  const up = () => { dragging = false; };
  const move = e => {
    if (!dragging) return;
    if (Math.abs(e.clientX - px) + Math.abs(e.clientY - py) > 2) moved = true;
    WS.yaw = yaw += (e.clientX - px) * 0.01; WS.pitch = pitch = Math.max(-1.5, Math.min(1.5, pitch + (e.clientY - py) * 0.01));
    px = e.clientX; py = e.clientY; draw();
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
  canvas.addEventListener("wheel", e => { e.preventDefault(); WS.zoom = zoom = Math.max(0.3, Math.min(5, zoom * (e.deltaY < 0 ? 1.1 : 0.9))); draw(); }, {passive: false});
}

/* ── 원자 상세 카드 (기획서 3.3) ── */
function wsAtomCard(r, i) {
  const box = $("ws-atom"); if (!box) return;
  const atoms = parseXyz(r.structure_xyz); const a = atoms[i]; if (!a) { box.style.display = "none"; return; }
  const q = (r.mulliken_charges || [])[i];
  const ml = (r.charge_models?.meta_lowdin || r.meta_lowdin_charges || [])[i];
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
  const cards = orbCard("homo_ev", "HOMO", "homo") + orbCard("lumo_ev", "LUMO", "lumo")
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

/* ── 결과 상세 ── */
function showResult(job) {
  const r = job.result;
  CURRENT_RESULT = r;
  VIEW_MODE = "element";
  WS.sel = null; WS.measure = []; WS.tool = "select";
  const d = r.descriptors;
  const ref = d.potential_reference;
  $("result-title").textContent = `결과 상세 — ${job.material.name}`;

  const quick = WS_MODES.map(([m, l]) => `<button class="ws-q ${m === "element" ? "on" : ""}" type="button" data-ws-mode="${m}"><div class="ws-thumb" data-thumb="${m}"></div>${l}</button>`).join("");
  let html = `
    <div class="small muted mono" style="margin-bottom:8px">${esc(job.id)} · ${esc(r.conditions.method)} · ${esc(r.conditions.solvent_model)} ·
      ${esc(String(r.conditions.temperature_k))} K · wall ${r.wall_time_s}s</div>
    ${r.binder_report ? binderScorecard(r.binder_report) : ""}
    <div class="ws-work">
      <div class="ws-panel">
        <div class="ws-ph">Molecule Viewer<span class="sp small muted" id="ws-mode-label">구조</span></div>
        <div class="ws-tools">
          <button class="ws-tool on" type="button" data-ws-tool="select" title="원자 클릭 = 상세 카드"><i>↖</i>선택</button>
          <button class="ws-tool" type="button" data-ws-tool="measure" title="원자 2개 = 거리 · 3개 = 각도 · 4개 = 이면각"><i>⟷</i>측정</button>
          <button class="ws-tool" type="button" data-ws-tool="label" title="원자 번호 표시"><i>Aa</i>라벨</button>
          <button class="ws-tool" type="button" data-ws-tool="zoomin"><i>＋</i>확대</button>
          <button class="ws-tool" type="button" data-ws-tool="zoomout"><i>－</i>축소</button>
          <button class="ws-tool" type="button" data-ws-tool="reset"><i>⌂</i>초기화</button>
          <label class="small muted" id="ws-iso-wrap" style="margin-left:auto;display:none;gap:6px;align-items:center">등가면 <input type="range" id="ws-iso" min="4" max="20" value="10" style="width:80px;accent-color:var(--accent)"></label>
        </div>
        <div id="viewer3d" style="position:relative;width:100%;height:420px;background:radial-gradient(ellipse at 50% 40%,color-mix(in srgb,var(--accent) 6%,var(--surface)) 0%,var(--grid) 90%)">
        </div>
        <div class="ws-atom" id="ws-atom" style="display:none"></div>
        <div class="legend" id="viewer3d-legend" style="padding:6px 12px 0"></div>
        <p class="muted small" id="viewer3d-note" style="margin:4px 12px 8px"></p>
        <div class="ws-quick">${quick}</div>
      </div>
      <div class="ws-col">${wsInputPanel(job, r)}${wsProgressPanel(job, r)}</div>
      ${wsSummaryPanel(job, r)}
    </div>`;

  // ── 이하 기존 결과 구역 (물성 지문 · conformer · Li⁺ · 전체 목록 · BDE · 조건 · 주의사항) ──
  const radar = svgRadar(d);
  if (radar) {
    html += `<div class="grid-2" style="margin-top:16px"><div>
      <h3 style="font-size:13px;color:var(--accent)">물성 지문 (축 선택 가능)</h3>
      <div id="fp-axis-picker"></div>
      <div id="fp-radar">${radar}</div>
      <p class="muted small" style="margin:4px 0 0">
        저장된 PUBLISHED 결과 전체 범위로 min-max 정규화 · 점에 마우스를 올리면 원값·단위 표시 ·
        바깥쪽일수록 스크리닝에 유리한 방향</p></div>`;
    if (d.surface_adsorption) {
      html += `<div><h3 style="font-size:13px;color:var(--accent)">활물질 표면 흡착 에너지</h3>
        ${svgAdsorption(d.surface_adsorption)}
        <p class="muted small" style="margin:4px 0 0">
          막대가 길수록 해당 표면에 강하게 흡착 (E_ad 음수 방향) ·
          대용 클러스터 모델 전제 — 다른 표면 모델·문헌 절대값과 비교 금지</p></div>`;
    }
    html += "</div>";
  } else if (d.surface_adsorption) {
    html += `<h3 style="font-size:13px;color:var(--accent);margin-top:16px">활물질 표면 흡착 에너지</h3>
      ${svgAdsorption(d.surface_adsorption)}`;
  }
  if (Array.isArray(d.conformer_populations) && d.conformer_populations.length > 1) {
    html += `<h3 style="font-size:13px;color:var(--accent);margin-top:16px">
        Conformer Boltzmann 분포 (상대 에너지 kcal/mol)</h3>
      ${svgPops(d.conformer_populations)}`;
  }
  if (d.conformer_sensitivity) {
    html += `<h3 style="font-size:13px;color:var(--accent);margin-top:16px">
        전위 conformer 민감도 (P0-5)</h3>
      ${htmlConfSens(d.conformer_sensitivity, ref)}`;
  }
  if (d.li_interaction) {
    html += `<h3 style="font-size:13px;color:var(--accent);margin-top:16px">
        Li⁺ 상호작용 — site 별 결합 · 용매 경쟁 (P0-6)</h3>
      ${htmlLiInteraction(d.li_interaction)}`;
  }

  const shown = new Set(["potential_reference", "conformer_populations", "conformer_sensitivity", "li_interaction",
                         "mep_points", "surface_adsorption", "bde_all", "bde_weakest_bond"]);
  const ordered = [...PINNED, ...KV_GROUPS.flatMap(g => g[1]), ...Object.keys(d)];
  let listRows = "";
  const seenKey = new Set();
  for (const k of ordered) {
    if (seenKey.has(k) || shown.has(k) || d[k] == null) continue;
    seenKey.add(k);
    const [label, unit] = DESC_LABELS[k] || [k, ""];
    const star = PINNED.has(k);
    const suffix = k.includes("potential") && ref ? ` vs ${ref}` : "";
    listRows += `<tr${star ? ' style="background:color-mix(in srgb,var(--pin) 7%,transparent)"' : ""}>
      <td style="width:30px"><button class="pin-btn ${star ? "on" : ""}" data-pin="${esc(k)}"
        title="클릭하면 ★ 고정 — 레이더 축으로 사용됩니다">${star ? "★" : "☆"}</button></td>
      <td><b>${esc(label)}</b></td>
      <td class="small muted">${esc(unit)}${suffix}</td>
      <td class="num" style="text-align:right;font-variant-numeric:tabular-nums">${fmt(d[k])}</td></tr>`;
  }
  if (r.validation) html += htmlValidationCard(r.validation, job.id);
  html += `<h3 style="font-size:13px;color:var(--accent);margin-top:18px">
      물성 전체 목록 <span class="muted small">(★를 클릭하면 고정 — 레이더 축이 됩니다)</span></h3>
    <div class="scroll-x"><table class="table" style="min-width:520px">
      <tr><th></th><th>물성</th><th>단위</th><th class="num" style="text-align:right">값</th></tr>
      ${listRows}</table></div>
    <div class="form-error" id="pin-msg"></div>`;

  let condRows = "";
  for (const [k, v] of Object.entries(r.conditions)) condRows += `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`;
  let provRows = "";
  for (const [k, v] of Object.entries(r.provenance || {})) provRows += `<tr><th>${esc(k)}</th><td>${esc(typeof v === "object" ? JSON.stringify(v) : String(v))}</td></tr>`;
  if (d.bde_all) {
    html += `<h3 style="font-size:13px;color:var(--accent);margin-top:16px">
        결합별 해리에너지 (BDE)</h3>
      <div class="scroll-x"><table class="kv-table">
        <tr><th>결합</th><td>BDE 298 K</td><td>0 K (전자)</td><td>ZPE 보정</td><td>고정 구조</td><td>완화</td></tr>
        ${d.bde_all.map(bx => `<tr><th>${esc(bx.bond)}${bx.bond === d.bde_weakest_bond
          ? ' <span class="badge failed">최약</span>' : ""}</th>
          <td><b>${bx.bde_298_kj != null ? fmt(bx.bde_298_kj) + " kJ/mol" : "—"}</b></td>
          <td>${fmt(bx.bde_kj)}</td>
          <td class="muted">${bx.zpe_correction_kj != null ? bx.zpe_correction_kj : "—"}</td>
          <td class="muted">${bx.bde_frozen_kj ?? "—"}</td>
          <td class="muted">${bx.relaxation_kj != null ? "−" + bx.relaxation_kj : "—"}</td></tr>`).join("")}
      </table>
      <p class="muted small" style="margin:4px 0 0">문헌 BDE와 직접 비교할 값은 <b>298 K</b> 열입니다
        (ZPE + 열운동 + pV 포함). 0 K는 순수 전자에너지 차이입니다.</p></div>`;
  }
  html += `
    <h3 style="font-size:13px;color:var(--accent);margin-top:14px">주의사항</h3>
    <ul class="log-list">${r.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul>
    <div class="ws-drawer" id="ws-drawer">
      <div class="dh"><button class="on" type="button" data-d="log">계산 로그</button><button type="button" data-d="raw">PySCF 원본 로그</button><button type="button" data-d="geom">좌표 · 결합 · 전하</button><button type="button" data-d="cond">계산 조건 전체</button><button type="button" data-d="prov">재현성 정보</button></div>
      <pre id="ws-d-log">${esc((job.logs || []).join("\n"))}</pre>
      <pre id="ws-d-raw" hidden>불러오는 중…</pre>
      <div id="ws-d-geom" hidden class="scroll-x"></div>
      <div id="ws-d-cond" hidden><table class="kv-table" style="margin:6px 0">${condRows}</table></div>
      <div id="ws-d-prov" hidden>${provRows ? `<table class="kv-table" style="margin:6px 0">${provRows}</table>` : '<div class="small muted" style="padding:8px">재현성 정보 없음</div>'}
        <details style="margin:6px 0"><summary class="small muted">XYZ 좌표</summary><pre class="xyz">${esc(r.structure_xyz)}</pre></details></div>
    </div>`;

  $("result-body").innerHTML = html;
  const body = $("result-body");
  body.querySelectorAll("[data-pin]").forEach(b => b.addEventListener("click", () => {
    const msg = togglePin(b.dataset.pin); const box = $("pin-msg");
    if (msg) { if (box) box.textContent = msg; return; }
    if (box) box.textContent = "";
    showResult(job);
  }));
  if ($("fp-axis-picker")) {
    const redraw = () => { renderAxisPicker("fp-axis-picker", redraw); $("fp-radar").innerHTML = svgRadar(d); };
    redraw();
  }
  // 뷰어 모드 전환 (썸네일 탭 · 궤도 카드)
  const setMode = m => {
    VIEW_MODE = m;
    body.querySelectorAll(".ws-q").forEach(b => b.classList.toggle("on", b.dataset.wsMode === m));
    const lab = $("ws-mode-label"); if (lab) lab.textContent = (WS_MODES.find(x => x[0] === m) || [])[1] || m;
    const isoWrap = $("ws-iso-wrap"); if (isoWrap) isoWrap.style.display = (m === "homo" || m === "lumo" || m === "cloud" || m === "mep") ? "inline-flex" : "none";
    render3D(r, {onPick: i => { if (WS.tool !== "measure") wsAtomCard(r, i); }});
  };
  body.querySelectorAll("[data-ws-mode]").forEach(b => b.addEventListener("click", () => { setMode(b.dataset.wsMode); if (b.classList.contains("orb")) $("viewer3d").scrollIntoView({block: "nearest", behavior: "smooth"}); }));
  body.querySelectorAll("[data-ws-tool]").forEach(b => b.addEventListener("click", () => {
    const t = b.dataset.wsTool;
    if (t === "reset") { WS.yaw = 0.6; WS.pitch = -0.4; WS.zoom = 1; WS.sel = null; WS.measure = []; $("ws-atom").style.display = "none"; }
    else if (t === "label") { WS.labels = !WS.labels; b.classList.toggle("on", WS.labels); }
    else if (t === "zoomin") WS.zoom = Math.min(5, WS.zoom * 1.2);
    else if (t === "zoomout") WS.zoom = Math.max(0.3, WS.zoom / 1.2);
    else { WS.tool = t; WS.measure = []; body.querySelectorAll("[data-ws-tool='select'],[data-ws-tool='measure']").forEach(x => x.classList.toggle("on", x.dataset.wsTool === t)); }
    if (t !== "label") render3D(r, {onPick: i => { if (WS.tool !== "measure") wsAtomCard(r, i); }}); else WS.redraw && WS.redraw();
  }));
  const iso = $("ws-iso"); if (iso) iso.addEventListener("input", e => { WS.iso = e.target.value / 10; WS.redraw && WS.redraw(); });
  body.querySelectorAll("[data-ws-rerun]").forEach(b => b.addEventListener("click", () => { if (window.rbPrefillCalc) window.rbPrefillCalc(job); }));
  // 요약 탭
  const tabs = $("ws-tabs");
  if (tabs) tabs.querySelectorAll("button").forEach(b => b.addEventListener("click", () => {
    tabs.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
    ["conv", "el", "vib", "uv", "esw"].forEach(k => { const el = $("ws-p-" + k); if (el) el.hidden = k !== b.dataset.p; });
  }));
  if ($("ws-p-el")) $("ws-p-el").innerHTML = d.homo_ev != null && d.lumo_ev != null
    ? svgLevels(d.homo_ev, d.lumo_ev, d.gap_ev) + svgHomoLumoAxis([{name: job.material.name, homo: d.homo_ev, lumo: d.lumo_ev, idx: 0}])
      + `<p class="muted small" style="margin:4px 0 0">막대 왼쪽 끝 = HOMO, 오른쪽 끝 = LUMO · 점선 = 전극 페르미 준위 근사 μ ≈ −(1.44 + V) eV</p>`
    : '<p class="muted small">준위 데이터 없음</p>';
  if ($("ws-p-vib")) $("ws-p-vib").innerHTML = svgVibSpectrum(r.thermo?.freqs_cm || r.thermo?.frequencies_cm, r.thermo?.ir_intensities);
  if ($("ws-p-uv")) $("ws-p-uv").innerHTML = d.uvvis_lambda_max_nm != null
    ? `<div class="stat-row" style="margin:6px 0 0"><div class="stat-tile"><div class="stat-label">λmax</div><div class="stat-value">${fmt(d.uvvis_lambda_max_nm)}<span class="stat-unit"> nm</span></div><div class="stat-sub">수직 여기 ${fmt(d.uvvis_excitation_ev)} eV · f = ${fmt(d.uvvis_osc_strength)}</div></div></div>`
    : '<p class="muted small">TDDFT 결과가 없습니다 — «물성 지문» 목적으로 계산한 작업에 표시됩니다.</p>';
  const red = d.reduction_potential_gibbs_v ?? d.reduction_potential_v, ox = d.oxidation_potential_gibbs_v ?? d.oxidation_potential_v;
  if ($("ws-p-esw")) $("ws-p-esw").innerHTML = red != null && ox != null ? svgEswBar(red, ox, ref || "Li/Li⁺") : '<p class="muted small">전위가 계산되지 않은 작업입니다 (목적 «전자구조 + 산화/환원 전위» 이상).</p>';
  // 수렴 그래프 — 모니터 API
  (async () => {
    const box = $("ws-p-conv"); if (!box) return;
    try {
      const res = await fetch(`/api/jobs/${encodeURIComponent(job.id)}/monitor`);
      if (!res.ok) throw new Error("HTTP " + res.status);
      const m = await res.json();
      const runs = m.scf_history?.runs || [], opt = m.opt_history?.runs || [];
      box.innerHTML = runs.length ? `<div class="ws-conv"><div>${svgScfRuns(runs)}</div>
        <div class="ws-convdone"><b>${runs[runs.length - 1].converged === false ? "✗ 미수렴" : "✓ 수렴 완료"}</b>
          ${(() => { const last = runs[runs.length - 1], c = last.cycles[last.cycles.length - 1] || {}; return `Final ΔE = ${c.delta_e != null ? Number(c.delta_e).toExponential(1) : "—"}<br>Iterations: ${last.cycles.length}<br>|g| ${c.gorb != null ? Number(c.gorb).toExponential(1) : "—"}<br>run ${runs.length}/${m.scf_history.total_runs}`; })()}</div></div>
        ${opt.length ? `<div class="small muted" style="margin-top:6px">구조 최적화 ${opt.length} run</div>${svgOptRuns(opt)}` : ""}` : '<p class="muted small">SCF 이력이 없습니다 (이전 버전 계산 또는 배치 결과).</p>';
    } catch (e) { box.innerHTML = `<p class="muted small">수렴 이력을 불러오지 못했습니다 (${esc(e.message)}).</p>`; }
  })();
  // 드로어
  const drawer = $("ws-drawer");
  if (drawer) drawer.querySelectorAll("[data-d]").forEach(b => b.addEventListener("click", async () => {
    drawer.querySelectorAll("[data-d]").forEach(x => x.classList.toggle("on", x === b));
    ["log", "raw", "geom", "cond", "prov"].forEach(k => { const el = $("ws-d-" + k); if (el) el.hidden = k !== b.dataset.d; });
    if (b.dataset.d === "raw" && $("ws-d-raw").dataset.loaded !== "1") {
      try { const res = await fetch(`/api/jobs/${encodeURIComponent(job.id)}/log?tail=200`); const t = await res.json(); $("ws-d-raw").textContent = t.exists ? (t.note ? "# " + t.note + "\n" : "") + t.text : (t.note || "원본 로그가 없습니다."); }
      catch (e) { $("ws-d-raw").textContent = "원본 로그를 불러오지 못했습니다."; }
      $("ws-d-raw").dataset.loaded = "1";
    }
    if (b.dataset.d === "geom" && !$("ws-d-geom").innerHTML) {
      const atoms = parseXyz(r.structure_xyz), bonds = bondList(atoms), q = r.mulliken_charges || [];
      $("ws-d-geom").innerHTML = `<table class="table" style="min-width:520px"><tr><th>원자</th><th class="num">x (Å)</th><th class="num">y (Å)</th><th class="num">z (Å)</th><th class="num">Mulliken</th><th>결합</th></tr>${atoms.map((a, i) => `<tr><td>${esc(a.el)}${i + 1}</td><td class="num">${a.x.toFixed(3)}</td><td class="num">${a.y.toFixed(3)}</td><td class="num">${a.z.toFixed(3)}</td><td class="num">${q[i] != null ? (q[i] > 0 ? "+" : "") + q[i].toFixed(3) : "—"}</td><td class="small">${bonds.filter(bb => bb[0] === i || bb[1] === i).map(bb => { const j = bb[0] === i ? bb[1] : bb[0]; return atoms[j].el + (j + 1) + " " + bb[2].toFixed(2); }).join(", ")}</td></tr>`).join("")}</table>`;
    }
  }));
  $("result-card").style.display = "";
  setMode("element");
  // 썸네일 (정적 렌더) — 레이아웃이 잡힌 뒤
  requestAnimationFrame(() => body.querySelectorAll(".ws-thumb[data-thumb]").forEach(t => render3D(r, {box: t, mode: t.dataset.thumb, static: true})));
}

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
