let PRESETS = null;
let JOBS_CACHE = [];
const selected = new Map();  // key → {key, name, smiles, dictId}

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

/* ---------- 물질 보관함(localStorage) 연동 ---------- */
function loadLibraryMaterials() {
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (!k.startsWith("dft-workbench")) continue;
      const v = JSON.parse(localStorage.getItem(k));
      if (v && Array.isArray(v.materials) && v.materials.length) {
        return v.materials.filter(m => m && m.smiles);
      }
    }
  } catch (e) { /* 보관함 파싱 실패 시 서버 프리셋으로 폴백 */ }
  return null;
}

function buildMaterialGrid() {
  const grid = $("material-grid");
  grid.innerHTML = "";
  const lib = loadLibraryMaterials();
  const presetIds = new Set(PRESETS.materials.map(m => m.id));
  const items = lib
    ? lib.map(m => ({
        key: m.id, name: m.name, smiles: m.smiles, formula: m.formula || "",
        note: (m.type || "") + (m.builtin ? "" : " · 사용자 등록"),
        dictId: presetIds.has(m.dictId) ? m.dictId : null,
      }))
    : PRESETS.materials.map(m => ({
        key: m.id, name: m.name, smiles: m.smiles["모노머"],
        formula: m.formula, note: m.note, dictId: m.id,
      }));
  for (const key of [...selected.keys()]) {
    if (!items.some(it => it.key === key)) selected.delete(key);
  }
  for (const it of items) {
    const btn = document.createElement("button");
    btn.className = "mol-card" + (selected.has(it.key) ? " selected" : "");
    btn.innerHTML = `<b>${esc(it.name)}</b>
      <span class="small muted">${esc(it.formula)}${it.note ? " · " + esc(it.note) : ""}</span>
      <span class="mono small muted">${esc(it.smiles)}</span>`;
    btn.onclick = () => {
      selected.has(it.key) ? selected.delete(it.key) : selected.set(it.key, it);
      btn.classList.toggle("selected", selected.has(it.key));
    };
    grid.appendChild(btn);
  }
}

function rbSelectMaterialByName(name) {
  buildMaterialGrid();
  const card = [...document.querySelectorAll("#material-grid .mol-card")]
    .find(c => c.textContent.includes(name));
  if (card && !card.classList.contains("selected")) card.click();
}
window.rbSelectMaterialByName = rbSelectMaterialByName;

/* ---------- 용매 라이브러리(localStorage) 연동 ---------- */
function loadLibrarySolvents() {
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (!k.startsWith("dft-workbench")) continue;
      const v = JSON.parse(localStorage.getItem(k));
      if (v && Array.isArray(v.solvents) && v.solvents.length) return v.solvents;
    }
  } catch (e) { /* 폴백: 서버 프리셋 */ }
  return null;
}

function buildSolventOptions() {
  const sel = $("solvent");
  const prev = sel.value;
  sel.innerHTML = "";
  sel.add(new Option("(용매 없음 — 기체상)", ""));
  const serverIds = new Set(PRESETS.solvents.map(s => s.id));
  const knownAbbrs = new Set(PRESETS.solvents.filter(s => s.kind === "single").map(s => s.abbr));
  const lib = loadLibrarySolvents();
  const list = lib || PRESETS.solvents;
  for (const s of list) {
    const label = `${s.abbr}${s.kind === "mixed" ? " (혼합)" : ""} — ${s.name}`;
    if (serverIds.has(s.id)) {
      sel.add(new Option(label, s.id));
    } else if (s.kind === "mixed" && (s.components || []).length >= 2
               && s.components.every(c => knownAbbrs.has(c.abbr))) {
      // 사용자 혼합 용매: 성분 SMD 파라미터의 부피 가중 평균으로 서버에서 계산
      const payload = {name: s.abbr || s.name,
                       components: s.components.map(c => ({abbr: c.abbr, ratio: c.ratio}))};
      sel.add(new Option(label + " · 라이브러리", "mix:" + JSON.stringify(payload)));
    } else {
      const opt = new Option(label + " (SMD 파라미터 없음 — 계산 불가)", "");
      opt.disabled = true;
      sel.add(opt);
    }
  }
  if (prev && [...sel.options].some(o => o.value === prev)) sel.value = prev;
  else if ([...sel.options].some(o => o.value === PRESETS.defaults.solventId)) {
    sel.value = PRESETS.defaults.solventId;
  }
}

window.rbReloadMaterials = () => { buildMaterialGrid(); buildSolventOptions(); };

async function init() {
  PRESETS = await (await fetch("/api/presets")).json();

  buildMaterialGrid();

  const envDiv = $("env-radios");
  envDiv.innerHTML = "";
  for (const env of PRESETS.envTypes) {
    const label = document.createElement("label");
    label.className = "radio-row";
    label.innerHTML = `<input type="radio" name="env" value="${esc(env.id)}"
        ${env.id === PRESETS.defaults.envType ? "checked" : ""}>
      <b>${esc(env.id)}</b> <span class="muted small">${esc(env.desc)}</span>`;
    label.querySelector("input").onchange = syncEnvState;
    envDiv.appendChild(label);
  }

  buildSolventOptions();
  fillSelect("atmosphere", PRESETS.atmospheres.map(a => [a, a]), PRESETS.defaults.atmosphere);
  fillSelect("ref-electrode",
    [["없음", "없음 (IP·EA만 보고)"], ...PRESETS.referenceElectrodes.map(r => [r, r + " 기준 전위"])],
    PRESETS.defaults.referenceElectrode);
  fillSelect("structure", PRESETS.structures.map(s => [s, s]), PRESETS.defaults.structure);
  fillSelect("accuracy", Object.keys(PRESETS.accuracy).map(k => [k, k]), PRESETS.defaults.accuracy);
  fillSelect("purpose", PRESETS.purposes.map(p => [p, p]), PRESETS.defaults.purpose);
  fillSelect("functional", PRESETS.functionals.map(f => [f, f]), PRESETS.defaults.expert.functional);
  for (const b of PRESETS.basisSets) $("basis").add(new Option(b, b));

  $("accuracy").onchange = syncAccuracyDesc;
  syncAccuracyDesc();
  syncEnvState();
  $("add-explicit").onclick = () => addExplicitRow();
  $("submit-btn").onclick = submit;
  $("lookup-btn").onclick = doLookup;
  $("lookup-q").addEventListener("keydown", e => { if (e.key === "Enter") doLookup(); });
  refreshJobs();
  setInterval(refreshJobs, 2000);
}

/* ---------- 명시적 주변 분자 ---------- */
function addExplicitRow() {
  const row = document.createElement("div");
  row.className = "toolbar";
  row.dataset.explicit = "1";
  row.style.marginBottom = "6px";
  const singles = PRESETS.solvents.filter(s => s.kind === "single");
  row.innerHTML = `
    <select class="input" data-role="species">
      ${singles.map(s => `<option value="${esc(s.smiles)}">${esc(s.abbr)} — ${esc(s.name)}</option>`).join("")}
      <option value="__custom__">사용자 SMILES…</option>
    </select>
    <input class="input" data-role="custom" placeholder="SMILES 입력" style="display:none;width:180px">
    <input class="input" data-role="count" type="number" value="1" min="1" max="10" style="width:80px">
    <span class="muted small">개</span>
    <button class="btn ghost danger" type="button" data-role="remove">삭제</button>`;
  row.querySelector('[data-role="species"]').addEventListener("change", (e) => {
    row.querySelector('[data-role="custom"]').style.display =
      e.target.value === "__custom__" ? "" : "none";
  });
  row.querySelector('[data-role="remove"]').addEventListener("click", () => row.remove());
  $("explicit-rows").appendChild(row);
}

function collectExplicit() {
  const out = [];
  for (const row of document.querySelectorAll('[data-explicit="1"]')) {
    const sel = row.querySelector('[data-role="species"]');
    const smiles = sel.value === "__custom__"
      ? row.querySelector('[data-role="custom"]').value.trim()
      : sel.value;
    if (!smiles) continue;
    const name = sel.value === "__custom__" ? smiles : sel.options[sel.selectedIndex].text.split(" — ")[0];
    const count = Math.max(1, parseInt(row.querySelector('[data-role="count"]').value) || 1);
    out.push({smiles, name, count});
  }
  return out;
}

function fillSelect(id, pairs, def) {
  const sel = $(id);
  sel.innerHTML = "";
  for (const [v, label] of pairs) sel.add(new Option(label, v));
  if (def != null) sel.value = def;
}

function syncAccuracyDesc() {
  $("accuracy-desc").textContent = PRESETS.accuracy[$("accuracy").value] || "";
}

function syncEnvState() {
  const env = document.querySelector('input[name="env"]:checked')?.value;
  $("solvent").disabled = env === "진공·기체";
}

async function submit() {
  $("form-error").textContent = "";
  const env = document.querySelector('input[name="env"]:checked')?.value;
  const chosen = [...selected.values()];
  const body = {
    materialIds: chosen.filter(c => c.dictId).map(c => c.dictId),
    customMaterials: chosen.filter(c => !c.dictId).map(c => ({smiles: c.smiles, name: c.name})),
    customSmiles: $("custom-smiles").value.trim() || null,
    customName: $("custom-name").value.trim() || null,
    settings: {
      envType: env,
      explicitMolecules: collectExplicit(),
      solventId: (env === "진공·기체" || $("solvent").value.startsWith("mix:"))
        ? null : ($("solvent").value || null),
      customMixedSolvent: (env !== "진공·기체" && $("solvent").value.startsWith("mix:"))
        ? JSON.parse($("solvent").value.slice(4)) : null,
      temperature: parseFloat($("temperature").value) || 298.15,
      atmosphere: $("atmosphere").value,
      structure: $("structure").value,
      accuracy: $("accuracy").value,
      purpose: $("purpose").value,
      referenceElectrode: $("ref-electrode").value,
      expert: {
        charge: parseInt($("charge").value) || 0,
        multiplicity: parseInt($("multiplicity").value) || 1,
        nConformers: $("n-conformers").value ? parseInt($("n-conformers").value) : null,
        functional: $("functional").value,
        basis: $("basis").value || null,
        optimizeGeometry: $("optimize").value === "" ? null : $("optimize").value === "true",
        thermochemistry: $("thermo").value === "" ? null : $("thermo").value === "true",
        redoxAdiabatic: $("redox-mode").value === "" ? null : $("redox-mode").value === "true",
        nonequilibriumSolvation: $("noneq-solv").value === "" ? null : $("noneq-solv").value === "true",
        boltzmannEnsemble: $("boltzmann").value === "" ? null : $("boltzmann").value === "true",
        freqScale: $("freq-scale").value ? parseFloat($("freq-scale").value) : null,
      },
    },
  };
  const btn = $("submit-btn");
  btn.disabled = true;
  try {
    const res = await fetch("/api/jobs", {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    await refreshJobs();
    if (window.rbOpenResults) window.rbOpenResults();  // 제출 후 결과 페이지로 이동
  } catch (e) {
    $("form-error").textContent = e.message;
  } finally {
    btn.disabled = false;
  }
}

const badgeClass = {QUEUED: "queued", RUNNING: "running", PUBLISHED: "published", FAILED: "failed"};
const badgeLabel = {QUEUED: "대기", RUNNING: "실행", PUBLISHED: "PUBLISHED", FAILED: "실패"};

async function refreshJobs() {
  const {jobs} = await (await fetch("/api/jobs")).json();
  JOBS_CACHE = jobs;
  const real = document.getElementById("rb-real");
  if (real?.classList.contains("mode-esw") && window.rbRenderEsw) window.rbRenderEsw();
  if (real?.classList.contains("mode-compare") && window.rbRenderCompare) window.rbRenderCompare();
  const list = $("job-list");
  if (!jobs.length) {
    list.className = "empty small";
    list.textContent = "작업이 없습니다.";
    return;
  }
  list.className = "";
  list.innerHTML = "";
  for (const job of jobs) {
    const div = document.createElement("div");
    div.className = "job-row";
    const solvent = PRESETS.solvents.find(s => s.id === job.settings.solventId);
    const method = job.result?.conditions?.method
      || `${job.settings.expert.functional}${job.settings.expert.basis ? "/" + job.settings.expert.basis : ""}`;
    div.innerHTML = `
      <div class="job-main">
        <div><b>${esc(job.material.name)}</b> <span class="mono small muted">${esc(job.id)}</span></div>
        <div class="small muted">${esc(job.settings.envType)} · ${esc(solvent?.abbr ?? "vacuum")} ·
          ${esc(job.settings.structure)} · ${esc(method)} · ${esc(job.settings.accuracy)}</div>
        ${["RUNNING", "QUEUED"].includes(job.status)
          ? `<div class="progress-track"><div class="progress-fill" style="width:${job.progress}%"></div></div>
             <div class="small muted">${esc(job.stage)} · <b>${job.progress}%</b></div>` : ""}
        ${job.error ? `<div class="small" style="color:var(--danger)">${esc(job.error)}</div>` : ""}
        <details><summary class="small muted">로그 (${job.logs.length})</summary>
          <ul class="log-list">${job.logs.map(l => `<li>${esc(l)}</li>`).join("")}</ul></details>
      </div>
      <div class="job-side">
        <span class="badge ${badgeClass[job.status] || "queued"}">${badgeLabel[job.status] || esc(job.status)}</span>
        ${job.status === "PUBLISHED"
          ? `<button class="btn ghost" data-view="${esc(job.id)}">결과 보기</button>` : ""}
        ${["QUEUED", "RUNNING"].includes(job.status)
          ? `<button class="btn ghost danger" data-cancel="${esc(job.id)}">취소</button>`
          : `<button class="btn ghost danger" data-del="${esc(job.id)}">삭제</button>`}
      </div>`;
    div.querySelector("[data-view]")?.addEventListener("click", () => showResult(job));
    div.querySelector("[data-cancel]")?.addEventListener("click", () =>
      fetch(`/api/jobs/${job.id}/cancel`, {method: "POST"}).then(refreshJobs));
    div.querySelector("[data-del]")?.addEventListener("click", () =>
      fetch(`/api/jobs/${job.id}`, {method: "DELETE"}).then(refreshJobs));
    list.appendChild(div);
  }
}

const DESC_LABELS = {
  total_energy_hartree: ["전자 에너지", "Ha"],
  homo_ev: ["HOMO", "eV"], lumo_ev: ["LUMO", "eV"], gap_ev: ["HOMO–LUMO 갭", "eV"],
  dipole_debye: ["쌍극자 모멘트", "D"],
  zpe_kcal: ["영점 진동 에너지 (ZPE)", "kcal/mol"],
  gibbs_correction_kcal: ["깁스 보정 (G − E, 기체상)", "kcal/mol"],
  gibbs_energy_hartree: ["깁스 자유에너지 (E+G보정)", "Ha"],
  entropy_cal_mol_k: ["엔트로피 S", "cal/(mol·K)"],
  n_imaginary_freqs: ["허수 진동수 개수", ""],
  interaction_energy_kcal: ["클러스터 상호작용 에너지", "kcal/mol"],
  solvation_energy_kcal: ["용매화 에너지 ΔE(solv−gas)", "kcal/mol"],
  smd_cds_kcal: ["SMD CDS 항", "kcal/mol"],
  ip_vertical_ev: ["수직 이온화 에너지 (IP)", "eV"],
  ea_vertical_ev: ["수직 전자 친화도 (EA)", "eV"],
  freq_scale_factor: ["진동수 스케일 인자", ""],
  standard_state_corr_kcal: ["1 atm→1 M 표준 상태 보정", "kcal/mol"],
  gibbs_energy_solution_hartree: ["용액상 깁스 자유에너지 (1 M)", "Ha"],
  ip_gibbs_ev: ["ΔG 기반 이온화 에너지", "eV"],
  ea_gibbs_ev: ["ΔG 기반 전자 친화도", "eV"],
  ip_adiabatic_ev: ["단열 이온화 에너지 (IP)", "eV"],
  ea_adiabatic_ev: ["단열 전자 친화도 (EA)", "eV"],
  oxidation_potential_v: ["산화 전위", "V"],
  reduction_potential_v: ["환원 전위", "V"],
  oxidation_potential_gibbs_v: ["산화 전위 (ΔG 기반)", "V"],
  reduction_potential_gibbs_v: ["환원 전위 (ΔG 기반)", "V"],
};

let CURRENT_RESULT = null;
let VIEW_MODE = "element";

/* ---------- 2D 시각화 (모의 앱 차트 문법 재사용) ---------- */
function svgLevels(homo, lumo, gap) {
  const lo = Math.min(homo, lumo) - 1.2, hi = Math.max(homo, lumo) + 1.2;
  const W = 320, H = 230, T = 14, B = 16, L = 44;
  const y = e => T + (hi - e) / (hi - lo) * (H - T - B);
  const step = (hi - lo) > 9 ? 2 : 1;
  let sv = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:330px" role="img">`;
  sv += `<line x1="${L}" y1="${T}" x2="${L}" y2="${H - B}" class="baseline"/>`;
  for (let e = Math.ceil(lo); e <= hi; e += step) {
    sv += `<line x1="${L - 4}" y1="${y(e)}" x2="${L}" y2="${y(e)}" class="baseline"/>
      <text x="${L - 7}" y="${y(e) + 3.5}" text-anchor="end" class="axis-label">${e}</text>`;
  }
  sv += `<text x="10" y="${T + 3}" class="axis-label">eV</text>`;
  const bx = L + 22, bw = 116, gx = bx + bw / 2;
  sv += `<rect x="${bx}" y="${y(lumo) - 4}" width="${bw}" height="8" rx="2"
      fill="none" stroke="var(--pin)" stroke-width="2"/>
    <text x="${bx + bw + 7}" y="${y(lumo) + 4}" class="value-label">LUMO ${lumo} eV</text>`;
  sv += `<line x1="${gx}" y1="${y(lumo) + 7}" x2="${gx}" y2="${y(homo) - 7}"
      stroke="var(--text-2)" stroke-dasharray="3 3"/>
    <text x="${gx + 7}" y="${(y(homo) + y(lumo)) / 2 + 4}" class="value-label">갭 ${gap} eV</text>`;
  sv += `<rect x="${bx}" y="${y(homo) - 4}" width="${bw}" height="8" rx="2" fill="var(--accent)"/>
    <text x="${bx + bw + 7}" y="${y(homo) + 4}" class="value-label">HOMO ${homo} eV</text>`;
  return sv + "</svg>";
}

function svgEswBar(red, ox, ref) {
  const V0 = -0.5, V1 = 5.5, W = 640, H = 96, L = 10;
  const x = v => L + (Math.max(V0, Math.min(V1, v)) - V0) / (V1 - V0) * (W - L - 14);
  let sv = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:680px" role="img">`;
  for (let v = 0; v <= 5; v++) {
    sv += `<line x1="${x(v)}" y1="24" x2="${x(v)}" y2="${H - 26}" class="gridline"/>
      <text x="${x(v)}" y="${H - 13}" text-anchor="middle" class="axis-label">${v}</text>`;
  }
  for (const el of ELECTRODES) {
    sv += `<line x1="${x(el.v)}" y1="16" x2="${x(el.v)}" y2="${H - 26}"
        stroke="var(--pin)" stroke-dasharray="4 3"/>
      <text x="${x(el.v)}" y="11" text-anchor="middle" class="axis-label"
        fill="var(--pin)">${esc(el.label.split(" (")[0])}</text>`;
  }
  sv += `<rect x="${x(red)}" y="38" width="${Math.max(2, x(ox) - x(red))}" height="18" rx="4"
      fill="color-mix(in srgb, var(--accent) 30%, transparent)" stroke="var(--accent)"/>
    <text x="${x(red) - 4}" y="51" text-anchor="end" class="value-label">${red.toFixed(2)}</text>
    <text x="${x(ox) + 4}" y="51" class="value-label">${ox.toFixed(2)}</text>
    <text x="${(x(red) + x(ox)) / 2}" y="${H - 13}" text-anchor="middle"
      class="axis-label">전위 (V vs ${esc(ref)})</text>`;
  return sv + "</svg>";
}

function svgPops(pops) {
  const W = 340, rowH = 24, H = pops.length * rowH + 6;
  let sv = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:360px" role="img">`;
  pops.forEach((c, i) => {
    const y = i * rowH + 4, w = Math.max(2, c.population_pct / 100 * (W - 160));
    sv += `<text x="0" y="${y + 12}" class="axis-label">#${i + 1} (+${c.rel_e_kcal})</text>
      <rect x="78" y="${y}" width="${w}" height="15" rx="3" fill="var(--series-${(i % 8) + 1})"/>
      <text x="${84 + w}" y="${y + 12}" class="value-label">${c.population_pct}%</text>`;
  });
  return sv + "</svg>";
}

/* ---------- 결과 상세 ---------- */
const KV_GROUPS = [
  ["에너지 · 열역학", ["total_energy_hartree", "zpe_kcal", "gibbs_correction_kcal",
    "gibbs_energy_hartree", "entropy_cal_mol_k", "n_imaginary_freqs", "freq_scale_factor",
    "standard_state_corr_kcal", "gibbs_energy_solution_hartree"]],
  ["용매화 · 상호작용 · 전위", ["solvation_energy_kcal", "smd_cds_kcal", "interaction_energy_kcal",
    "ip_vertical_ev", "ea_vertical_ev", "ip_adiabatic_ev", "ea_adiabatic_ev",
    "ip_gibbs_ev", "ea_gibbs_ev", "oxidation_potential_v", "reduction_potential_v",
    "oxidation_potential_gibbs_v", "reduction_potential_gibbs_v"]],
];

function showResult(job) {
  const r = job.result;
  CURRENT_RESULT = r;
  VIEW_MODE = "element";
  const d = r.descriptors;
  const ref = d.potential_reference;
  $("result-title").textContent = `결과 상세 — ${job.material.name}`;

  const tiles = [
    ["HOMO", d.homo_ev, "eV", "최고 점유 궤도"],
    ["LUMO", d.lumo_ev, "eV", "최저 비점유 궤도"],
    ["HOMO–LUMO 갭", d.gap_ev, "eV", "클수록 전자적 안정"],
    ["쌍극자 모멘트", d.dipole_debye, "D", "분자 극성"],
  ].filter(t => t[1] != null).map(([l, v, u, sub]) => `
    <div class="stat-tile"><div class="stat-label">${l}</div>
      <div class="stat-value">${v}<span class="stat-unit"> ${u}</span></div>
      <div class="stat-sub">${sub}</div></div>`).join("");

  let html = `
    <div class="small muted mono" style="margin-bottom:8px">${esc(job.id)} ·
      ${esc(r.conditions.method)} · ${esc(r.conditions.solvent_model)} ·
      ${esc(String(r.conditions.temperature_k))} K · wall ${r.wall_time_s}s</div>
    <div class="stat-row">${tiles}</div>
    <div class="grid-2">
      <div>
        <h3 style="font-size:13px;color:var(--accent)">전자 에너지 준위</h3>
        ${d.homo_ev != null && d.lumo_ev != null
          ? svgLevels(d.homo_ev, d.lumo_ev, d.gap_ev)
          : '<p class="muted small">준위 데이터 없음</p>'}
      </div>
      <div>
        <h3 style="font-size:13px;color:var(--accent)">3D 구조</h3>
        <div class="toolbar" style="margin-bottom:6px">
          <button class="btn" id="v3d-element" type="button">원소 색</button>
          <button class="btn" id="v3d-charge" type="button">부분 전하 색</button>
        </div>
        <div id="viewer3d" style="width:100%;height:280px;position:relative;
          border:1px solid var(--grid);border-radius:10px;overflow:hidden"></div>
        <p class="muted small" id="viewer3d-note" style="margin:6px 0 0"></p>
      </div>
    </div>`;

  const red = d.reduction_potential_gibbs_v ?? d.reduction_potential_v;
  const ox = d.oxidation_potential_gibbs_v ?? d.oxidation_potential_v;
  if (red != null && ox != null) {
    html += `<h3 style="font-size:13px;color:var(--accent);margin-top:16px">
        전기화학 안정 창 (활물질 작동 전위 대비)</h3>
      ${svgEswBar(red, ox, ref || "Li/Li⁺")}`;
  }
  if (Array.isArray(d.conformer_populations) && d.conformer_populations.length > 1) {
    html += `<h3 style="font-size:13px;color:var(--accent);margin-top:16px">
        Conformer Boltzmann 분포 (상대 에너지 kcal/mol)</h3>
      ${svgPops(d.conformer_populations)}`;
  }

  html += '<div class="grid-2" style="margin-top:16px">';
  for (const [title, keys] of KV_GROUPS) {
    let rows = "";
    for (const k of keys) {
      if (d[k] == null) continue;
      const [label, unit] = DESC_LABELS[k] || [k, ""];
      const suffix = k.includes("potential") && ref ? ` vs ${ref}` : "";
      rows += `<tr><th>${esc(label)}</th><td>${d[k]} ${unit}${suffix}</td></tr>`;
    }
    if (rows) html += `<div><h3 style="font-size:13px;color:var(--accent)">${title}</h3>
      <table class="kv-table">${rows}</table></div>`;
  }
  html += "</div>";

  let condRows = "";
  for (const [k, v] of Object.entries(r.conditions)) {
    condRows += `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`;
  }
  html += `
    <details style="margin-top:14px"><summary class="small muted">계산 조건 전체</summary>
      <table class="kv-table" style="margin-top:6px">${condRows}</table></details>
    <h3 style="font-size:13px;color:var(--accent);margin-top:14px">주의사항</h3>
    <ul class="log-list">${r.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul>
    <details style="margin-top:8px"><summary class="small muted">XYZ 좌표 보기</summary>
      <pre class="xyz">${esc(r.structure_xyz)}</pre></details>`;

  $("result-body").innerHTML = html;
  $("v3d-element").addEventListener("click", () => { VIEW_MODE = "element"; render3D(CURRENT_RESULT); });
  $("v3d-charge").addEventListener("click", () => { VIEW_MODE = "charge"; render3D(CURRENT_RESULT); });
  $("result-card").style.display = "";
  render3D(r);
  $("result-card").scrollIntoView({behavior: "smooth"});
}

/* ---------- 3D 뷰어 (자체 캔버스, 원소/부분전하 색상) ---------- */
function chargeColor(q, qmax) {
  const t = Math.max(-1, Math.min(1, q / (qmax || 1)));
  // 파랑(−) ↔ 흰색(0) ↔ 빨강(+)
  const r = t > 0 ? 214 : Math.round(255 - (-t) * 180);
  const g = Math.round(235 - Math.abs(t) * 190);
  const b = t < 0 ? 216 : Math.round(255 - t * 190);
  return `rgb(${t > 0 ? 214 : r},${g},${t < 0 ? 216 : b})`;
}

function render3D(r) {
  const box = $("viewer3d");
  const note = $("viewer3d-note");
  if (!box) return;
  const atoms = [];
  const lines = r.structure_xyz.trim().split("\n");
  for (let i = 2; i < lines.length; i++) {
    const t = lines[i].trim().split(/\s+/);
    if (t.length >= 4) atoms.push({el: t[0], x: +t[1], y: +t[2], z: +t[3]});
  }
  if (!atoms.length) { box.style.display = "none"; return; }
  const charges = r.mulliken_charges || [];
  const qmax = Math.max(...charges.map(Math.abs), 0.01);

  const solventIdx = new Set();
  if (r.fragments && r.fragments.length > 1) {
    for (const f of r.fragments.slice(1)) {
      for (let i = f.start; i < f.end; i++) solventIdx.add(i);
    }
  }
  const baseNote = solventIdx.size
    ? "선명한 분자 = 용질 · 흐린 분자 = 명시적 주변 분자 · 드래그 회전 / 휠 확대"
    : "드래그로 회전, 휠로 확대할 수 있습니다.";
  note.textContent = VIEW_MODE === "charge"
    ? "부분 전하(Mulliken): 파랑 = 음전하(친핵 부위) · 빨강 = 양전하(친전자 부위) — " + baseNote
    : baseNote;
  $("v3d-element")?.classList.toggle("primary", VIEW_MODE === "element");
  $("v3d-charge")?.classList.toggle("primary", VIEW_MODE === "charge");

  const COLOR = {H:"#cfcfcf",C:"#3a3a3a",N:"#2f5bd8",O:"#d62828",F:"#4fb944",
                 S:"#c9a227",P:"#e08020",Cl:"#3fae49",Br:"#8a4b26",I:"#7a3fa0",Li:"#b04fd8"};
  const RCOV = {H:.31,C:.76,N:.71,O:.66,F:.57,S:1.05,P:1.07,Cl:1.02,Br:1.2,I:1.39,Li:1.28};
  const rad = el => RCOV[el] ?? .8;

  const bonds = [];
  for (let i = 0; i < atoms.length; i++) {
    for (let j = i + 1; j < atoms.length; j++) {
      const a = atoms[i], b = atoms[j];
      const dd = Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
      if (dd < (rad(a.el) + rad(b.el)) * 1.25 && dd > 0.4) bonds.push([i, j]);
    }
  }
  const cx = atoms.reduce((s, a) => s + a.x, 0) / atoms.length;
  const cy = atoms.reduce((s, a) => s + a.y, 0) / atoms.length;
  const cz = atoms.reduce((s, a) => s + a.z, 0) / atoms.length;
  const span = Math.max(...atoms.map(a => Math.hypot(a.x - cx, a.y - cy, a.z - cz)), 1.5);

  box.innerHTML = "";
  const canvas = document.createElement("canvas");
  canvas.style.width = "100%";
  canvas.style.height = "100%";
  canvas.style.cursor = "grab";
  box.appendChild(canvas);
  const ctx = canvas.getContext("2d");
  let yaw = 0.6, pitch = -0.4, zoom = 1;

  function draw() {
    const dpr = window.devicePixelRatio || 1;
    const W = box.clientWidth, H = box.clientHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const scale = Math.min(W, H) / (span * 2.6) * zoom;
    const cyaw = Math.cos(yaw), syaw = Math.sin(yaw);
    const cp = Math.cos(pitch), sp = Math.sin(pitch);
    const proj = atoms.map((a, i) => {
      const x0 = a.x - cx, y0 = a.y - cy, z0 = a.z - cz;
      const x1 = x0 * cyaw + z0 * syaw, z1 = -x0 * syaw + z0 * cyaw;
      const y2 = y0 * cp - z1 * sp, z2 = y0 * sp + z1 * cp;
      return {i, el: a.el, sx: W / 2 + x1 * scale, sy: H / 2 - y2 * scale, z: z2};
    });
    for (const [i, j] of bonds) {
      const p = proj[i], q = proj[j];
      const faded = solventIdx.has(i) || solventIdx.has(j);
      ctx.strokeStyle = faded ? "rgba(140,140,140,.45)" : "rgba(90,90,90,.9)";
      ctx.lineWidth = faded ? 1.4 : 2.6;
      ctx.beginPath(); ctx.moveTo(p.sx, p.sy); ctx.lineTo(q.sx, q.sy); ctx.stroke();
    }
    proj.sort((a, b) => a.z - b.z);
    for (const p of proj) {
      const faded = solventIdx.has(p.i);
      const rr = (rad(p.el) * 0.45 + 0.18) * scale * (faded ? 0.7 : 1);
      ctx.globalAlpha = faded ? 0.45 : 1;
      ctx.beginPath();
      ctx.arc(p.sx, p.sy, Math.max(rr, 2), 0, Math.PI * 2);
      ctx.fillStyle = VIEW_MODE === "charge" && charges[p.i] !== undefined
        ? chargeColor(charges[p.i], qmax)
        : (COLOR[p.el] ?? "#888");
      ctx.fill();
      ctx.strokeStyle = VIEW_MODE === "charge" ? "rgba(60,60,60,.5)" : "rgba(255,255,255,.6)";
      ctx.lineWidth = 1;
      ctx.stroke();
      if (VIEW_MODE === "charge" && charges[p.i] !== undefined && !faded && p.el !== "H") {
        ctx.fillStyle = "#333";
        ctx.font = "10px ui-monospace,monospace";
        ctx.textAlign = "center";
        ctx.fillText(charges[p.i].toFixed(2), p.sx, p.sy - rr - 3);
      }
      ctx.globalAlpha = 1;
    }
  }

  let dragging = false, px = 0, py = 0;
  canvas.addEventListener("mousedown", e => { dragging = true; px = e.clientX; py = e.clientY; });
  window.addEventListener("mouseup", () => { dragging = false; });
  window.addEventListener("mousemove", e => {
    if (!dragging) return;
    yaw += (e.clientX - px) * 0.01;
    pitch += (e.clientY - py) * 0.01;
    pitch = Math.max(-1.5, Math.min(1.5, pitch));
    px = e.clientX; py = e.clientY;
    draw();
  });
  canvas.addEventListener("wheel", e => {
    e.preventDefault();
    zoom = Math.max(0.3, Math.min(5, zoom * (e.deltaY < 0 ? 1.1 : 0.9)));
    draw();
  }, {passive: false});
  draw();
}

init();


/* ================= 화학물질 조회 ================= */
let LAST_LOOKUP = null;

const LOOKUP_LABELS = {
  formula: "분자식", mw: "분자량 (g/mol)", canonical_smiles: "SMILES (정규화)",
  logp_crippen: "LogP (Crippen, 소수성)", xlogp: "XLogP (PubChem)",
  tpsa: "TPSA (극성 표면적, Å²)", hbd: "수소결합 주개 (HBD)", hba: "수소결합 받개 (HBA)",
  rotatable_bonds: "회전 가능 결합", rings: "고리 수", heavy_atoms: "무거운 원자 수",
  formal_charge: "형식 전하", charge: "전하", iupac_name: "IUPAC 이름", cas: "CAS 번호",
  cid: "PubChem CID",
};

async function doLookup() {
  const q = $("lookup-q").value.trim();
  $("lookup-error").textContent = "";
  if (!q) return;
  $("lookup-result").innerHTML = '<p class="muted small">조회 중…</p>';
  let r;
  try {
    const res = await fetch("/api/lookup", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({query: q}),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    r = await res.json();
  } catch (e) {
    $("lookup-result").innerHTML = "";
    $("lookup-error").textContent = "조회 실패: " + e.message;
    return;
  }
  LAST_LOOKUP = r;
  renderLookup(r);
}

function kvRows(obj, keys) {
  let rows = "";
  for (const k of keys) {
    const v = obj?.[k];
    if (v === null || v === undefined || v === "") continue;
    rows += `<tr><th>${esc(LOOKUP_LABELS[k] || k)}</th><td>${esc(v)}</td></tr>`;
  }
  return rows;
}

function renderLookup(r) {
  const smiles = r.pubchem?.smiles || r.local?.canonical_smiles;
  const name = r.pubchem?.title || r.pubchem?.iupac_name || r.query;
  let html = "";
  if (smiles) {
    html += `<h3 style="font-size:14px;color:var(--accent);margin:6px 0">${esc(name)}</h3>`;
    html += `<div class="toolbar" style="margin-bottom:10px">
      <button class="btn primary" id="lk-add">물질 보관함에 추가</button>
      <button class="btn" id="lk-calc">DFT 계산으로 보내기</button>
      ${r.pubchem?.url ? `<a class="btn" href="${esc(r.pubchem.url)}" target="_blank" rel="noopener">PubChem에서 열기</a>` : ""}
    </div>`;
  }
  if (r.local) {
    html += `<h3 style="font-size:13px;color:var(--accent)">구조 기반 특성 (RDKit 로컬 계산)</h3>
      <table class="kv-table">${kvRows(r.local,
        ["formula","mw","canonical_smiles","logp_crippen","tpsa","hbd","hba",
         "rotatable_bonds","rings","heavy_atoms","formal_charge"])}</table>`;
  }
  if (r.pubchem) {
    html += `<h3 style="font-size:13px;color:var(--accent);margin-top:14px">PubChem 등록 정보</h3>
      <table class="kv-table">${kvRows(r.pubchem, ["iupac_name","cas","cid","xlogp","charge"])}</table>`;
    if (r.pubchem.description) {
      html += `<p class="small" style="max-width:76ch;color:var(--text-2)">${esc(r.pubchem.description)}</p>`;
    }
    if (r.pubchem.synonyms?.length) {
      html += `<p class="muted small">동의어: ${r.pubchem.synonyms.slice(0, 6).map(esc).join(" · ")}</p>`;
    }
  }
  if (r.mp) {
    html += `<h3 style="font-size:13px;color:var(--accent);margin-top:14px">Materials Project (분자)</h3>
      <pre class="xyz">${esc(JSON.stringify(r.mp, null, 1))}</pre>`;
  }
  if (r.notes?.length) {
    html += `<ul class="log-list">${r.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul>`;
  }
  $("lookup-result").innerHTML = html || '<p class="muted small">결과가 없습니다.</p>';
  if (smiles) {
    $("lk-add")?.addEventListener("click", () => {
      addToLibrary(name, smiles, r.local);
      $("lk-add").textContent = "보관함에 추가됨 ✓";
    });
    $("lk-calc")?.addEventListener("click", () => {
      const key = addToLibrary(name, smiles, r.local);
      if (window.rbOpenCalc) window.rbOpenCalc();
      setTimeout(() => {
        const it = [...document.querySelectorAll("#material-grid .mol-card")]
          .find(c => c.textContent.includes(name));
        if (it && !it.classList.contains("selected")) it.click();
      }, 200);
    });
  }
}

function addToLibrary(name, smiles, local) {
  const ts = Date.now();
  const mat = {
    id: "mat-lookup-" + ts, name, smiles,
    formula: local?.formula || "", mw: local?.mw || null,
    type: "조회 등록", originType: "사용자", tags: [], note: "화학물질 조회에서 추가",
    precursorCas: [], structureVersion: 1, readyState: "Ready",
    createdAt: ts, updatedAt: ts, builtin: false,
  };
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (!k.startsWith("dft-workbench")) continue;
    try {
      const v = JSON.parse(localStorage.getItem(k));
      if (v && Array.isArray(v.materials)) {
        if (!v.materials.some(m => m.smiles === smiles)) {
          v.materials.push(mat);
          localStorage.setItem(k, JSON.stringify(v));
          sessionStorage.setItem("rb-lib-dirty", "1");
        }
        return mat.id;
      }
    } catch (e) { /* 다음 키 시도 */ }
  }
  return mat.id;
}

/* ================= 전기화학 안정성 (ESW) ================= */
// 배터리 활물질 작동 전위 (V vs Li/Li+, 대표값)
const ELECTRODES = [
  {label: "Graphite", v: 0.1, side: "anode"},
  {label: "Si", v: 0.4, side: "anode"},
  {label: "LFP", v: 3.45, side: "cathode"},
  {label: "NCM811 (4.3 V 충전)", v: 4.3, side: "cathode"},
];

function eswJobs() {
  return JOBS_CACHE.filter(j => j.status === "PUBLISHED"
    && j.result?.descriptors?.oxidation_potential_v != null
    && j.result?.descriptors?.reduction_potential_v != null);
}

window.rbRenderEsw = function () {
  const jobs = eswJobs();
  const box = $("esw-body");
  if (!jobs.length) {
    box.innerHTML = '<div class="empty small">전위가 포함된 PUBLISHED 결과가 없습니다.<br>' +
      'DFT 계산에서 목적을 "전자구조 + 산화/환원 전위"로 선택해 제출하세요.</div>';
    return;
  }
  const V0 = -0.5, V1 = 5.5, W = 820, H = 46 * jobs.length + 70, L = 170;
  const x = v => L + (Math.max(V0, Math.min(V1, v)) - V0) / (V1 - V0) * (W - L - 16);
  let svg = `<svg class="esw-chart" viewBox="0 0 ${W} ${H}" role="img">`;
  for (let v = 0; v <= 5; v++) {
    svg += `<line x1="${x(v)}" y1="26" x2="${x(v)}" y2="${H - 34}" stroke="var(--grid)" />
      <text x="${x(v)}" y="${H - 20}" font-size="11" text-anchor="middle" fill="var(--muted)">${v}</text>`;
  }
  svg += `<text x="${(L + W) / 2}" y="${H - 4}" font-size="11" text-anchor="middle" fill="var(--muted)">전위 (V vs Li/Li⁺)</text>`;
  for (const el of ELECTRODES) {
    svg += `<line x1="${x(el.v)}" y1="18" x2="${x(el.v)}" y2="${H - 34}"
        stroke="var(--pin)" stroke-dasharray="4 3" />
      <text x="${x(el.v)}" y="12" font-size="10.5" text-anchor="middle" fill="var(--pin)">${esc(el.label)}</text>`;
  }
  jobs.forEach((j, i) => {
    const d = j.result.descriptors;
    const red = d.reduction_potential_gibbs_v ?? d.reduction_potential_v;
    const ox = d.oxidation_potential_gibbs_v ?? d.oxidation_potential_v;
    const y = 40 + i * 46;
    svg += `<text x="${L - 8}" y="${y + 5}" font-size="12" text-anchor="end" fill="var(--text-1)">${esc(j.material.name.split(" (")[0])}</text>
      <rect x="${x(red)}" y="${y - 8}" width="${Math.max(2, x(ox) - x(red))}" height="16" rx="4"
        fill="color-mix(in srgb, var(--accent) 30%, transparent)" stroke="var(--accent)" />
      <text x="${x(red) - 4}" y="${y + 4}" font-size="10" text-anchor="end" fill="var(--text-2)">${red.toFixed(2)}</text>
      <text x="${x(ox) + 4}" y="${y + 4}" font-size="10" fill="var(--text-2)">${ox.toFixed(2)}</text>`;
  });
  svg += "</svg>";

  let rows = "";
  for (const j of jobs) {
    const d = j.result.descriptors;
    const red = d.reduction_potential_gibbs_v ?? d.reduction_potential_v;
    const ox = d.oxidation_potential_gibbs_v ?? d.oxidation_potential_v;
    const anodeOK = red < 0.1, anodeMid = red < 0.8;
    const ncmOK = ox > 4.3, lfpOK = ox > 3.45;
    rows += `<tr><td><b>${esc(j.material.name)}</b><br><span class="mono small muted">${esc(j.id)}</span></td>
      <td>${red.toFixed(2)} ~ ${ox.toFixed(2)} V</td>
      <td class="${anodeOK ? "verdict-ok" : anodeMid ? "verdict-mid" : "verdict-no"}">${anodeOK ? "안정" : anodeMid ? "경계" : "환원 분해 우려"}</td>
      <td class="${lfpOK ? "verdict-ok" : "verdict-no"}">${lfpOK ? "안정" : "산화 우려"}</td>
      <td class="${ncmOK ? "verdict-ok" : "verdict-no"}">${ncmOK ? "안정" : "산화 우려"}</td></tr>`;
  }
  box.innerHTML = svg + `
    <div class="scroll-x" style="margin-top:14px"><table class="kv-table" style="min-width:640px">
      <tr><th>물질</th><th>ESW (환원~산화)</th><th>음극 Graphite (0.1 V)</th><th>양극 LFP (3.45 V)</th><th>양극 NCM811 (4.3 V)</th></tr>
      ${rows}</table></div>
    <ul class="log-list" style="margin-top:10px">
      <li>판정 기준: 환원 전위 &lt; 음극 전위 → 음극에서 환원 안정, 산화 전위 &gt; 양극 전위 → 양극에서 산화 안정 (열역학적 기준)</li>
      <li>ΔG 기반 전위가 있으면 우선 사용, 없으면 단열/수직 전위 사용</li>
      <li>주의: 실제 전지에서는 SEI/CEI 피막의 동역학적 보호가 크게 작용합니다 — 예: EC는 환원 분해되지만 안정적 SEI를 형성해 사용됩니다. 이 판정은 스크리닝용 열역학 지표입니다.</li>
    </ul>`;
};

/* ================= 물질 비교 ================= */
const COMPARE_SEL = new Set();

window.rbRenderCompare = function () {
  const jobs = JOBS_CACHE.filter(j => j.status === "PUBLISHED" && j.result);
  const box = $("compare-body");
  if (!jobs.length) {
    box.innerHTML = '<div class="empty small">PUBLISHED 결과가 없습니다.</div>';
    return;
  }
  for (const id of [...COMPARE_SEL]) if (!jobs.some(j => j.id === id)) COMPARE_SEL.delete(id);
  let picker = '<div class="mol-grid" style="margin-bottom:14px">';
  for (const j of jobs) {
    picker += `<button class="mol-card ${COMPARE_SEL.has(j.id) ? "selected" : ""}" data-cmp="${esc(j.id)}">
      <b>${esc(j.material.name)}</b>
      <span class="small muted">${esc(j.result.conditions.method)} · ${esc(j.result.conditions.solvent_model)}</span>
      <span class="mono small muted">${esc(j.id)}</span></button>`;
  }
  picker += "</div>";

  const chosen = jobs.filter(j => COMPARE_SEL.has(j.id));
  let table = "";
  if (chosen.length >= 2) {
    // 모의 앱 스타일 비교 차트 (시리즈 색상)
    const METRICS = [
      ["homo_ev", "HOMO", "eV"], ["lumo_ev", "LUMO", "eV"], ["gap_ev", "HOMO–LUMO 갭", "eV"],
      ["dipole_debye", "쌍극자 모멘트", "D"],
      ["oxidation_potential_v", "산화 전위", "V"], ["reduction_potential_v", "환원 전위", "V"],
      ["solvation_energy_kcal", "용매화 에너지", "kcal/mol"],
      ["interaction_energy_kcal", "클러스터 상호작용", "kcal/mol"],
    ];
    let charts = "";
    for (const [key, title, unit] of METRICS) {
      const entries = chosen
        .map((j, i) => ({name: j.material.name.split(" (")[0], v: j.result.descriptors[key], i}))
        .filter(e => e.v != null);
      if (entries.length < 2) continue;
      const maxAbs = Math.max(...entries.map(e => Math.abs(e.v)), 1e-9);
      const W = 340, rowH = 24, H = entries.length * rowH + 6;
      let sv = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:360px" role="img">`;
      entries.forEach((e, k) => {
        const y = k * rowH + 4, w = Math.max(2, Math.abs(e.v) / maxAbs * (W - 190));
        sv += `<text x="0" y="${y + 12}" class="axis-label">${esc(e.name.slice(0, 12))}</text>
          <rect x="96" y="${y}" width="${w}" height="15" rx="3" fill="var(--series-${(e.i % 8) + 1})"/>
          <text x="${102 + w}" y="${y + 12}" class="value-label">${e.v}</text>`;
      });
      sv += "</svg>";
      charts += `<div><h3 style="font-size:12.5px;color:var(--accent);margin:0 0 4px">
        ${esc(title)}${unit ? ` (${unit})` : ""}</h3>${sv}</div>`;
    }
    if (charts) {
      table += `<div class="grid-2" style="margin-bottom:14px">${charts}</div>`;
    }
    const keys = [];
    for (const j of chosen) {
      for (const k of Object.keys(j.result.descriptors)) {
        if (k !== "potential_reference" && !keys.includes(k)) keys.push(k);
      }
    }
    table += '<div class="scroll-x"><table class="kv-table" style="min-width:560px"><tr><th>지표</th>' +
      chosen.map(j => `<th>${esc(j.material.name.split(" (")[0])}</th>`).join("") + "</tr>";
    for (const k of keys) {
      const [label, unit] = DESC_LABELS[k] || [k, ""];
      table += `<tr><th>${esc(label)}${unit ? ` (${unit})` : ""}</th>` +
        chosen.map(j => `<td>${j.result.descriptors[k] ?? "—"}</td>`).join("") + "</tr>";
    }
    table += "</table></div>" + `
      <ul class="log-list" style="margin-top:10px">
        <li>바인더 후보: HOMO가 낮고(산화 저항) 갭이 크며 산화 전위가 양극 전위보다 높을수록 유리</li>
        <li>전해액 첨가제/용매 후보: 목적에 따라 다름 — SEI 형성 첨가제는 오히려 환원 전위가 약간 높은(먼저 분해되는) 물질을 선택</li>
        <li>용매화 에너지가 클수록(더 음수) 극성 환경 친화적 — 수계/유기계 공정 적합성 참고</li>
      </ul>`;
  } else {
    table = '<p class="muted small">두 개 이상 선택하면 비교 표가 나타납니다.</p>';
  }
  box.innerHTML = picker + table;
  box.querySelectorAll("[data-cmp]").forEach(b => b.addEventListener("click", () => {
    const id = b.dataset.cmp;
    COMPARE_SEL.has(id) ? COMPARE_SEL.delete(id) : COMPARE_SEL.add(id);
    window.rbRenderCompare();
  }));
};
