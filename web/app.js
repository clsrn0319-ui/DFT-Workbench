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

/* ---------- 접속 (공유 비밀번호) ---------- */
let LIMITS = null;

async function boot() {
  try {
    const res = await fetch("/api/me");
    if (res.ok) {
      LIMITS = (await res.json()).limits;
      await startApp();
      return;
    }
  } catch (e) { /* 서버 미가동 — 접속 화면 유지 */ }
  showLogin();
}

function showLogin() {
  $("rb-login").style.display = "flex";
  $("rb-userbar").style.display = "none";
  const submit = async () => {
    $("login-err").textContent = "";
    const password = $("login-pass").value;
    if (!password) { $("login-err").textContent = "접속 비밀번호를 입력하세요."; return; }
    $("login-btn").disabled = true;
    try {
      const res = await fetch("/api/login", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({password}),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "접속에 실패했습니다.");
      }
      const meRes = await fetch("/api/me");
      if (meRes.ok) LIMITS = (await meRes.json()).limits;
      await startApp();
    } catch (e) {
      $("login-err").textContent = e.message;
    } finally {
      $("login-btn").disabled = false;
    }
  };
  $("login-btn").onclick = submit;
  $("login-pass").onkeydown = e => { if (e.key === "Enter") submit(); };
  $("login-pass").focus();
}

async function startApp() {
  $("rb-login").style.display = "none";
  $("rb-userbar").style.display = "flex";
  $("rb-whoami").textContent = "접속됨";
  $("rb-logout").onclick = async () => {
    await fetch("/api/logout", {method: "POST"});
    location.reload();
  };
  dismissIntroOverlay();
  await init();
}

/* 접속을 마쳤으므로 앱의 인트로(ENTER) 화면은 자동으로 넘긴다 */
function dismissIntroOverlay() {
  let tries = 0;
  const timer = setInterval(() => {
    const btn = document.querySelector("#lp button");
    if (btn) { btn.click(); clearInterval(timer); }
    if (++tries > 40) clearInterval(timer);
  }, 150);
}

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
  for (const f of PRESETS.functionals) $("cmp-functionals").add(new Option(f, f));

  $("accuracy").onchange = syncAccuracyDesc;
  syncAccuracyDesc();
  syncEnvState();
  $("add-explicit").onclick = () => addExplicitRow();
  $("submit-btn").onclick = submit;
  $("lookup-btn").onclick = doLookup;
  wireResultsControls();
  wireBinderControls();
  wirePolymerCard();
  wireChainControls();
  wireMechControls();
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
  const cmpF = [...$("cmp-functionals").selectedOptions].map(o => o.value);
  const body = {
    compareFunctionals: cmpF,
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
        optimizeInSolvent: $("opt-solvent").value === "true",
        bdeRelaxFragments: $("bde-relax").value === "" ? null : $("bde-relax").value === "true",
        bdeThermalCorrection: $("bde-thermal").value === "" ? null : $("bde-thermal").value === "true",
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
  const res = await fetch("/api/jobs");
  if (res.status === 401) { location.reload(); return; }  // 세션 만료 → 로그인 화면
  const {jobs} = await res.json();
  JOBS_CACHE = jobs;
  const real = document.getElementById("rb-real");
  if (real?.classList.contains("mode-results") && window.rbRenderResults) window.rbRenderResults();
  else renderJobList();
  if (real?.classList.contains("mode-compare") && window.rbRenderCompare) window.rbRenderCompare();
}

function jobsSignature() {
  return JOBS_CACHE.map(j => `${j.id}:${j.status}:${j.progress}:${j.logs.length}`).join("|")
    + "#" + [...EXPORT_SEL].sort().join(",");
}

function renderJobList(force = false) {
  const list = $("job-list");
  if (!list) return;
  const sig = jobsSignature();
  if (!force && sig === JOB_LIST_SIG && list.children.length) return;  // 변화 없음 → 유지
  JOB_LIST_SIG = sig;
  if (!JOBS_CACHE.length) {
    list.className = "empty small";
    list.textContent = "작업이 없습니다.";
    updateSelCount();
    return;
  }
  list.className = "";
  // 소재별로 묶어서 표시 — 나중에 데이터를 찾기 쉽도록
  const groups = new Map();
  for (const job of JOBS_CACHE) {
    if (!groups.has(job.material.name)) groups.set(job.material.name, []);
    groups.get(job.material.name).push(job);
  }
  for (const id of [...EXPORT_SEL]) if (!JOBS_CACHE.some(j => j.id === id)) EXPORT_SEL.delete(id);

  list.innerHTML = [...groups.entries()].map(([name, jobs]) => {
    const done = jobs.filter(j => j.status === "PUBLISHED").length;
    const active = jobs.filter(j => ["QUEUED", "RUNNING"].includes(j.status)).length;
    const failed = jobs.filter(j => j.status === "FAILED").length;
    const open = OPEN_GROUPS.has(name) || (active && !OPEN_GROUPS.size);
    return `<details class="job-group" data-group="${esc(name)}" ${open ? "open" : ""}
        style="border:1px solid var(--grid);border-radius:10px;padding:8px 12px;margin-bottom:8px">
      <summary style="cursor:pointer;font-weight:700">${esc(name)}
        <span class="muted small" style="font-weight:400">— 총 ${jobs.length}건${done ? ` · 완료 ${done}` : ""}${active ? ` · 진행 ${active}` : ""}${failed ? ` · 실패 ${failed}` : ""}</span>
      </summary>
      <div style="margin-top:8px">${jobs.map(jobRowHtml).join("")}</div>
    </details>`;
  }).join("");

  list.querySelectorAll("details.job-group").forEach(d => d.addEventListener("toggle", () => {
    d.open ? OPEN_GROUPS.add(d.dataset.group) : OPEN_GROUPS.delete(d.dataset.group);
    JOB_LIST_SIG = jobsSignature();   // 펼침 변화는 재렌더 대상이 아님
  }));
  list.querySelectorAll("[data-export-sel]").forEach(cb => cb.addEventListener("change", () => {
    cb.checked ? EXPORT_SEL.add(cb.dataset.exportSel) : EXPORT_SEL.delete(cb.dataset.exportSel);
    JOB_LIST_SIG = jobsSignature();
    updateSelCount();
  }));
  list.querySelectorAll("[data-view-job]").forEach(b => b.addEventListener("click", () => {
    const job = JOBS_CACHE.find(x => x.id === b.dataset.viewJob);
    if (job) { SELECTED_RESULT = job.id; showResult(job); }
  }));
  list.querySelectorAll("[data-retry]").forEach(b => b.addEventListener("click", () =>
    fetch(`/api/jobs/${b.dataset.retry}/retry`, {method: "POST"}).then(refreshJobs)));
  list.querySelectorAll("[data-cancel]").forEach(b => b.addEventListener("click", () =>
    fetch(`/api/jobs/${b.dataset.cancel}/cancel`, {method: "POST"}).then(refreshJobs)));
  list.querySelectorAll("[data-del]").forEach(b => b.addEventListener("click", () =>
    fetch(`/api/jobs/${b.dataset.del}`, {method: "DELETE"}).then(refreshJobs)));
  updateSelCount();
}

function jobRowHtml(job) {
  const solvent = PRESETS.solvents.find(s => s.id === job.settings.solventId);
  const method = job.result?.conditions?.method
    || `${job.settings.expert.functional}${job.settings.expert.basis ? "/" + job.settings.expert.basis : ""}`;
  const done = job.status === "PUBLISHED";
  return `<div class="job-row">
    <div class="job-main">
      <div>
        ${done ? `<label class="compare-check"><input type="checkbox" data-export-sel="${esc(job.id)}"
            ${EXPORT_SEL.has(job.id) ? "checked" : ""}> 내보내기</label> ` : ""}
        <span class="mono small muted">${esc(job.id)}</span>
      </div>
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
      ${done ? `<button class="btn ghost" data-view-job="${esc(job.id)}">결과 보기</button>` : ""}
      ${job.status === "FAILED" ? `<button class="btn ghost" data-retry="${esc(job.id)}">재시도</button>` : ""}
      ${["QUEUED", "RUNNING"].includes(job.status)
        ? `<button class="btn ghost danger" data-cancel="${esc(job.id)}">취소</button>`
        : `<button class="btn ghost danger" data-del="${esc(job.id)}">삭제</button>`}
    </div></div>`;
}

function updateSelCount() {
  const el = $("sel-count");
  if (el) el.textContent = EXPORT_SEL.size
    ? `${EXPORT_SEL.size}건 선택됨` : "선택 없음 → 전체 내보내기";
}

function wireResultsControls() {
  const on = (id, fn) => { const el = $(id); if (el) el.onclick = fn; };
  on("sel-all", () => { publishedJobs().forEach(j => EXPORT_SEL.add(j.id)); renderJobList(true); });
  on("sel-none", () => { EXPORT_SEL.clear(); renderJobList(true); });
  const dl = format => {
    const ids = [...EXPORT_SEL].join(",");
    window.location = `/api/export?format=${format}` + (ids ? `&ids=${encodeURIComponent(ids)}` : "");
  };
  on("export-csv", () => dl("csv"));
  on("export-json", () => dl("json"));
  on("export-html", () => dl("html"));
  on("result-close", () => { $("result-card").style.display = "none"; SELECTED_RESULT = null; });
  const slider = $("cmp-opacity");
  if (slider) slider.oninput = () => {
    CMP_OPACITY = parseFloat(slider.value);
    const lbl = $("cmp-opacity-val");
    if (lbl) lbl.textContent = CMP_OPACITY.toFixed(2);
    if (window.rbRenderCompare) window.rbRenderCompare();
  };
  const ctype = $("cmp-chart-type");
  if (ctype) {
    ctype.value = CMP_CHART;
    ctype.onchange = () => {
      CMP_CHART = ctype.value;
      localStorage.setItem(CMP_CHART_KEY, CMP_CHART);
      if (window.rbRenderCompare) window.rbRenderCompare();
    };
  }
  const tbars = $("cmp-table-bars");
  if (tbars) {
    tbars.checked = CMP_TABLE_BARS;
    tbars.onchange = () => {
      CMP_TABLE_BARS = tbars.checked;
      localStorage.setItem(CMP_TBAR_KEY, CMP_TABLE_BARS ? "1" : "0");
      if (window.rbRenderCompare) window.rbRenderCompare();
    };
  }
  for (const id of ["res-filter-mat", "res-filter-cond"]) {
    const el = $(id);
    if (el) el.onchange = () => window.rbRenderResults();
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
  mep_max_kcal: ["MEP 최대 양전위", "kcal/mol"],
  mep_min_kcal: ["MEP 최소 음전위", "kcal/mol"],
  chemical_hardness_ev: ["화학적 경도 η", "eV"],
  chemical_potential_ev: ["화학적 퍼텐셜 μ", "eV"],
  electrophilicity_ev: ["친전자성 지수 ω", "eV"],
  softness_inv_ev: ["화학적 연성 S", "1/eV"],
  li_binding_kj: ["Li⁺ 결합 에너지", "kJ/mol"],
  dimer_binding_kj: ["이량체 결합 에너지 (바인더–바인더)", "kJ/mol"],
  bde_min_kj: ["최약 결합 BDE (0 K 전자에너지)", "kJ/mol"],
  bde_min_298_kj: ["최약 결합 BDE (298 K, 문헌 비교용)", "kJ/mol"],
  uvvis_lambda_max_nm: ["UV-Vis 최대 흡수 λmax", "nm"],
  uvvis_osc_strength: ["진동자 세기 f", ""],
  uvvis_excitation_ev: ["수직 여기 에너지", "eV"],
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
  const [V0, V1, STEP] = niceRange(
    [red, ox, ...ELECTRODES.map(e => e.v), 0], 0.6);
  const W = 640, H = 118, L = 34;
  const x = v => L + (v - V0) / (V1 - V0) * (W - L - 34);
  let sv = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:680px" role="img">`;
  for (let v = V0; v <= V1 + 1e-9; v += STEP) {
    sv += `<line x1="${x(v)}" y1="34" x2="${x(v)}" y2="${H - 32}" class="gridline"/>
      <text x="${x(v)}" y="${H - 20}" text-anchor="middle" class="axis-label">${v}</text>`;
  }
  ELECTRODES.forEach((el, i) => {
    const ly = i % 2 ? 26 : 12;  // 가까운 전극 라벨은 2단으로 엇갈리게
    sv += `<line x1="${x(el.v)}" y1="${ly + 4}" x2="${x(el.v)}" y2="${H - 32}"
        stroke="var(--pin)" stroke-dasharray="4 3"/>
      <text x="${x(el.v)}" y="${ly}" text-anchor="middle" class="axis-label"
        fill="var(--pin)">${esc(el.label.split(" (")[0])}</text>`;
  });
  sv += `<rect x="${x(red)}" y="52" width="${Math.max(2, x(ox) - x(red))}" height="18" rx="4"
      fill="color-mix(in srgb, var(--accent) 30%, transparent)" stroke="var(--accent)"/>
    <text x="${x(red) - 4}" y="65" text-anchor="end" class="value-label">${red.toFixed(2)}</text>
    <text x="${x(ox) + 4}" y="65" class="value-label">${ox.toFixed(2)}</text>
    <text x="${W / 2}" y="${H - 5}" text-anchor="middle"
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

/* ---------- 차트 공통: 데이터에 맞춘 눈금 범위 ---------- */
function niceRange(values, pad = 0.5) {
  const lo = Math.min(...values) - pad, hi = Math.max(...values) + pad;
  const span = hi - lo;
  const step = span > 12 ? 4 : span > 7 ? 2 : 1;
  return [Math.floor(lo / step) * step, Math.ceil(hi / step) * step, step];
}

/* ---------- 물성 지문 레이더 ---------- */
const FP_PRESET = [
  {key: "gap_ev", label: "HOMO-LUMO gap", unit: "eV", lower: false},
  {key: "dipole_debye", label: "쌍극자 모멘트", unit: "D", lower: false},
  {key: "oxidation_potential_v", label: "산화 전위", unit: "V", lower: false},
  {key: "lumo_ev", label: "LUMO 에너지", unit: "eV", lower: false},
  {key: "homo_ev", label: "HOMO 에너지", unit: "eV", lower: true},
  {key: "li_binding_kj", label: "Li⁺ 결합 에너지", unit: "kJ/mol", lower: true},
];
// ↓낮을수록 유리한 지표 (레이더에서 바깥쪽 방향을 뒤집음)
const LOWER_IS_BETTER = new Set(["homo_ev", "li_binding_kj", "solvation_energy_kcal",
  "interaction_energy_kcal", "dimer_binding_kj", "reduction_potential_v",
  "reduction_potential_gibbs_v", "mep_min_kcal"]);

function numericDescriptorKeys() {
  const keys = new Set();
  for (const j of JOBS_CACHE) {
    if (j.status !== "PUBLISHED") continue;
    for (const [k, v] of Object.entries(j.result?.descriptors || {})) {
      if (typeof v === "number") keys.add(k);
    }
  }
  return [...keys];
}

function axisMeta(key) {
  const [label, unit] = DESC_LABELS[key] || [key, ""];
  return {key, label, unit, lower: LOWER_IS_BETTER.has(key)};
}

/* ---------- 숫자 표기: 소수 넷째 자리까지 ---------- */
function fmt(v) {
  if (typeof v !== "number" || !isFinite(v)) return v;
  if (Number.isInteger(v)) return String(v);
  return v.toFixed(4);
}

/* ---------- ★ 고정 물성 (사용자 지정, 레이더 축과 연동) ---------- */
const PIN_KEY = "rhobench-pinned-descriptors";
let PINNED = (() => {
  try {
    const saved = JSON.parse(localStorage.getItem(PIN_KEY) || "null");
    if (Array.isArray(saved) && saved.length) return new Set(saved);
  } catch (e) { /* 기본값 사용 */ }
  return new Set(FP_PRESET.map(a => a.key));
})();

function savePins() {
  localStorage.setItem(PIN_KEY, JSON.stringify([...PINNED]));
}

function togglePin(key) {
  if (PINNED.has(key)) {
    if (PINNED.size <= 3) return "레이더 축은 최소 3개가 필요합니다.";
    PINNED.delete(key);
  } else {
    if (PINNED.size >= 8) return "레이더 축은 최대 8개까지입니다.";
    PINNED.add(key);
  }
  savePins();
  return null;
}

/* ---------- 물질 비교: 사용자가 고르는 그래프 지표 ---------- */
const CMP_METRIC_KEY = "rhobench-compare-metrics";
const CMP_CHART_KEY = "rhobench-compare-chart";
const CMP_TBAR_KEY = "rhobench-compare-table-bars";
const CMP_DEFAULT_METRICS = ["homo_ev", "lumo_ev", "gap_ev", "dipole_debye",
  "oxidation_potential_v", "reduction_potential_v", "solvation_energy_kcal",
  "interaction_energy_kcal"];
const CMP_MAX_METRICS = 12;

let CMP_METRICS = (() => {
  try {
    const saved = JSON.parse(localStorage.getItem(CMP_METRIC_KEY) || "null");
    if (Array.isArray(saved)) return saved.filter(k => typeof k === "string");
  } catch (e) { /* 기본값 사용 */ }
  return [...CMP_DEFAULT_METRICS];
})();
let CMP_CHART = localStorage.getItem(CMP_CHART_KEY) || "hbar";  // hbar | vbar | line
let CMP_TABLE_BARS = localStorage.getItem(CMP_TBAR_KEY) !== "0";

function saveCmpMetrics() {
  localStorage.setItem(CMP_METRIC_KEY, JSON.stringify(CMP_METRICS));
}

function toggleCmpMetric(key) {
  const i = CMP_METRICS.indexOf(key);
  if (i >= 0) CMP_METRICS.splice(i, 1);
  else if (CMP_METRICS.length >= CMP_MAX_METRICS) return `그래프는 최대 ${CMP_MAX_METRICS}개까지입니다.`;
  else CMP_METRICS.push(key);
  saveCmpMetrics();
  return null;
}

/* ---------- 결과 화면: 결과 불러오기 · 상세 · ESW · 작업 큐 ---------- */
let SELECTED_RESULT = null;   // 상세를 보고 있는 작업 id
const EXPORT_SEL = new Set(); // 내보내기 선택 작업 id
const OPEN_GROUPS = new Set(); // 사용자가 펼쳐 둔 소재 그룹
let CMP_OPACITY = 0.7;         // 비교 차트 막대·영역 투명도
let JOB_LIST_SIG = null;       // 목록 변화 없으면 다시 그리지 않음 (펼침 유지)

function publishedJobs() {
  return JOBS_CACHE.filter(j => j.status === "PUBLISHED" && j.result);
}

function condLabel(job) {
  const c = job.result?.conditions || {};
  return `${c.method || ""} · ${c.solvent_model || ""}`;
}

function fillFilter(id, values, allLabel) {
  const sel = $(id);
  if (!sel) return;
  const prev = sel.value;
  sel.innerHTML = "";
  sel.add(new Option(allLabel, ""));
  for (const v of values) sel.add(new Option(v.length > 42 ? v.slice(0, 40) + "…" : v, v));
  if (prev && [...sel.options].some(o => o.value === prev)) sel.value = prev;
}

window.rbRenderResults = function () {
  const jobs = publishedJobs();
  const mats = [...new Set(jobs.map(j => j.material.name))];
  const conds = [...new Set(jobs.map(condLabel))];
  fillFilter("res-filter-mat", mats, "모든 소재");
  fillFilter("res-filter-cond", conds, "모든 조건");

  const fm = $("res-filter-mat").value, fc = $("res-filter-cond").value;
  const shown = jobs.filter(j => (!fm || j.material.name === fm) && (!fc || condLabel(j) === fc));
  $("res-count").textContent = `${shown.length} / ${jobs.length}건`;

  const picker = $("result-picker");
  if (!shown.length) {
    picker.className = "empty small";
    picker.textContent = jobs.length
      ? "조건에 맞는 결과가 없습니다. 필터를 바꿔보세요."
      : "완료된 계산이 없습니다. 'DFT 계산'에서 제출하세요.";
  } else {
    picker.className = "mol-grid";
    picker.innerHTML = shown.map(j => `
      <button class="mol-card ${SELECTED_RESULT === j.id ? "selected" : ""}" data-open="${esc(j.id)}">
        <b>${esc(j.material.name)}</b>
        <span class="small muted">${esc(condLabel(j))}</span>
        <span class="mono small muted">${esc(j.id)} · ${esc(fmtTime(j.finishedAt))}</span>
      </button>`).join("");
    picker.querySelectorAll("[data-open]").forEach(b => b.addEventListener("click", () => {
      const job = JOBS_CACHE.find(x => x.id === b.dataset.open);
      if (job) { SELECTED_RESULT = job.id; showResult(job); window.rbRenderResults(); }
    }));
  }

  renderJobList();
};

function fmtTime(t) {
  return t ? new Date(t * 1000).toLocaleString("ko-KR", {month: "numeric", day: "numeric",
    hour: "2-digit", minute: "2-digit"}) : "—";
}

function fpRange(key) {
  // 저장된 PUBLISHED 결과 전체로 min-max 범위 산출 (1건뿐이면 ±20% 여유)
  const vals = JOBS_CACHE.filter(j => j.status === "PUBLISHED")
    .map(j => j.result?.descriptors?.[key]).filter(v => typeof v === "number");
  if (!vals.length) return null;
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi - lo < 1e-9) { const pad = Math.abs(hi) * 0.2 + 0.5; lo -= pad; hi += pad; }
  return [lo, hi];
}

function renderAxisPicker(containerId, onChange) {
  const box = $(containerId);
  if (!box) return;
  const keys = numericDescriptorKeys();
  for (const k of PINNED) if (!keys.includes(k)) keys.push(k);
  box.innerHTML = `<div class="toolbar" style="margin-bottom:6px">
      <span class="muted small">레이더 축 = ★ 고정 물성 (3~8개)</span>
      <button class="btn" data-fp-preset="1" type="button">기본 축으로</button>
    </div>
    <div style="display:flex;flex-wrap:wrap;gap:6px">
      ${keys.map(k => `<button class="btn ${PINNED.has(k) ? "primary" : ""}" data-fp-axis="${esc(k)}"
          type="button" style="padding:3px 10px;font-size:11.5px">${esc(axisMeta(k).label)}</button>`).join("")}
    </div>
    <div class="form-error" data-fp-msg style="margin-top:4px"></div>`;
  box.querySelectorAll("[data-fp-axis]").forEach(btn => btn.addEventListener("click", () => {
    const msg = togglePin(btn.dataset.fpAxis);
    if (msg) { box.querySelector("[data-fp-msg]").textContent = msg; return; }
    onChange();
  }));
  box.querySelector("[data-fp-preset]").addEventListener("click", () => {
    PINNED = new Set(FP_PRESET.map(a => a.key));
    savePins();
    onChange();
  });
}

/* ---------- 비교 그래프 지표 선택 ---------- */
function comparableKeys(chosen) {
  // 선택한 물질 중 2건 이상에서 숫자로 존재하는 지표 (표시 순서는 DESC_LABELS 순)
  const count = {};
  for (const j of chosen) {
    for (const [k, v] of Object.entries(j.result?.descriptors || {})) {
      if (typeof v === "number") count[k] = (count[k] || 0) + 1;
    }
  }
  const order = Object.keys(DESC_LABELS);
  return Object.keys(count).filter(k => count[k] >= 2 && k !== "potential_reference")
    .sort((a, b) => {
      const ia = order.indexOf(a), ib = order.indexOf(b);
      return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib);
    });
}

function renderMetricPicker(chosen, onChange) {
  const box = $("cmp-metric-picker");
  if (!box) return;
  const keys = comparableKeys(chosen);
  for (const k of CMP_METRICS) if (!keys.includes(k)) keys.push(k);
  if (!keys.length) {
    box.innerHTML = '<p class="muted small" style="margin:8px 0 0">' +
      "두 개 이상 선택하면 그래프로 그릴 지표를 고를 수 있습니다.</p>";
    return;
  }
  box.innerHTML = `<div class="toolbar" style="margin:10px 0 6px">
      <span class="muted small">그래프로 그릴 지표 (클릭해서 켜고 끄기 · 최대 ${CMP_MAX_METRICS}개)</span>
      <button class="btn" data-cm-preset="1" type="button">기본 지표로</button>
      <button class="btn" data-cm-clear="1" type="button">모두 끄기</button>
    </div>
    <div style="display:flex;flex-wrap:wrap;gap:6px">
      ${keys.map(k => {
        const m = axisMeta(k);
        return `<button class="btn ${CMP_METRICS.includes(k) ? "primary" : ""}" data-cm-key="${esc(k)}"
          type="button" style="padding:3px 10px;font-size:11.5px"
          title="${esc(m.label)}${m.unit ? ` (${m.unit})` : ""}">${esc(m.label)}</button>`;
      }).join("")}
    </div>
    <div class="form-error" data-cm-msg style="margin-top:4px"></div>`;
  box.querySelectorAll("[data-cm-key]").forEach(btn => btn.addEventListener("click", () => {
    const msg = toggleCmpMetric(btn.dataset.cmKey);
    if (msg) { box.querySelector("[data-cm-msg]").textContent = msg; return; }
    onChange();
  }));
  box.querySelector("[data-cm-preset]").addEventListener("click", () => {
    CMP_METRICS = [...CMP_DEFAULT_METRICS];
    saveCmpMetrics();
    onChange();
  });
  box.querySelector("[data-cm-clear]").addEventListener("click", () => {
    CMP_METRICS = [];
    saveCmpMetrics();
    onChange();
  });
}

/* ---------- 비교 그래프: 가로 막대 · 세로 막대 · 꺾은선 ---------- */
function shortName(name, n) {
  const s = String(name);
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

function cellText(v) {
  if (typeof v === "number") return fmt(v);
  if (v == null) return "—";
  if (Array.isArray(v)) {
    const parts = v.slice(0, 3).map(o => (o && typeof o === "object" && "population_pct" in o)
      ? `${fmt(o.population_pct)}% (Δ${fmt(o.rel_e_kcal)})` : JSON.stringify(o));
    return parts.join(" · ") + (v.length > 3 ? ` 외 ${v.length - 3}개` : "");
  }
  if (typeof v === "object") return Object.entries(v).map(([k, x]) => `${k} ${fmt(x)}`).join(" · ");
  return String(v);
}

function rowScale(nums) {
  // 표 미니 막대: 그 줄 안에서의 상대 위치 (절대 0 기준이 아님 — 총에너지처럼 큰 값도 차이가 보이게)
  const lo = Math.min(...nums), hi = Math.max(...nums);
  const pad = hi - lo > 1e-12 ? (hi - lo) * 0.18 : Math.abs(hi) * 0.2 + 0.5;
  return {lo: lo - pad, hi: hi + pad};
}

function chartScale(vals) {
  // 0을 반드시 포함하는 축 — 음수 지표(HOMO, 용매화 에너지 등)를 올바른 방향으로 표시
  let lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
  if (hi - lo < 1e-12) hi = lo + 1;
  const pad = (hi - lo) * 0.04;
  return {lo: lo - (lo < 0 ? pad : 0), hi: hi + (hi > 0 ? pad : 0)};
}

function svgMetricChart(entries, unit) {
  const vals = entries.map(e => e.v);
  const {lo, hi} = chartScale(vals);
  const span = hi - lo;
  const bar = (e, i) => `var(--series-${(e.i % 8) + 1})`;
  const tip = e => `<title>${esc(e.name)}: ${fmt(e.v)}${unit ? " " + unit : ""}</title>`;

  if (CMP_CHART === "hbar") {
    // 값 라벨은 오른쪽 고정 열에 — 막대 길이와 상관없이 잘리거나 겹치지 않는다
    const W = 360, rowH = 38, PAD = 6, barMax = W - 80;
    const H = entries.length * rowH + PAD;
    const x = v => (v - lo) / span * barMax;
    const zero = x(0);
    let sv = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:380px" role="img">`;
    if (lo < 0 && hi > 0) sv += `<line x1="${zero}" y1="${PAD}" x2="${zero}" y2="${H}" class="gridline" />`;
    entries.forEach((e, k) => {
      const top = k * rowH + PAD, xv = x(e.v);
      const bx = Math.min(zero, xv), bw = Math.max(2, Math.abs(xv - zero));
      const col = bar(e, k);
      sv += `<text x="0" y="${top + 9}" class="axis-label">${esc(e.name)}</text>
        <rect x="${bx}" y="${top + 15}" width="${bw}" height="14" rx="3" fill="${col}"
          fill-opacity="${CMP_OPACITY}" stroke="${col}" stroke-opacity="0.85">${tip(e)}</rect>
        <text x="${W}" y="${top + 26}" class="value-label" text-anchor="end">${fmt(e.v)}</text>`;
    });
    return sv + "</svg>";
  }

  if (CMP_CHART === "vbar") {
    const colW = 78, W = Math.max(240, entries.length * colW), TOP = 16, BOT = 34;
    const H = 190, plot = H - TOP - BOT;
    const y = v => TOP + (hi - v) / span * plot;
    const zero = y(0);
    let sv = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:${Math.max(300, W)}px" role="img">`;
    sv += `<line x1="0" y1="${zero}" x2="${W}" y2="${zero}" class="gridline" />`;
    entries.forEach((e, k) => {
      const cx = k * colW + colW / 2, yv = y(e.v), col = bar(e, k);
      const by = Math.min(zero, yv), bh = Math.max(2, Math.abs(yv - zero));
      const pos = e.v >= 0;
      sv += `<rect x="${cx - 17}" y="${by}" width="34" height="${bh}" rx="3" fill="${col}"
          fill-opacity="${CMP_OPACITY}" stroke="${col}" stroke-opacity="0.85">${tip(e)}</rect>
        <text x="${cx}" y="${pos ? by - 4 : by + bh + 11}" class="value-label"
          text-anchor="middle">${fmt(e.v)}</text>
        <text x="${cx}" y="${H - 12}" class="axis-label" text-anchor="middle"
          >${esc(shortName(e.name, 8))}<title>${esc(e.name)}</title></text>`;
    });
    return sv + "</svg>";
  }

  // line — 물질 순서에 따른 추이
  const colW = 78, W = Math.max(240, entries.length * colW), TOP = 16, BOT = 34;
  const H = 190, plot = H - TOP - BOT;
  const y = v => TOP + (hi - v) / span * plot;
  const px = k => k * colW + colW / 2;
  const zero = y(0);
  const pts = entries.map((e, k) => `${px(k)},${y(e.v)}`).join(" ");
  let sv = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:${Math.max(300, W)}px" role="img">`;
  sv += `<line x1="0" y1="${zero}" x2="${W}" y2="${zero}" class="gridline" />
    <polyline points="${pts}" fill="none" stroke="var(--accent)" stroke-width="2"
      stroke-opacity="${CMP_OPACITY}" />`;
  entries.forEach((e, k) => {
    const col = bar(e, k), yv = y(e.v);
    sv += `<circle cx="${px(k)}" cy="${yv}" r="5" fill="${col}" fill-opacity="${CMP_OPACITY}"
        stroke="${col}">${tip(e)}</circle>
      <text x="${px(k)}" y="${yv - 9}" class="value-label" text-anchor="middle">${fmt(e.v)}</text>
      <text x="${px(k)}" y="${H - 12}" class="axis-label" text-anchor="middle"
        >${esc(shortName(e.name, 8))}<title>${esc(e.name)}</title></text>`;
  });
  return sv + "</svg>";
}

function svgRadar(series) {
  // series: 기술자 객체 하나 또는 [{name, d, idx}] 배열 (여러 물질 오버레이)
  const list = Array.isArray(series) ? series : [{name: null, d: series, idx: 0}];
  const axes = [...PINNED].map(key => {
    const meta = axisMeta(key);
    // 저장된 결과 전체로 범위를 잡되, 값이 없으면 현재 결과 값으로 대체 범위 구성
    let range = fpRange(key);
    if (!range) {
      const here = list.map(s => s.d[key]).filter(v => typeof v === "number");
      if (!here.length) return {...meta, range: null};
      const v = here[0], pad = Math.abs(v) * 0.2 + 0.5;
      range = [v - pad, v + pad];
    }
    return {...meta, range};
  });
  if (axes.length < 3) {
    return '<p class="muted small">레이더를 그리려면 ★ 고정 물성이 3개 이상 필요합니다.</p>';
  }
  const W = 460, H = 340, CX = W / 2, CY = H / 2, R = 92;
  const ang = i => -Math.PI / 2 + i * 2 * Math.PI / axes.length;
  const pt = (i, f) => [CX + Math.cos(ang(i)) * R * f, CY + Math.sin(ang(i)) * R * f];
  const norm = (a, v) => {
    let t = (v - a.range[0]) / (a.range[1] - a.range[0]);
    if (a.lower) t = 1 - t;
    return Math.max(0.06, Math.min(1, t));
  };
  let sv = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:460px" role="img">`;
  for (const f of [0.25, 0.5, 0.75, 1]) {
    sv += `<polygon points="${axes.map((_, i) => pt(i, f).map(n => n.toFixed(1)).join(",")).join(" ")}"
      fill="none" stroke="var(--grid)"/>`;
  }
  axes.forEach((a, i) => {
    const [x, y] = pt(i, 1);
    sv += `<line x1="${CX}" y1="${CY}" x2="${x}" y2="${y}" stroke="var(--grid)"/>`;
    const [lx, ly] = pt(i, 1.2);
    const anchor = Math.abs(lx - CX) < 12 ? "middle" : (lx > CX ? "start" : "end");
    const missing = !a.range;
    sv += `<text x="${lx}" y="${ly}" text-anchor="${anchor}" class="axis-label"
        ${missing ? 'opacity="0.45"' : ""}>${esc(a.label)}</text>
      <text x="${lx}" y="${ly + 14}" text-anchor="${anchor}" class="axis-label" opacity="0.7">
        (${esc(a.unit || "-")}${a.lower ? ", ↓바깥" : ""}${missing ? ", 값 없음" : ""})</text>`;
  });
  list.forEach(sObj => {
    const col = list.length > 1 ? `var(--series-${(sObj.idx % 8) + 1})` : "var(--accent)";
    const poly = axes.map((a, i) => {
      const v = sObj.d[a.key];
      const f = (a.range && typeof v === "number") ? norm(a, v) : 0.06;
      return pt(i, f).map(n => n.toFixed(1)).join(",");
    }).join(" ");
    sv += `<polygon points="${poly}"
      fill="${list.length > 1 ? "none" : "var(--accent)"}"
      fill-opacity="${list.length > 1 ? 0 : CMP_OPACITY * 0.22}"
      stroke="${col}" stroke-width="2"/>`;
    axes.forEach((a, i) => {
      const v = sObj.d[a.key];
      if (!a.range || typeof v !== "number") return;
      const [x, y] = pt(i, norm(a, v));
      sv += `<circle cx="${x}" cy="${y}" r="4" fill="${col}" class="ring-mark">
        <title>${sObj.name ? esc(sObj.name) + " — " : ""}${esc(a.label)}: ${fmt(v)} ${esc(a.unit)}</title></circle>`;
    });
  });
  sv += "</svg>";
  if (list.length > 1) {
    sv += `<div class="legend">${list.map(sObj =>
      `<span class="legend-item"><span class="legend-swatch"
        style="background:var(--series-${(sObj.idx % 8) + 1})"></span>${esc(sObj.name)}</span>`).join("")}</div>`;
  }
  return sv;
}

function svgAdsorption(ads) {
  const items = Object.values(ads);
  if (!items.length) return "";
  const W = 560, H = 210, L = 44, B = 40, T = 30;
  const maxV = Math.max(...items.map(i => Math.abs(i.energy_kj)), 1);
  const top = Math.ceil(maxV / 10) * 10;
  const y = v => T + (1 - v / top) * (H - T - B);
  const bw = Math.min(56, (W - L - 20) / items.length * 0.5);
  let sv = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:600px" role="img">`;
  for (const g of [0, top / 2, top]) {
    sv += `<line x1="${L}" y1="${y(g)}" x2="${W - 12}" y2="${y(g)}" class="gridline"/>
      <text x="${L - 6}" y="${y(g) + 4}" text-anchor="end" class="axis-label">${g}</text>`;
  }
  sv += `<text x="4" y="12" class="axis-label">|E_ad| (kJ/mol)</text>`;
  items.forEach((it, i) => {
    const cx = L + 24 + i * ((W - L - 40) / items.length);
    const v = Math.abs(it.energy_kj);
    sv += `<rect x="${cx - bw / 2}" y="${y(v)}" width="${bw}" height="${y(0) - y(v)}"
        rx="2" fill="var(--series-${(i % 8) + 1})"><title>${esc(it.desc)}: ${it.energy_kj} kJ/mol</title></rect>
      <text x="${cx}" y="${y(v) - 5}" text-anchor="middle" class="value-label">${it.energy_kj}</text>
      <text x="${cx}" y="${H - 20}" text-anchor="middle" class="axis-label">${esc(it.label)}</text>`;
  });
  return sv + "</svg>";
}

function svgHomoLumoAxis(entries) {
  // entries: {name, homo, lumo, idx}[] — 단일이면 길이 1
  const marks = ELECTRODES.map(e => ({label: e.label.split(" (")[0], mu: -(1.44 + e.v)}));
  const vals = entries.flatMap(e => [e.homo, e.lumo]).concat(marks.map(m => m.mu));
  const lo = Math.min(...vals) - 0.6, hi = Math.max(...vals) + 0.6;
  const rowH = 26, W = 700, L = 148, H = 62 + entries.length * rowH + 34;
  const x = v => L + (v - lo) / (hi - lo) * (W - L - 30);
  let sv = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:680px" role="img">`;
  const start = Math.ceil(lo), end = Math.floor(hi);
  const step = (end - start) > 14 ? 2 : 1;
  for (let v = start; v <= end; v += step) {
    sv += `<line x1="${x(v)}" y1="46" x2="${x(v)}" y2="${H - 30}" class="gridline"/>
      <text x="${x(v)}" y="${H - 14}" text-anchor="middle" class="axis-label">${v}</text>`;
  }
  sv += `<text x="${W - 16}" y="30" class="axis-label">eV</text>`;
  marks.forEach((m, i) => {
    const ly = i % 2 ? 40 : 26;
    const col = m.mu < -2.5 ? "var(--pin)" : "var(--accent)";
    sv += `<line x1="${x(m.mu)}" y1="${ly + 3}" x2="${x(m.mu)}" y2="${H - 30}"
        stroke="${col}" stroke-dasharray="4 3"/>
      <text x="${x(m.mu)}" y="${ly}" text-anchor="middle" class="axis-label"
        fill="${col}">${esc(m.label)}</text>`;
  });
  entries.forEach((e, k) => {
    const y = 62 + k * rowH;
    const col = entries.length > 1 ? `var(--series-${(e.idx % 8) + 1})` : "var(--accent)";
    const nm = e.name.length > 13 ? e.name.slice(0, 12) + "…" : e.name;
    sv += `<text x="${L - 8}" y="${y + 4}" text-anchor="end" class="axis-label">${esc(nm)}
        <title>${esc(e.name)}</title></text>
      <line x1="${x(e.homo)}" y1="${y}" x2="${x(e.lumo)}" y2="${y}"
        stroke="${col}" stroke-width="8" stroke-linecap="round" opacity="0.5"/>
      <line x1="${x(e.homo)}" y1="${y - 7}" x2="${x(e.homo)}" y2="${y + 7}" stroke="${col}" stroke-width="2.5"/>
      <line x1="${x(e.lumo)}" y1="${y - 7}" x2="${x(e.lumo)}" y2="${y + 7}" stroke="${col}" stroke-width="2.5"/>
      <text x="${x(e.homo)}" y="${y - 10}" text-anchor="middle" class="value-label">${e.homo}</text>
      <text x="${x(e.lumo)}" y="${y - 10}" text-anchor="middle" class="value-label">${e.lumo}</text>`;
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
      <div class="stat-value">${fmt(v)}<span class="stat-unit"> ${u}</span></div>
      <div class="stat-sub">${sub}</div></div>`).join("");

  let html = `
    <div class="small muted mono" style="margin-bottom:8px">${esc(job.id)} ·
      ${esc(r.conditions.method)} · ${esc(r.conditions.solvent_model)} ·
      ${esc(String(r.conditions.temperature_k))} K · wall ${r.wall_time_s}s</div>
    ${r.binder_report ? binderScorecard(r.binder_report) : ""}
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
          <button class="btn" id="v3d-cloud" type="button">전자구름</button>
        </div>
        <div id="viewer3d" style="width:100%;height:280px;position:relative;
          border:1px solid var(--grid);border-radius:10px;overflow:hidden"></div>
        <div class="legend" id="viewer3d-legend" style="margin-top:6px"></div>
        <p class="muted small" id="viewer3d-note" style="margin:6px 0 0"></p>
      </div>
    </div>`;

  if (d.homo_ev != null && d.lumo_ev != null) {
    html += `<h3 style="font-size:13px;color:var(--accent);margin-top:16px">
        HOMO / LUMO (전극 페르미 준위 공통 축)</h3>
      ${svgHomoLumoAxis([{name: job.material.name, homo: d.homo_ev, lumo: d.lumo_ev, idx: 0}])}
      <p class="muted small" style="margin:4px 0 0">
        막대 왼쪽 끝 = HOMO, 오른쪽 끝 = LUMO, 길이 = 갭 · 점선 = 전극 페르미 준위 근사
        μ ≈ −(1.44 + V) eV — <b>LUMO가 음극 준위보다 낮으면 환원</b>,
        <b>HOMO가 양극 준위보다 높으면 산화</b> 위험</p>`;
  }
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

  const shown = new Set(["potential_reference", "conformer_populations",
                         "mep_points", "surface_adsorption", "bde_all",
                         "bde_weakest_bond"]);
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
  html += `<h3 style="font-size:13px;color:var(--accent);margin-top:18px">
      물성 전체 목록 <span class="muted small">(★를 클릭하면 고정 — 레이더 축이 됩니다)</span></h3>
    <div class="scroll-x"><table class="table" style="min-width:520px">
      <tr><th></th><th>물성</th><th>단위</th><th class="num" style="text-align:right">값</th></tr>
      ${listRows}</table></div>
    <div class="form-error" id="pin-msg"></div>`;

  let condRows = "";
  for (const [k, v] of Object.entries(r.conditions)) {
    condRows += `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`;
  }
  let provRows = "";
  for (const [k, v] of Object.entries(r.provenance || {})) {
    provRows += `<tr><th>${esc(k)}</th><td>${esc(String(v))}</td></tr>`;
  }
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
    <details style="margin-top:14px"><summary class="small muted">계산 조건 전체</summary>
      <table class="kv-table" style="margin-top:6px">${condRows}</table></details>
    ${provRows ? `<details style="margin-top:6px">
      <summary class="small muted">재현성 정보 (엔진·버전·수렴 설정)</summary>
      <table class="kv-table" style="margin-top:6px">${provRows}</table></details>` : ""}
    <h3 style="font-size:13px;color:var(--accent);margin-top:14px">주의사항</h3>
    <ul class="log-list">${r.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul>
    <details style="margin-top:8px"><summary class="small muted">XYZ 좌표 보기</summary>
      <pre class="xyz">${esc(r.structure_xyz)}</pre></details>`;

  $("result-body").innerHTML = html;
  $("result-body").querySelectorAll("[data-pin]").forEach(b => b.addEventListener("click", () => {
    const msg = togglePin(b.dataset.pin);
    const box = $("pin-msg");
    if (msg) { if (box) box.textContent = msg; return; }
    if (box) box.textContent = "";
    showResult(job);   // 핀 변경을 목록·레이더에 즉시 반영
  }));
  if ($("fp-axis-picker")) {
    const redraw = () => {
      renderAxisPicker("fp-axis-picker", redraw);
      $("fp-radar").innerHTML = svgRadar(d);
    };
    redraw();
  }
  $("v3d-element").addEventListener("click", () => { VIEW_MODE = "element"; render3D(CURRENT_RESULT); });
  $("v3d-charge").addEventListener("click", () => { VIEW_MODE = "charge"; render3D(CURRENT_RESULT); });
  $("v3d-cloud").addEventListener("click", () => { VIEW_MODE = "cloud"; render3D(CURRENT_RESULT); });
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

const COLOR = {H:"#cfcfcf",C:"#3a3a3a",N:"#2f5bd8",O:"#d62828",F:"#4fb944",
               S:"#c9a227",P:"#e08020",Cl:"#3fae49",Br:"#8a4b26",I:"#7a3fa0",Li:"#b04fd8"};

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
  const mepPts = r.descriptors?.mep_points;
  const baseNote = solventIdx.size
    ? "선명한 분자 = 용질 · 흐린 분자 = 명시적 주변 분자 · 드래그 회전 / 휠 확대"
    : "드래그로 회전, 휠로 확대할 수 있습니다.";
  const legend = $("viewer3d-legend");
  if (legend) {
    if (VIEW_MODE === "element") {
      const present = [...new Set(atoms.map(a => a.el))];
      legend.innerHTML = present.map(el =>
        `<span class="legend-item"><span class="legend-swatch"
          style="background:${COLOR[el] ?? "#888"};border:1px solid rgba(0,0,0,.15)"></span>${esc(el)}</span>`).join("");
    } else if (VIEW_MODE === "charge") {
      legend.innerHTML = `<span class="legend-item"><span class="legend-swatch"
          style="background:rgb(75,145,216)"></span>음전하 (친핵 부위)</span>
        <span class="legend-item"><span class="legend-swatch"
          style="background:#fff;border:1px solid var(--border)"></span>중성</span>
        <span class="legend-item"><span class="legend-swatch"
          style="background:rgb(214,45,40)"></span>양전하 (친전자 부위)</span>`;
    } else {
      legend.innerHTML = `<span class="legend-item">점이 촘촘할수록 전자 밀도 ρ(r)가 높은 영역</span>`;
    }
  }
  note.textContent = VIEW_MODE === "charge"
    ? "부분 전하(Mulliken): 파랑 = 음전하(친핵 부위) · 빨강 = 양전하(친전자 부위) — " + baseNote
    : baseNote;
  $("v3d-element")?.classList.toggle("primary", VIEW_MODE === "element");
  $("v3d-charge")?.classList.toggle("primary", VIEW_MODE === "charge");
  $("v3d-cloud")?.classList.toggle("primary", VIEW_MODE === "cloud");
  const cloud = r.density_cloud;
  if (VIEW_MODE === "cloud") {
    note.textContent = cloud
      ? "전자구름: 점의 밀집도가 전자 밀도 ρ(r)에 비례 — 점이 촘촘할수록 전자가 많이 머무는 영역 · 드래그 회전 / 휠 확대"
      : "이 결과에는 전자밀도 데이터가 없습니다 (이전 버전에서 계산된 작업). 다시 계산하면 표시됩니다.";
  }

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
      const cloudMode = VIEW_MODE === "cloud";
      ctx.strokeStyle = faded ? "rgba(140,140,140,.45)"
        : (cloudMode ? "rgba(60,60,60,.55)" : "rgba(90,90,90,.9)");
      ctx.lineWidth = faded ? 1.4 : (cloudMode ? 1.4 : 2.6);
      ctx.beginPath(); ctx.moveTo(p.sx, p.sy); ctx.lineTo(q.sx, q.sy); ctx.stroke();
    }
    if (VIEW_MODE === "cloud" && cloud) {
      const rmax = cloud.rho_max || 1;
      const cp3 = cloud.points.map((q, i) => {
        const x0 = q[0] - cx, y0 = q[1] - cy, z0 = q[2] - cz;
        const x1 = x0 * cyaw + z0 * syaw, z1 = -x0 * syaw + z0 * cyaw;
        const y2 = y0 * cp - z1 * sp, z2 = y0 * sp + z1 * cp;
        return {sx: W / 2 + x1 * scale, sy: H / 2 - y2 * scale, z: z2, rho: cloud.rho[i]};
      }).sort((a, b) => a.z - b.z);
      for (const q of cp3) {
        const t = Math.min(1, Math.pow(q.rho / rmax, 0.28));
        ctx.globalAlpha = 0.10 + 0.42 * t;
        ctx.fillStyle = `rgb(${Math.round(70 + 120 * (1 - t))},${Math.round(120 + 60 * (1 - t))},${Math.round(200 + 40 * (1 - t))})`;
        ctx.beginPath();
        ctx.arc(q.sx, q.sy, 1.1 + 2.6 * t, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    }
    if (mepPts && VIEW_MODE === "charge") {
      for (const [kind, pos] of [["min", mepPts.min], ["max", mepPts.max]]) {
        if (!pos) continue;
        const x0 = pos[0] - cx, y0 = pos[1] - cy, z0 = pos[2] - cz;
        const x1 = x0 * cyaw + z0 * syaw, z1 = -x0 * syaw + z0 * cyaw;
        const y2 = y0 * cp - z1 * sp;
        const sx = W / 2 + x1 * scale, sy = H / 2 - y2 * scale;
        ctx.setLineDash([3, 2]);
        ctx.strokeStyle = kind === "min" ? "#2a78d6" : "#e34948";
        ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(sx, sy, 9, 0, Math.PI * 2); ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = ctx.strokeStyle;
        ctx.font = "10px system-ui";
        ctx.textAlign = "center";
        ctx.fillText(kind === "min" ? "MEP− (Li⁺ 배위)" : "MEP+", sx, sy - 12);
      }
    }
    proj.sort((a, b) => a.z - b.z);
    for (const p of proj) {
      const faded = solventIdx.has(p.i);
      const shrink = VIEW_MODE === "cloud" ? 0.35 : 1;
      const rr = (rad(p.el) * 0.45 + 0.18) * scale * (faded ? 0.7 : 1) * shrink;
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

boot();


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

function eswReason(job) {
  // 왜 ESW에 못 그리는지 — 조용히 빠지지 않도록 이유를 밝힌다
  const d = job.result?.descriptors || {};
  if (d.ip_vertical_ev != null || d.ea_vertical_ev != null) {
    return "기준 전극 '없음'으로 계산 — IP/EA만 있고 전위 환산값이 없습니다";
  }
  const purpose = job.settings?.purpose || "";
  if (!purpose.includes("전위") && !purpose.includes("지문")) {
    return `목적이 '${purpose}' — 전위를 계산하지 않았습니다`;
  }
  return "전위 값이 없습니다";
}

function eswSection(jobs) {
  const usable = jobs.filter(j => j.result?.descriptors?.oxidation_potential_v != null
                              && j.result?.descriptors?.reduction_potential_v != null);
  const skipped = jobs.filter(j => !usable.includes(j));
  const skipNote = skipped.length ? `
    <div class="banner warn" style="margin:0 0 10px">
      <b>${skipped.length}개 물질은 이 차트에 표시할 수 없습니다.</b>
      <ul class="log-list" style="margin-top:4px">
        ${skipped.map(j => `<li>${esc(j.material.name)} — ${esc(eswReason(j))}</li>`).join("")}
      </ul>
      <span class="small">해결: 'DFT 계산'에서 목적을 <b>"전자구조 + 산화/환원 전위"</b>로,
        기준 전극을 <b>Li/Li+</b>(또는 SHE)로 두고 다시 계산하세요.</span>
    </div>` : "";
  if (!usable.length) {
    return skipNote + '<div class="empty small">전위가 계산된 결과가 없습니다.<br>' +
      'DFT 계산에서 목적을 "전자구조 + 산화/환원 전위"로 선택해 제출하세요.</div>';
  }
  jobs = usable;
  const allV = jobs.flatMap(j => {
    const dd = j.result.descriptors;
    return [dd.reduction_potential_gibbs_v ?? dd.reduction_potential_v,
            dd.oxidation_potential_gibbs_v ?? dd.oxidation_potential_v];
  }).filter(v => typeof v === "number");
  const [V0, V1, STEP] = niceRange([...allV, ...ELECTRODES.map(e => e.v), 0], 0.6);
  const W = 820, H = 46 * jobs.length + 82, L = 170;
  const x = v => L + (v - V0) / (V1 - V0) * (W - L - 42);
  let svg = `<svg class="esw-chart" viewBox="0 0 ${W} ${H}" role="img">`;
  for (let v = V0; v <= V1 + 1e-9; v += STEP) {
    svg += `<line x1="${x(v)}" y1="32" x2="${x(v)}" y2="${H - 34}" stroke="var(--grid)" />
      <text x="${x(v)}" y="${H - 20}" font-size="11" text-anchor="middle" fill="var(--muted)">${v}</text>`;
  }
  svg += `<text x="${(L + W) / 2}" y="${H - 4}" font-size="11" text-anchor="middle"
    fill="var(--muted)">전위 (V vs Li/Li⁺)</text>`;
  ELECTRODES.forEach((el, i) => {
    const ly = i % 2 ? 24 : 12;
    svg += `<line x1="${x(el.v)}" y1="${ly + 4}" x2="${x(el.v)}" y2="${H - 34}"
        stroke="var(--pin)" stroke-dasharray="4 3" />
      <text x="${x(el.v)}" y="${ly}" font-size="10.5" text-anchor="middle"
        fill="var(--pin)">${esc(el.label)}</text>`;
  });
  jobs.forEach((j, i) => {
    const d = j.result.descriptors;
    const red = d.reduction_potential_gibbs_v ?? d.reduction_potential_v;
    const ox = d.oxidation_potential_gibbs_v ?? d.oxidation_potential_v;
    const y = 52 + i * 46;
    const nm = j.material.name.length > 13 ? j.material.name.slice(0, 12) + "…" : j.material.name;
    const col = jobs.length > 1 ? `var(--series-${(i % 8) + 1})` : "var(--accent)";
    svg += `<text x="${L - 8}" y="${y + 5}" font-size="12" text-anchor="end"
        fill="var(--text-1)">${esc(nm)}<title>${esc(j.material.name)}</title></text>
      <rect x="${x(red)}" y="${y - 8}" width="${Math.max(2, x(ox) - x(red))}" height="16" rx="4"
        fill="${col}" fill-opacity="${CMP_OPACITY * 0.45}" stroke="${col}" />
      <text x="${x(red) - 4}" y="${y + 4}" font-size="10" text-anchor="end"
        fill="var(--text-2)">${fmt(red)}</text>
      <text x="${x(ox) + 4}" y="${y + 4}" font-size="10" fill="var(--text-2)">${fmt(ox)}</text>`;
  });
  svg += "</svg>";

  let rows = "";
  for (const j of jobs) {
    const d = j.result.descriptors;
    const red = d.reduction_potential_gibbs_v ?? d.reduction_potential_v;
    const ox = d.oxidation_potential_gibbs_v ?? d.oxidation_potential_v;
    // 흑연 판정은 «구동 범위 전체가 ESW 안에 들어오는가» — 한 점이 아니라 포함 관계
    const GR_LO = 0.01, GR_HI = 0.25;
    const anodeOK = red < GR_LO, anodeMid = red <= GR_HI;
    const ncmOK = ox > 4.3, lfpOK = ox > 3.45;
    rows += `<tr><td><b>${esc(j.material.name)}</b><br>
        <span class="mono small muted">${esc(j.id)}</span></td>
      <td>${fmt(red)} ~ ${fmt(ox)} V</td>
      <td class="${anodeOK ? "verdict-ok" : anodeMid ? "verdict-mid" : "verdict-no"}">${anodeOK ? "안정" : anodeMid ? "경계" : "환원 분해 우려"}</td>
      <td class="${lfpOK ? "verdict-ok" : "verdict-no"}">${lfpOK ? "안정" : "산화 우려"}</td>
      <td class="${ncmOK ? "verdict-ok" : "verdict-no"}">${ncmOK ? "안정" : "산화 우려"}</td>
      <td><button class="btn" type="button"
        onclick="window.rbEswDiagnose('${esc(j.id)}','graphite')">왜?</button></td></tr>`;
  }
  return skipNote + svg + `
    <div class="scroll-x" style="margin-top:14px"><table class="kv-table" style="min-width:640px">
      <tr><th>물질</th><th>ESW (환원~산화)</th><th>음극 Graphite (0.01~0.25 V)</th>
        <th>양극 LFP (3.45 V)</th><th>양극 NCM811 (4.3 V)</th><th>근거</th></tr>
      ${rows}</table></div>
    <div id="esw-diag" style="margin-top:12px">${ESW_DIAG?.html || ""}</div>
    <ul class="log-list" style="margin-top:10px">
      <li>판정 기준은 <b>포함 관계</b>입니다 — 전극 «구동 범위 전체»가 물질의 ESW 안에 들어와야 안정합니다. 한쪽 끝만 보면 중간에서 분해되는 경우를 놓칩니다.</li>
      <li>흑연은 단일 전위가 아니라 0.01~0.25 V 범위에서 작동합니다 (리튬화 단계 평탄부 0.20 · 0.11 · 0.08 V).</li>
      <li>「왜?」 버튼을 누르면 판정을 <b>구조 → LUMO → EA → 환원 전위 → 판정</b> 으로 되짚어 보여줍니다.</li>
      <li>ΔG 기반 전위가 있으면 우선 사용, 없으면 단열/수직 전위 사용</li>
      <li>주의: 실제 전지에서는 SEI/CEI 피막의 동역학적 보호가 크게 작용합니다 — 예: EC는 환원 분해되지만 안정적 SEI를 형성해 사용됩니다. 이 판정은 스크리닝용 열역학 지표입니다.</li>
    </ul>`;
}

/* ================= 물질 비교 ================= */
const COMPARE_SEL = new Set();

window.rbRenderCompare = function () {
  const jobs = JOBS_CACHE.filter(j => j.status === "PUBLISHED" && j.result);
  const box = $("compare-body");
  if (!jobs.length) {
    box.innerHTML = '<div class="empty small">PUBLISHED 결과가 없습니다.</div>';
    renderMetricPicker([], () => window.rbRenderCompare());
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
    // 요약 타일 — 물질별 핵심 지표
    table += '<div class="stat-row">' + chosen.map((j, i) => {
      const dd = j.result.descriptors;
      return `<div class="stat-tile" style="border-left:4px solid var(--series-${(i % 8) + 1})">
        <div class="stat-label">${esc(j.material.name)}</div>
        <div class="stat-value">${dd.gap_ev ?? "—"}<span class="stat-unit"> eV 갭</span></div>
        <div class="stat-sub">HOMO ${dd.homo_ev ?? "—"} · LUMO ${dd.lumo_ev ?? "—"} eV</div></div>`;
    }).join("") + "</div>";

    // HOMO/LUMO 공통 축 오버레이
    const hl = chosen.map((j, i) => ({name: j.material.name, idx: i,
      homo: j.result.descriptors.homo_ev, lumo: j.result.descriptors.lumo_ev}))
      .filter(e => e.homo != null && e.lumo != null);
    if (hl.length >= 2) {
      table += `<h3 style="font-size:13px;color:var(--accent);margin:14px 0 4px">
          HOMO / LUMO 공통 축 (전극 페르미 준위 대비)</h3>
        ${svgHomoLumoAxis(hl)}
        <p class="muted small" style="margin:4px 0 0">막대 왼쪽 = HOMO, 오른쪽 = LUMO ·
          점선 = 전극 페르미 준위 근사 — 막대가 왼쪽 점선보다 오른쪽으로 넘으면 산화, 오른쪽 점선보다 왼쪽이면 환원 위험</p>`;
    }

    // 물성 지문 오버레이 레이더 (축 선택 가능)
    const series = chosen.map((j, i) => ({name: j.material.name, d: j.result.descriptors, idx: i}));
    table += `<h3 style="font-size:13px;color:var(--accent);margin:16px 0 4px">
        물성 지문 겹쳐보기 (축 선택 가능)</h3>
      <div id="cmp-axis-picker"></div>
      <div id="cmp-radar">${svgRadar(series)}</div>
      <p class="muted small" style="margin:4px 0 10px">
        저장된 PUBLISHED 결과 전체 범위로 정규화 · 바깥쪽일수록 스크리닝에 유리한 방향</p>
      <h3 style="font-size:13px;color:var(--accent);margin:16px 0 4px">
        전기화학 안정성 (선택 물질 비교)</h3>
      ${eswSection(chosen)}`;
    // 사용자가 고른 지표를 그래프로 (그래프 종류는 '표시 설정'에서 선택)
    let charts = "";
    for (const key of CMP_METRICS) {
      const {label: title, unit} = axisMeta(key);
      const entries = chosen
        .map((j, i) => ({name: j.material.name, v: j.result.descriptors[key], i}))
        .filter(e => typeof e.v === "number");
      if (entries.length < 2) continue;
      charts += `<div><h3 style="font-size:12.5px;color:var(--accent);margin:0 0 4px">
        ${esc(title)}${unit ? ` (${esc(unit)})` : ""}</h3>${svgMetricChart(entries, unit)}</div>`;
    }
    table += charts
      ? `<h3 style="font-size:13px;color:var(--accent);margin:16px 0 4px">선택한 지표 그래프</h3>
         <div class="grid-2" style="margin-bottom:14px">${charts}</div>`
      : `<p class="muted small" style="margin:16px 0 10px">
         그래프로 그릴 지표가 없습니다 — 위 '표시 설정'에서 지표를 켜거나, 아래 표에서 '그래프' 버튼을 누르세요.</p>`;

    const keys = [];
    for (const j of chosen) {
      for (const k of Object.keys(j.result.descriptors)) {
        if (k !== "potential_reference" && !keys.includes(k)) keys.push(k);
      }
    }
    table += `<h3 style="font-size:13px;color:var(--accent);margin:16px 0 4px">전체 값 표</h3>
      <p class="muted small" style="margin:0 0 6px">각 줄의 '그래프' 버튼을 누르면 그 지표가 위 그래프에 추가됩니다 ·
        칸 아래 미니 막대는 <b>그 줄 안에서의 상대 크기</b>(길수록 큰 값)이며, 위 그래프는 0을 기준으로 그립니다.</p>` +
      '<div class="scroll-x"><table class="kv-table" style="min-width:560px"><tr><th>지표</th>' +
      chosen.map((j, i) => `<th><span style="display:inline-block;width:8px;height:8px;border-radius:2px;
        background:var(--series-${(i % 8) + 1});margin-right:5px"></span>${esc(shortName(j.material.name, 18))}</th>`).join("") +
      "</tr>";
    for (const k of keys) {
      const {label, unit} = axisMeta(k);
      const vals = chosen.map(j => j.result.descriptors[k]);
      const nums = vals.filter(v => typeof v === "number");
      const on = CMP_METRICS.includes(k);
      const canChart = nums.length >= 2;
      const btn = canChart
        ? `<button class="btn ${on ? "primary" : ""}" data-cm-row="${esc(k)}" type="button"
             style="padding:1px 7px;font-size:10.5px;margin-right:6px"
             title="${on ? "그래프에서 빼기" : "그래프로 보기"}">그래프</button>`
        : "";
      const scale = CMP_TABLE_BARS && canChart ? rowScale(nums) : null;
      table += `<tr><th style="white-space:nowrap">${btn}${esc(label)}${unit ? ` (${esc(unit)})` : ""}</th>` +
        vals.map((v, i) => {
          if (typeof v !== "number") return `<td>${esc(cellText(v))}</td>`;
          let cell = `<span class="mono">${fmt(v)}</span>`;
          if (scale) {
            const w = (v - scale.lo) / (scale.hi - scale.lo) * 100;
            cell += `<div style="position:relative;height:5px;margin-top:3px;background:var(--grid);
              border-radius:3px;min-width:64px;max-width:150px"><div style="position:absolute;left:0;
              width:${w.toFixed(1)}%;top:0;bottom:0;border-radius:3px;
              background:var(--series-${(i % 8) + 1});opacity:${CMP_OPACITY}"></div></div>`;
          }
          return `<td>${cell}</td>`;
        }).join("") + "</tr>";
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
  renderMetricPicker(chosen, () => window.rbRenderCompare());
  if ($("cmp-axis-picker")) {
    const series = chosen.map((j, i) => ({name: j.material.name, d: j.result.descriptors, idx: i}));
    const redraw = () => {
      renderAxisPicker("cmp-axis-picker", redraw);
      $("cmp-radar").innerHTML = svgRadar(series);
    };
    redraw();
  }
  box.querySelectorAll("[data-cm-row]").forEach(b => b.addEventListener("click", () => {
    const msg = toggleCmpMetric(b.dataset.cmRow);
    if (msg) { alert(msg); return; }
    window.rbRenderCompare();
  }));
  box.querySelectorAll("[data-cmp]").forEach(b => b.addEventListener("click", () => {
    const id = b.dataset.cmp;
    COMPARE_SEL.has(id) ? COMPARE_SEL.delete(id) : COMPARE_SEL.add(id);
    window.rbRenderCompare();
  }));
};

/* ================= 건식 음극 바인더 스크리닝 ================= */

const VERDICT_CLASS = {"양호": "verdict-ok", "주의": "verdict-mid", "위험": "verdict-no"};
const PFAS_STYLE = {
  pfas: ["verdict-no", "PFAS 해당"],
  fluorinated: ["verdict-mid", "불소 함유"],
  pfas_free: ["verdict-ok", "PFAS-free"],
  unknown: ["muted", "판정 불가"],
};

function pfasBadge(pfas) {
  const [cls, short] = PFAS_STYLE[pfas?.status] || PFAS_STYLE.unknown;
  return `<span class="badge ${cls}" style="border:1px solid currentColor">${esc(short)}</span>`;
}

/** 결과 상세 맨 위에 붙는 바인더 적합성 스코어카드 */
function binderScorecard(rep) {
  const cls = VERDICT_CLASS[rep.overall] || "muted";
  let h = `<div class="card ${cls}" data-binder-scorecard
      style="margin:0 0 14px;border-left:4px solid currentColor">
    <div class="card-head" style="margin-bottom:8px">
      <h2 style="margin:0;color:var(--text-1)">건식 음극 바인더 적합성</h2>
      <span class="${cls}" style="font-weight:700;font-size:15px">
        ${esc(rep.overall || "판정 불가")}</span>
    </div>
    <p style="margin:0 0 10px">${pfasBadge(rep.pfas)} ${esc(rep.summary)}</p>`;

  if (rep.pfas?.matched?.length) {
    h += `<p class="muted small" style="margin:0 0 10px">검출된 구조: ${
      rep.pfas.matched.map(esc).join(" · ")} · 불소 원자 ${rep.pfas.n_fluorine}개</p>`;
  }

  if (rep.absolute?.length) {
    h += '<table class="kv-table" style="margin-bottom:10px">';
    for (const a of rep.absolute) {
      const ac = VERDICT_CLASS[a.verdict] || "muted";
      h += `<tr><th style="width:120px">${esc(a.axis)}</th>
        <td style="width:90px" class="${ac}"><b>${esc(a.verdict)}</b></td>
        <td><span class="mono">${fmt(a.value)}</span>
          <span class="muted small"> ${esc(a.unit || "")}</span>
          <div class="muted small">${esc(a.detail)}</div></td></tr>`;
    }
    h += "</table>";
  }

  // 평가되지 않은 축 — 통과와 구분해서 보여준다
  if (rep.unevaluated?.length) {
    h += '<table class="kv-table" style="margin-bottom:10px">';
    for (const u of rep.unevaluated) {
      h += `<tr><th style="width:120px">${esc(u.axis)}</th>
        <td style="width:90px" class="muted"><b>판정 보류</b></td>
        <td class="muted small">${esc(u.reason)}</td></tr>`;
    }
    h += "</table>";
  }

  // 음극별 통과 여부
  const red = (rep.absolute || []).find(a => a.per_anode);
  if (red) {
    h += '<div class="toolbar" style="margin:0 0 10px">'
      + '<span class="muted small">음극별 환원 안정성</span>'
      + red.per_anode.map(p => `<span class="badge ${p.stable ? "verdict-ok" : "verdict-no"}"
          style="border:1px solid currentColor">${esc(p.label)} ${p.potential_v} V
          ${p.stable ? "통과" : "위험"}</span>`).join("")
      + "</div>";
  }

  if (rep.relative?.length) {
    h += '<table class="kv-table" style="margin-bottom:10px">';
    for (const rel of rep.relative) {
      h += `<tr><th style="width:120px">${esc(rel.axis)}</th>
        <td style="width:90px" class="mono">${fmt(rel.value)}</td>
        <td class="muted small">${esc(rel.detail)}</td></tr>`;
    }
    h += "</table><p class=\"muted small\" style=\"margin:0 0 8px\">"
      + "위 네 축은 절대 기준이 없어 «후보 순위» 화면에서 후보끼리 비교해야 의미가 있습니다.</p>";
  }

  h += '<ul class="log-list" style="margin:0">'
    + (rep.notes || []).map(n => `<li>${esc(n)}</li>`).join("") + "</ul></div>";
  return h;
}

/* ---------- 바인더 후보군 화면 ---------- */
let BINDER_LIB = null;
const BINDER_SEL = new Set();

async function loadBinderLib() {
  if (BINDER_LIB) return BINDER_LIB;
  const res = await fetch("/api/binder/candidates");
  if (!res.ok) throw new Error("후보 목록을 불러오지 못했습니다.");
  BINDER_LIB = await res.json();
  return BINDER_LIB;
}

window.rbRenderBinder = async function () {
  const grid = $("bnd-grid");
  if (!grid) return;
  let lib;
  try {
    lib = await loadBinderLib();
  } catch (e) {
    grid.className = "empty small";
    grid.textContent = e.message;
    return;
  }

  // 계열 필터 채우기 (한 번만)
  const fam = $("bnd-family");
  if (fam && !fam.options.length) {
    fam.add(new Option("모든 계열", ""));
    for (const f of [...new Set(lib.candidates.map(c => c.family))]) fam.add(new Option(f, f));
    fam.onchange = () => window.rbRenderBinder();
    $("bnd-hide-pfas").onchange = () => window.rbRenderBinder();
  }
  // 정확도·구조 선택지 (PRESETS 재사용)
  const acc = $("bnd-accuracy");
  if (acc && !acc.options.length && PRESETS) {
    for (const k of Object.keys(PRESETS.accuracy)) acc.add(new Option(k, k));
    acc.value = "빠름";      // 스크리닝은 사전 선별이므로 빠름이 기본
    const st = $("bnd-structure");
    for (const s of PRESETS.structures) st.add(new Option(s, s));
    acc.onchange = updateBinderEstimate;
    st.onchange = updateBinderEstimate;
  }

  const famV = fam ? fam.value : "";
  const hide = $("bnd-hide-pfas")?.checked;
  const shown = lib.candidates.filter(c =>
    (!famV || c.family === famV) && !(hide && c.pfas.status === "pfas"));

  grid.className = "mol-grid";
  grid.innerHTML = shown.map(c => `
    <button class="mol-card ${BINDER_SEL.has(c.id) ? "selected" : ""}" data-bnd="${esc(c.id)}">
      <b>${esc(c.abbr)} ${c.reference ? "· 기준군" : ""}</b>
      <span>${pfasBadge(c.pfas)} <span class="small muted">${esc(c.family)}</span></span>
      <span class="small muted">${esc(c.name)}</span>
      <span class="mono small muted">${esc(c.smiles)}</span>
      <span class="small muted">${esc(c.note)}</span>
    </button>`).join("");
  grid.querySelectorAll("[data-bnd]").forEach(b => b.addEventListener("click", () => {
    const id = b.dataset.bnd;
    BINDER_SEL.has(id) ? BINDER_SEL.delete(id) : BINDER_SEL.add(id);
    window.rbRenderBinder();
  }));

  $("bnd-count").textContent = `${shown.length}종 표시 · ${BINDER_SEL.size}종 선택`;
  updateBinderEstimate();
};

function updateBinderEstimate() {
  const el = $("bnd-estimate");
  if (!el) return;
  const n = BINDER_SEL.size;
  const acc = $("bnd-accuracy")?.value || "빠름";
  // 실측 기준: '빠름' 단순 분자 약 30초, 지문 전체 계산은 그보다 훨씬 오래 걸린다
  const per = {"빠름": "수 분", "표준": "수십 분", "정밀": "수십 분 이상"}[acc] || "수 분";
  el.textContent = n
    ? `${n}종 × 후보당 ${per} — 접착·응집·BDE까지 계산하므로 전위만 구할 때보다 오래 걸립니다.`
    : "후보를 선택하세요.";
}

function wireBinderControls() {
  const on = (id, fn) => { const el = $(id); if (el) el.onclick = fn; };
  on("bnd-sel-free", async () => {
    const lib = await loadBinderLib();
    lib.candidates.filter(c => c.pfas.status === "pfas_free")
      .forEach(c => BINDER_SEL.add(c.id));
    window.rbRenderBinder();
  });
  on("bnd-sel-none", () => { BINDER_SEL.clear(); window.rbRenderBinder(); });

  // 후보 순위 화면의 선택 버튼
  on("bndr-all", () => {
    publishedJobs().forEach(j => BINDER_RANK_SEL.add(j.id));
    window.rbRenderBinderRank();
  });
  on("bndr-none", () => { BINDER_RANK_SEL.clear(); window.rbRenderBinderRank(); });

  on("bnd-check", async () => {
    const out = $("bnd-check-out");
    const smiles = $("bnd-smiles").value.trim();
    if (!smiles) { out.textContent = "SMILES를 입력하세요."; return; }
    out.textContent = "판정 중…";
    try {
      const res = await fetch("/api/binder/pfas", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({smiles}),
      });
      const p = await res.json();
      if (!res.ok) throw new Error(p.detail || "판정 실패");
      out.innerHTML = `${pfasBadge(p)} <b>${esc(p.label)}</b>
        <div class="muted small">${esc(p.note || "")}${
          p.matched?.length ? " · 검출: " + p.matched.map(esc).join(" · ") : ""}</div>`;
    } catch (e) { out.textContent = e.message; }
  });

  on("bnd-submit", async () => {
    const out = $("bnd-submit-out");
    if (!BINDER_SEL.size) { out.textContent = "후보를 선택하세요."; return; }
    const lib = await loadBinderLib();
    const chosen = lib.candidates.filter(c => BINDER_SEL.has(c.id));
    out.textContent = "제출 중…";
    try {
      const res = await fetch("/api/jobs", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          customMaterials: chosen.map(c => ({smiles: c.smiles, name: `${c.abbr} — ${c.name}`})),
          settings: {
            ...PRESETS.defaults,
            accuracy: $("bnd-accuracy").value,
            structure: $("bnd-structure").value,
            purpose: "건식 음극 바인더 스크리닝",
            referenceElectrode: "Li/Li+",
          },
        }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || "제출 실패");
      const n = (body.jobs || body.created || []).length || chosen.length;
      out.innerHTML = `<span class="verdict-ok">${n}건 제출 완료</span> —
        «DFT 계산 결과»에서 진행률을 확인하고, 끝나면 «후보 순위»에서 비교하세요.`;
      BINDER_SEL.clear();
      window.rbRenderBinder();
    } catch (e) { out.innerHTML = `<span class="verdict-no">${esc(e.message)}</span>`; }
  });
}

/* ---------- 후보 순위 화면 ---------- */
const BINDER_RANK_SEL = new Set();

window.rbRenderBinderRank = async function () {
  const picker = $("bndr-picker"), body = $("bndr-body");
  if (!picker) return;
  const jobs = publishedJobs();
  for (const id of [...BINDER_RANK_SEL]) if (!jobs.some(j => j.id === id)) BINDER_RANK_SEL.delete(id);

  if (!jobs.length) {
    picker.className = "empty small";
    picker.textContent = "완료된 계산이 없습니다. «바인더 후보군»에서 스크리닝을 제출하세요.";
    body.innerHTML = "";
    return;
  }
  picker.className = "mol-grid";
  picker.innerHTML = jobs.map(j => `
    <button class="mol-card ${BINDER_RANK_SEL.has(j.id) ? "selected" : ""}" data-bndr="${esc(j.id)}">
      <b>${esc(j.material.name)}</b>
      <span class="small muted">${esc(condLabel(j))}</span>
      <span class="mono small muted">${esc(j.id)}</span></button>`).join("");
  picker.querySelectorAll("[data-bndr]").forEach(b => b.addEventListener("click", () => {
    const id = b.dataset.bndr;
    BINDER_RANK_SEL.has(id) ? BINDER_RANK_SEL.delete(id) : BINDER_RANK_SEL.add(id);
    window.rbRenderBinderRank();
  }));
  $("bndr-count").textContent = `${BINDER_RANK_SEL.size} / ${jobs.length}건 선택`;

  if (!BINDER_RANK_SEL.size) {
    body.innerHTML = '<p class="muted small">결과를 선택하면 판정과 순위가 나타납니다.</p>';
    return;
  }
  body.innerHTML = '<p class="muted small">판정 중…</p>';
  try {
    const res = await fetch("/api/binder/rank", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ids: [...BINDER_RANK_SEL]}),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "판정 실패");
    body.innerHTML = binderRankHtml(data);
  } catch (e) {
    body.innerHTML = `<p class="verdict-no">${esc(e.message)}</p>`;
  }
};

function binderRankHtml(data) {
  const reps = data.reports;
  // 1) 게이트 + 절대 판정 요약표
  let h = `<h3 style="font-size:13px;color:var(--accent);margin:0 0 6px">
      1차 판정 — PFAS 게이트와 절대 기준</h3>
    <div class="scroll-x"><table class="kv-table" style="min-width:640px">
    <tr><th>후보</th><th>PFAS</th><th>환원 안정성</th><th>열 안정성</th><th>종합</th></tr>`;
  for (const r of reps) {
    const rep = r.report;
    const cell = axis => {
      const a = (rep.absolute || []).find(x => x.axis === axis);
      if (a) {
        return `<td class="${VERDICT_CLASS[a.verdict]}"><b>${esc(a.verdict)}</b>
          <div class="mono small">${fmt(a.value)} ${esc(a.unit || "")}</div></td>`;
      }
      // 값이 없는 것은 «통과»가 아니라 «판정 보류» — 사유를 툴팁으로 붙인다
      const u = (rep.unevaluated || []).find(x => x.axis === axis);
      return `<td class="muted small" title="${esc(u?.reason || "")}">판정 보류</td>`;
    };
    h += `<tr><th style="white-space:nowrap">${esc(r.material)}</th>
      <td>${pfasBadge(rep.pfas)}</td>${cell("환원 안정성")}${cell("열 안정성")}
      <td class="${VERDICT_CLASS[rep.overall] || "muted"}"><b>${esc(rep.overall || "—")}</b>
        <div class="muted small">${esc(rep.summary)}</div></td></tr>`;
  }
  h += "</table></div>";

  // 2) 상대 축 순위
  const ranks = data.ranks || {};
  const keys = Object.keys(ranks);
  if (keys.length) {
    h += `<h3 style="font-size:13px;color:var(--accent);margin:16px 0 6px">
      2차 비교 — 후보 간 상대 순위</h3><div class="grid-2">`;
    for (const k of keys) {
      const rk = ranks[k];
      h += `<div><h3 style="font-size:12.5px;color:var(--accent);margin:0 0 4px">
        ${esc(rk.axis)} <span class="muted small">(${
          rk.lower_is_better ? "작을수록 유리" : "클수록 유리"})</span></h3>
        <table class="kv-table">`;
      for (const o of rk.order) {
        h += `<tr><th style="width:34px">${o.rank}위</th>
          <td>${esc(o.material)}</td>
          <td class="mono" style="width:90px">${fmt(o.value)}</td></tr>`;
      }
      h += "</table></div>";
    }
    h += "</div>";
  } else {
    h += `<p class="muted small" style="margin-top:14px">
      상대 순위를 매기려면 같은 지표를 가진 결과가 2건 이상 필요합니다 —
      «물성 지문» 또는 «건식 음극 바인더 스크리닝» 목적으로 계산하세요.</p>`;
  }

  h += `<ul class="log-list" style="margin-top:12px">
    <li>PFAS 해당은 다른 축과 무관하게 탈락입니다 — 규제 요건이기 때문입니다.</li>
    <li>상대 순위는 대용 클러스터 모델 기반이라 같은 조건으로 계산한 후보끼리만 유효합니다.</li>
    <li>현행 표준(PTFE·PVDF)을 함께 계산하면 «기존 대비 얼마나 되는가»를 읽을 수 있습니다.</li>
    <li>피브릴화·기계 물성·집전체 접착은 분자 단위 DFT 범위 밖입니다.</li>
  </ul>`;
  return h;
}

/* ---------- Step 1 · 고분자 물성 카드 ---------- */

/** 계산값·문헌값·예측 불가를 한눈에 구분되게 그린다 */
function polymerCardHtml(card) {
  const g = card.glass_transition, d = card.dft || {};
  const row = (label, value, unit, kind, note) => `
    <tr><th style="width:150px">${esc(label)}</th>
      <td style="width:110px" class="mono">${value}<span class="muted small"> ${esc(unit || "")}</span></td>
      <td style="width:60px"><span class="badge ${
        kind === "문헌" ? "verdict-mid" : kind === "불가" ? "muted" : "verdict-ok"
      }" style="border:1px solid currentColor">${esc(kind)}</span></td>
      <td class="muted small">${esc(note || "")}</td></tr>`;
  const tgRow = () => g?.available
    ? row("유리전이온도 Tg", fmt(g.tg_c), "°C", "문헌",
          (g.name ? g.name + " · " : "") +
          (g.uncertain ? "문헌값 편차가 큼 — " : "") + (g.note || "실측 인용"))
    : row("유리전이온도 Tg", "—", "", "불가", g?.note || "");

  // 반복 단위를 확정하지 못하면 구조 기반 물성은 전부 무효 — 다만 문헌값은 남긴다
  if (card.errors?.length || !card.computed) {
    return `<h3 style="font-size:13px;color:var(--accent);margin:12px 0 6px">
        고분자 물성 카드 — ${esc(card.name || card.smiles)}</h3>
      <p class="verdict-no small">${card.errors.map(esc).join(" · ")}</p>
      <div class="scroll-x"><table class="kv-table" style="min-width:620px">
      ${tgRow()}</table></div>`;
  }

  const c = card.computed;
  let h = `<h3 style="font-size:13px;color:var(--accent);margin:12px 0 6px">
      고분자 물성 카드 — ${esc(card.name || card.smiles)}</h3>
    <div class="scroll-x"><table class="kv-table" style="min-width:620px">`;
  h += row("반복 단위", `<span class="mono">${esc(c.repeat_unit_smiles)}</span>`, "",
           c.repeat_unit_source === "등록" ? "문헌" : "계산",
           `${c.repeat_unit_source} · ${c.repeat_unit_note || ""} `
           + "(* 는 이웃 단위와 붙는 자리)");
  h += row("반복 단위 분자량", fmt(c.repeat_unit_mw), "g/mol", "계산", "");
  h += row("van der Waals 부피", fmt(c.vdw_volume_cm3), "cm³/mol", "계산",
           "Zhao 법 · 반복 단위 기준 (PE 20.8 vs 문헌 20.5)");
  h += row("몰 부피", fmt(c.molar_volume_cm3), "cm³/mol", "계산", "M ÷ ρ");
  h += row("밀도 ρ", fmt(c.density_g_cm3), "g/cm³", "계산",
           "참조 47종 중첩 교차검증 평균오차 0.041 g/cm³");
  h += row("용해도 파라미터 δ", fmt(c.solubility_parameter_mpa05), "MPa^0.5", "계산",
           "참조 47종 중첩 교차검증 평균오차 1.8 MPa^0.5");
  h += row("응집 에너지 밀도 CED", fmt(c.ced_j_cm3), "J/cm³", "계산", "δ² 에서 유도");
  h += row("회전 가능 결합", `${c.rotatable_bonds} (밀도 ${fmt(c.rotatable_density)})`,
           "", "계산", "사슬 유연성 대리 지표 — 구조에서 직접 셈");

  h += tgRow();

  if (d.ced_j_cm3 != null) {
    h += row("CED (DFT 경로)", fmt(d.ced_j_cm3), "J/cm³", "계산",
             `이량체 결합 에너지 기반 · δ ${fmt(d.solubility_parameter_mpa05)} — ` +
             `구조 회귀와 차이 ${fmt(d.delta_vs_structure)} MPa^0.5`);
  }
  h += "</table></div>";

  if (c.warnings?.length) {
    h += `<ul class="log-list" style="margin-top:8px">${
      c.warnings.map(w => `<li class="verdict-mid">${esc(w)}</li>`).join("")}</ul>`;
  }
  h += `<p class="muted small" style="margin:8px 0 0">
    <b>계산</b> = 교차검증으로 오차를 측정한 값 ·
    <b>문헌</b> = 예측하지 않고 실측값 인용 ·
    <b>불가</b> = 신뢰할 수 없어 값을 내지 않음.
    Tg는 참조 47종·연결성 지수까지 넣어도 중첩 교차검증 오차 61.6 K(최대 581 K)로,
    참조셋 Tg 표준편차 89 K 대비 개선이 작아 예측하지 않습니다.</p>`;
  return h;
}

function wirePolymerCard() {
  const btn = $("bnd-card");
  if (!btn) return;
  btn.onclick = async () => {
    const out = $("bnd-card-out");
    const smiles = $("bnd-smiles").value.trim();
    if (!smiles) { out.innerHTML = '<p class="small">SMILES를 입력하세요.</p>'; return; }
    out.innerHTML = '<p class="muted small">계산 중…</p>';
    try {
      const res = await fetch("/api/polymer/card", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({smiles, name: $("bnd-name").value.trim() || null}),
      });
      const card = await res.json();
      if (!res.ok) throw new Error(card.detail || "물성 카드 생성 실패");
      out.innerHTML = polymerCardHtml(card);
    } catch (e) {
      out.innerHTML = `<p class="verdict-no small">${esc(e.message)}</p>`;
    }
  };
}

/* ================= 사슬 길이 수렴 (Step 1 · L3) ================= */

let CHAIN_SERIES = null;   // 선택한 계열 id

/** 물성값의 n 의존성 곡선 — 수렴하면 초록, 아니면 앰버. 점선은 외삽 극한값 */
function svgConvergence(prop) {
  const pts = prop.points || [];
  if (pts.length < 2) return "";
  const W = 300, H = 130, L = 46, R = 12, T = 12, B = 26;
  const ns = pts.map(p => p.n), vs = pts.map(p => p.value);
  const limit = prop.extrapolation?.limit;
  const all = limit != null ? vs.concat([limit]) : vs;
  let lo = Math.min(...all), hi = Math.max(...all);
  if (hi - lo < 1e-9) { lo -= 0.5; hi += 0.5; }
  const pad = (hi - lo) * 0.15; lo -= pad; hi += pad;
  const nMax = Math.max(...ns), nMin = Math.min(...ns);
  const x = n => L + (nMax === nMin ? 0.5 : (n - nMin) / (nMax - nMin)) * (W - L - R);
  const y = v => T + (hi - v) / (hi - lo) * (H - T - B);
  const col = prop.converged ? "var(--ok)" : "var(--pin)";

  let sv = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:320px" role="img">`;
  // 외삽 극한값 기준선
  if (limit != null) {
    sv += `<line x1="${L}" y1="${y(limit)}" x2="${W - R}" y2="${y(limit)}"
      class="gridline" stroke-dasharray="4 3" />
      <text x="${W - R}" y="${y(limit) - 3}" class="value-label" text-anchor="end"
        >극한 ${fmt(limit)}</text>`;
  }
  sv += `<polyline points="${pts.map(p => `${x(p.n)},${y(p.value)}`).join(" ")}"
    fill="none" stroke="${col}" stroke-width="2" />`;
  for (const p of pts) {
    sv += `<circle cx="${x(p.n)}" cy="${y(p.value)}" r="4" fill="${col}"
        ><title>n=${p.n}: ${fmt(p.value)}</title></circle>
      <text x="${x(p.n)}" y="${H - 8}" class="axis-label" text-anchor="middle">n=${p.n}</text>`;
  }
  sv += `<text x="2" y="${y(vs[0])}" class="value-label">${fmt(vs[0])}</text>
    <text x="2" y="${y(vs[vs.length - 1])}" class="value-label">${fmt(vs[vs.length - 1])}</text></svg>`;
  return sv;
}

function chainAnalysisHtml(data) {
  const md = data.minimum_defined || {};
  let h = `<h3 style="font-size:13px;color:var(--accent);margin:0 0 6px">
      ${esc(data.base.name)} — 판정에 쓴 사슬 길이 n = ${data.lengths.join(" · ")}
      ${(data.excluded_lengths || []).length
        ? `<span class="muted small">(계산 ${data.all_lengths.join(" · ")})</span>` : ""}</h3>`;

  h += `<p class="${data.n_converged === data.n_judged ? "verdict-ok" : "verdict-mid"}"
      style="margin:0 0 4px"><b>판정 물성 ${data.n_judged}개 중
      ${data.n_converged}개 수렴</b></p>`;
  if (data.not_converged?.length) {
    h += `<p class="muted small" style="margin:0 0 8px">미수렴: ${
      data.not_converged.map(k => esc(axisMeta(k).label)).join(" · ")}</p>`;
  }
  if (data.exclusion_note) {
    h += `<p class="verdict-mid small" style="margin:0 0 6px">
      n=${(data.excluded_lengths || []).join(", ")} 제외 — ${esc(data.exclusion_note)}</p>`;
  }
  if (data.warning) {
    h += `<p class="verdict-mid small" style="margin:0 0 6px">${esc(data.warning)}</p>`;
  }
  if (md.note) {
    h += `<p class="muted small" style="margin:0 0 10px">${esc(md.note)}</p>`;
  }

  // 수렴한 것 → 미수렴 → 크기값 순으로 정렬해 중요한 것부터 보이게 한다
  const rank = p => p.status === "not_converged" ? 0 : p.status === "converged" ? 1 : 2;
  const props = [...data.properties].sort((a, b) => rank(a) - rank(b));

  let cards = "";
  for (const p of props) {
    if (p.status === "insufficient") continue;
    const meta = axisMeta(p.key);
    const badge = p.status === "converged"
      ? '<span class="badge verdict-ok" style="border:1px solid currentColor">수렴</span>'
      : p.status === "not_converged"
      ? '<span class="badge verdict-mid" style="border:1px solid currentColor">미수렴</span>'
      : '<span class="badge muted" style="border:1px solid currentColor">크기값</span>';
    cards += `<div><h3 style="font-size:12.5px;color:var(--accent);margin:0 0 3px">
        ${esc(meta.label)}${meta.unit ? ` (${esc(meta.unit)})` : ""} ${badge}</h3>
      ${svgConvergence(p)}
      <p class="muted small" style="margin:2px 0 0">${esc(p.note || "")}</p></div>`;
  }
  h += `<div class="grid-2">${cards}</div>`;
  h += `<ul class="log-list" style="margin-top:12px">
    <li>수렴 판정은 «마지막 두 길이의 변화 &lt; 임계값» 기준입니다.</li>
    <li>극한값은 값 = a + b/n 선형 외삽의 절편 — 말단기 효과가 1/n 으로 준다는 표준 가정입니다.</li>
    <li>미수렴 물성은 후보 간 비교에 쓰지 마세요 — 사슬 길이 차이가 순위를 뒤집을 수 있습니다.</li>
    <li>전자 에너지처럼 사슬에 비례하는 «크기값»은 수렴 대상이 아닙니다.</li>
  </ul>`;
  return h;
}

window.rbRenderChain = async function () {
  const box = $("chn-series");
  if (!box) return;
  const acc = $("chn-accuracy");
  if (acc && !acc.options.length && PRESETS) {
    for (const k of Object.keys(PRESETS.accuracy)) acc.add(new Option(k, k));
    acc.value = "빠름";
  }
  try {
    const res = await fetch("/api/convergence/series");
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "계열 목록을 불러오지 못했습니다.");
    if (!data.series.length) {
      box.className = "empty small";
      box.textContent = "등록된 계열이 없습니다. 위에서 반복 단위 SMILES로 계열을 제출하세요.";
      $("chn-body").innerHTML = "";
      return;
    }
    box.className = "mol-grid";
    box.innerHTML = data.series.map(g => `
      <button class="mol-card ${CHAIN_SERIES === g.series_id ? "selected" : ""}"
        data-chn="${esc(g.series_id)}">
        <b>${esc(g.base_name)}</b>
        <span class="small ${g.done === g.total ? "verdict-ok" : "muted"}">
          ${g.done}/${g.total}건 완료 · n = ${g.jobs.map(x => x.n).join(", ")}</span>
        <span class="mono small muted">${esc(g.series_id)}</span></button>`).join("");
    box.querySelectorAll("[data-chn]").forEach(b => b.addEventListener("click", () => {
      CHAIN_SERIES = b.dataset.chn;
      window.rbRenderChain();
    }));
  } catch (e) {
    box.className = "empty small";
    box.textContent = e.message;
    return;
  }

  const body = $("chn-body");
  if (!CHAIN_SERIES) {
    body.innerHTML = '<p class="muted small">계열을 선택하면 수렴 판정이 나타납니다.</p>';
    return;
  }
  body.innerHTML = '<p class="muted small">판정 중…</p>';
  try {
    const res = await fetch(
      `/api/convergence/analyze?series_id=${encodeURIComponent(CHAIN_SERIES)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "판정 실패");
    body.innerHTML = chainAnalysisHtml(data);
  } catch (e) {
    body.innerHTML = `<p class="verdict-mid small">${esc(e.message)}</p>`;
  }
};

function wireChainControls() {
  const on = (id, fn) => { const el = $(id); if (el) el.onclick = fn; };
  const lengths = () => $("chn-lengths").value.split(",")
    .map(s => parseInt(s.trim(), 10)).filter(n => n >= 1 && n <= 12);
  const payload = () => ({
    smiles: $("chn-smiles").value.trim(),
    name: $("chn-name").value.trim() || null,
    lengths: lengths(),
    settings: {...PRESETS.defaults, accuracy: $("chn-accuracy").value,
               purpose: "전자구조 + 산화/환원 전위", referenceElectrode: "Li/Li+"},
  });

  on("chn-preview", async () => {
    const out = $("chn-preview-out");
    if (!$("chn-smiles").value.trim()) { out.innerHTML = '<p class="small">SMILES를 입력하세요.</p>'; return; }
    out.innerHTML = '<p class="muted small">확인 중…</p>';
    try {
      const res = await fetch("/api/convergence/preview", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload()),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || "미리보기 실패");
      out.innerHTML = `<table class="kv-table" style="margin-top:8px">
        <tr><th>n</th><th>올리고머 SMILES</th><th>원자 수</th><th></th></tr>` +
        d.series.map(e => `<tr><th>${e.n}</th>
          <td class="mono small">${esc(e.smiles || e.error || "—")}</td>
          <td class="mono">${e.atom_count ?? "—"}</td>
          <td class="${e.over_limit ? "verdict-no" : "muted"} small">${
            e.over_limit ? `상한 ${d.max_atoms} 초과 — 제외됨` : ""}</td></tr>`).join("") +
        `</table><p class="muted small" style="margin:6px 0 0">${
          esc(d.minimum_defined.note || "")}</p>` +
        (d.exclusion_note ? `<p class="verdict-mid small" style="margin:4px 0 0">
          n=1 제외 예정 — ${esc(d.exclusion_note)}</p>` : "") +
        (d.extrapolation_available ? "" : `<p class="verdict-mid small" style="margin:4px 0 0">
          판정에 쓸 길이가 ${d.judged_lengths.length}개(n = ${d.judged_lengths.join(", ")})뿐이라
          무한 사슬 외삽은 나오지 않습니다 — 길이를 3개 이상 남기세요.</p>`);
    } catch (e) { out.innerHTML = `<p class="verdict-no small">${esc(e.message)}</p>`; }
  });

  on("chn-submit", async () => {
    const out = $("chn-submit-out");
    if (!$("chn-smiles").value.trim()) { out.textContent = "SMILES를 입력하세요."; return; }
    out.textContent = "제출 중…";
    try {
      const res = await fetch("/api/convergence/submit", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload()),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || "제출 실패");
      CHAIN_SERIES = d.series_id;
      out.innerHTML = `<span class="verdict-ok">${d.jobs.length}건 제출 완료</span>
        — 계열 ${esc(d.series_id)}. 계산이 끝나면 아래에서 수렴 판정이 나타납니다.`;
      window.rbRenderChain();
    } catch (e) { out.innerHTML = `<span class="verdict-no">${esc(e.message)}</span>`; }
  });

  on("chn-refresh", () => window.rbRenderChain());
}

/* ================= 기계 물성 · 사용 온도 상태 (Step 2) ================= */

/** 상태별 색 — 확정이면 초록/회색, 보류면 앰버 */
function mechStateClass(state, confident) {
  if (!confident) return "verdict-mid";
  if (state === "유리질") return "verdict-ok";
  if (state === "용융" || state === "분해") return "verdict-no";
  return "muted";
}

function mechStatesHtml(data) {
  const rows = data.rows || [];
  let h = `<p class="small" style="margin:0 0 8px">사용 온도
    <b>${fmt(data.temperature_c)} °C</b> 기준 — 판정 근거는 Tg·Tm·분해 온도입니다.</p>
    <div class="scroll-x"><table class="kv-table" style="min-width:720px">
    <tr><th style="width:170px">후보</th><th style="width:110px">상태</th>
      <th style="width:60px">Tg</th><th style="width:60px">Tm</th>
      <th style="width:60px">분해</th><th>근거</th></tr>`;
  for (const r of rows) {
    h += `<tr><th>${esc(r.name)}</th>
      <td><span class="badge ${mechStateClass(r.state, r.confident)}"
        style="border:1px solid currentColor">${esc(r.state)}</span></td>
      <td class="mono small">${r.tg_c ?? "—"}</td>
      <td class="mono small">${r.tm_c ?? "—"}</td>
      <td class="mono small">${r.decomp_c ?? "—"}</td>
      <td class="muted small">${esc(r.note || "")}</td></tr>`;
  }
  h += `</table></div>`;
  const f = data.refusal;
  if (f) {
    h += `<p class="verdict-mid small" style="margin:10px 0 0"><b>탄성 상수는 예측하지 않습니다.</b>
      ${esc(f.note)}</p>
      <div class="scroll-x"><table class="kv-table" style="min-width:420px;margin-top:6px">
      <tr><th style="width:130px">목표</th><th style="width:110px">중첩 교차검증</th>
        <th style="width:110px">평균값 찍기</th><th>판정</th></tr>` +
      f.targets.map(t => `<tr><th>${esc(t.key)}</th>
        <td class="mono">${t.nested_cv} ${esc(t.unit || "")}</td>
        <td class="mono">${t.mean_baseline}</td>
        <td class="verdict-no small">짐</td></tr>`).join("") +
      `</table></div>`;
  }
  return h;
}

function mechCardHtml(card) {
  const s = card.state || {}, lit = card.literature || {}, d = card.derived;
  let h = `<h3 style="font-size:13px;color:var(--accent);margin:10px 0 6px">
      ${esc(card.name || card.smiles)} — ${fmt(card.temperature_c)} °C</h3>
    <p><span class="badge ${mechStateClass(s.state, s.confident)}"
      style="border:1px solid currentColor">${esc(s.state || "—")}</span>
      <span class="muted small"> ${esc(s.note || "")}</span></p>`;
  if (lit.available && d) {
    h += `<div class="scroll-x"><table class="kv-table" style="min-width:520px">
      <tr><th style="width:170px">영률 E</th><td class="mono">${fmt(d.e_gpa)} GPa</td>
        <td class="muted small">문헌 (${esc(lit.confidence)})</td></tr>
      <tr><th>푸아송비 ν</th><td class="mono">${fmt(d.poisson)}</td>
        <td class="muted small">문헌</td></tr>
      <tr><th>체적 탄성률 K</th><td class="mono">${fmt(d.bulk_gpa)} GPa</td>
        <td class="muted small">관계식 — 정확</td></tr>
      <tr><th>전단 탄성률 G</th><td class="mono">${fmt(d.shear_gpa)} GPa</td>
        <td class="muted small">관계식 — 정확</td></tr>
      ${d.longitudinal_wave_m_s ? `<tr><th>종파 음속</th>
        <td class="mono">${fmt(d.longitudinal_wave_m_s)} m/s</td>
        <td class="muted small">ρ ${fmt(d.density_g_cm3)} g/cm³ 기준</td></tr>
      <tr><th>횡파 음속</th><td class="mono">${fmt(d.shear_wave_m_s)} m/s</td>
        <td class="muted small">Rao·Hartmann 몰함수가 쓰는 양</td></tr>` : ""}
      </table></div>`;
  } else {
    h += `<p class="muted small">${esc(lit.note || "문헌 탄성 상수 없음")}</p>`;
  }
  if (card.rubbery) {
    h += `<p class="small" style="margin-top:8px">고무질 탄성률
      <b class="mono">${fmt(card.rubbery.e_mpa)} MPa</b>
      <span class="muted"> — ${esc(card.rubbery.basis)}</span></p>`;
  }
  if (card.errors?.length) {
    h += card.errors.map(e =>
      `<p class="verdict-mid small" style="margin:6px 0 0">${esc(e)}</p>`).join("");
  }
  return h;
}

window.rbRenderMech = async function () {
  const out = $("mch-states");
  if (!out || out.dataset.loaded) return;
  out.dataset.loaded = "1";
  await mechRunStates();
};

async function mechRunStates() {
  const out = $("mch-states");
  out.innerHTML = '<p class="muted small">판정 중…</p>';
  try {
    const res = await fetch("/api/mechanical/states", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({smiles: "C=C", temperature_c: Number($("mch-temp").value)}),
    });
    const d = await res.json();
    if (!res.ok) throw new Error(d.detail || "판정 실패");
    out.innerHTML = mechStatesHtml(d);
  } catch (e) { out.innerHTML = `<p class="verdict-no small">${esc(e.message)}</p>`; }
}

function wireMechControls() {
  const on = (id, fn) => { const el = $(id); if (el) el.onclick = fn; };
  on("mch-run", mechRunStates);
  on("mch-rt", () => { $("mch-temp").value = 25; mechRunStates(); });
  on("mch-dry", () => { $("mch-temp").value = 180; mechRunStates(); });

  on("mch-card", async () => {
    const box = $("mch-card-out");
    const smiles = $("mch-smiles").value.trim();
    if (!smiles) { box.innerHTML = '<p class="small">SMILES를 입력하세요.</p>'; return; }
    box.innerHTML = '<p class="muted small">판정 중…</p>';
    try {
      const me = parseFloat($("mch-me").value);
      const res = await fetch("/api/mechanical/card", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({smiles, name: $("mch-name").value.trim() || null,
                              temperature_c: Number($("mch-temp").value),
                              entanglement_mw: Number.isFinite(me) ? me : null}),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || "판정 실패");
      box.innerHTML = mechCardHtml(d);
    } catch (e) { box.innerHTML = `<p class="verdict-no small">${esc(e.message)}</p>`; }
  });

  on("mch-conv", async () => {
    const box = $("mch-conv-out");
    box.innerHTML = '<p class="muted small">환산 중…</p>';
    try {
      const res = await fetch("/api/mechanical/elastic", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({e_gpa: Number($("mch-e").value),
                              poisson: Number($("mch-nu").value),
                              density_g_cm3: Number($("mch-rho").value)}),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || "환산 실패");
      box.innerHTML = `<div class="scroll-x"><table class="kv-table" style="min-width:460px">` +
        [["체적 탄성률 K", d.bulk_gpa, "GPa"], ["전단 탄성률 G", d.shear_gpa, "GPa"],
         ["종탄성률 K+4G/3", d.longitudinal_gpa, "GPa"],
         ["종파 음속", d.longitudinal_wave_m_s, "m/s"],
         ["횡파 음속", d.shear_wave_m_s, "m/s"]]
          .filter(r => r[1] != null)
          .map(([k, v, u]) => `<tr><th style="width:170px">${esc(k)}</th>
            <td class="mono">${fmt(v)}<span class="muted small"> ${esc(u)}</span></td></tr>`)
          .join("") + `</table></div>`;
    } catch (e) { box.innerHTML = `<p class="verdict-no small">${esc(e.message)}</p>`; }
  });
}

/* ============ ESW 진단: 「왜 이 판정인가」를 구조까지 되짚어 보여준다 ============ */

// 열어 둔 진단 패널 — 비교 화면이 2초마다 다시 그려져도 살아남아야 한다
let ESW_DIAG = null;   // {jobId, electrode, html}

/** 포함 관계 그림 — 전극 구동 «범위»가 물질 ESW 안에 들어오는지 한눈에 */
function svgContainment(d) {
  const red = d.reduction_potential_v, ox = d.oxidation_potential_v;
  const c = d.containment, w = c.window;
  const lo = Math.min(red, w.low, 0) - 0.6, hi = Math.max(ox, w.high) + 0.6;
  const W = 780, H = 176, L = 96, R = 26;
  const x = v => L + (v - lo) / (hi - lo) * (W - L - R);
  const safe = !c.fails.length;
  let s = `<svg viewBox="0 0 ${W} ${H}" class="esw-chart" role="img"
    aria-label="전극 구동 범위와 안정 창의 포함 관계">`;

  // 눈금
  const step = (hi - lo) > 8 ? 2 : (hi - lo) > 4 ? 1 : 0.5;
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
    s += `<line x1="${x(v)}" y1="26" x2="${x(v)}" y2="${H - 40}" stroke="var(--grid)"/>
      <text x="${x(v)}" y="${H - 24}" font-size="10.5" text-anchor="middle"
        fill="var(--muted)">${(+v.toFixed(2))}</text>`;
  }
  s += `<text x="${(L + W) / 2}" y="${H - 6}" font-size="11" text-anchor="middle"
    fill="var(--muted)">전위 (V vs Li/Li⁺) — 왼쪽일수록 환원되기 쉬움</text>`;

  // 물질의 ESW 띠 (안정 구간)
  s += `<text x="${L - 8}" y="62" font-size="11.5" text-anchor="end"
      fill="var(--text-1)">이 물질의 ESW</text>
    <rect x="${x(red)}" y="46" width="${Math.max(2, x(ox) - x(red))}" height="22" rx="5"
      fill="var(--accent)" fill-opacity="0.16" stroke="var(--accent)"/>
    <text x="${x(red) - 4}" y="61" font-size="10" text-anchor="end"
      fill="var(--text-2)">${fmt(red)}</text>
    <text x="${x(ox) + 4}" y="61" font-size="10" fill="var(--text-2)">${fmt(ox)}</text>`;

  // 전극 구동 범위 띠
  const ey = 96, ew = Math.max(3, x(w.high) - x(w.low));
  s += `<text x="${L - 8}" y="${ey + 15}" font-size="11.5" text-anchor="end"
      fill="var(--text-1)">${esc(w.label)} 구동</text>
    <rect x="${x(w.low)}" y="${ey}" width="${ew}" height="22" rx="5"
      fill="${safe ? "var(--ok)" : "var(--danger)"}" fill-opacity="0.22"
      stroke="${safe ? "var(--ok)" : "var(--danger)"}"/>
    <text x="${x(w.high) + 5}" y="${ey + 15}" font-size="10"
      fill="var(--text-2)">${w.low}~${w.high} V</text>`;

  // 벗어난 구간을 붉게 — 「어디가 왜 문제인가」가 이 부분이다
  for (const f of c.fails) {
    if (f.side === "환원") {
      const x0 = x(w.low), x1 = x(Math.min(red, w.high));
      s += `<rect x="${x0}" y="${ey - 3}" width="${Math.max(2, x1 - x0)}" height="28"
          fill="var(--danger)" fill-opacity="0.30"/>
        <line x1="${x0}" y1="${ey + 34}" x2="${x1}" y2="${ey + 34}"
          stroke="var(--danger)" stroke-width="1.5"/>
        <text x="${(x0 + x1) / 2}" y="${ey + 48}" font-size="10.5" text-anchor="middle"
          fill="var(--danger)">환원 구간 ${f.gap_v} V</text>`;
    } else {
      const x0 = x(Math.max(ox, w.low)), x1 = x(w.high);
      s += `<rect x="${x0}" y="${ey - 3}" width="${Math.max(2, x1 - x0)}" height="28"
          fill="var(--danger)" fill-opacity="0.30"/>
        <text x="${(x0 + x1) / 2}" y="${ey + 48}" font-size="10.5" text-anchor="middle"
          fill="var(--danger)">산화 구간 ${f.gap_v} V</text>`;
    }
  }
  if (safe) {
    s += `<text x="${x((w.low + w.high) / 2)}" y="${ey + 44}" font-size="10.5"
      text-anchor="middle" fill="var(--ok)">ESW 안에 완전히 들어옴</text>`;
  }
  return s + "</svg>";
}

/** EA 도약 — 수직 → 단열 → ΔG 로 가며 판정이 뒤집히는 지점을 드러낸다 */
function svgEaStages(d) {
  const st = d.ea_stages?.steps || [];
  if (st.length < 2) return "";
  const w = d.containment.window;
  const vs = st.map(s => s.reduction_v);
  const lo = Math.min(...vs, w.low) - 0.5, hi = Math.max(...vs, w.high) + 0.5;
  const W = 780, H = 64 + 42 * st.length, L = 118, R = 30;
  const x = v => L + (v - lo) / (hi - lo) * (W - L - R);
  let s = `<svg viewBox="0 0 ${W} ${H}" class="esw-chart" role="img"
    aria-label="전자 친화도 단계별 환원 전위">`;
  // 흑연 구동 범위 띠 — 어느 단계에서 이 띠를 넘는지가 핵심
  s += `<rect x="${x(w.low)}" y="24" width="${Math.max(3, x(w.high) - x(w.low))}"
      height="${H - 58}" fill="var(--danger)" fill-opacity="0.10"/>
    <line x1="${x(w.high)}" y1="24" x2="${x(w.high)}" y2="${H - 34}"
      stroke="var(--danger)" stroke-dasharray="4 3"/>
    <text x="${x(w.high) + 4}" y="18" font-size="10" fill="var(--danger)"
      >${esc(w.label)} 상단 ${w.high} V</text>`;
  st.forEach((p, i) => {
    const y = 46 + i * 42, over = p.reduction_v > w.high;
    const col = over ? "var(--danger)" : p.reduction_v >= w.low ? "var(--pin)" : "var(--ok)";
    s += `<text x="${L - 8}" y="${y + 4}" font-size="11.5" text-anchor="end"
        fill="var(--text-1)">${esc(p.label)}</text>
      <circle cx="${x(p.reduction_v)}" cy="${y}" r="6" fill="${col}"/>
      <text x="${x(p.reduction_v)}" y="${y - 11}" font-size="10.5" text-anchor="middle"
        fill="${col}">${fmt(p.reduction_v)} V</text>`;
    if (i > 0) {
      const prev = st[i - 1];
      s += `<line x1="${x(prev.reduction_v)}" y1="${y - 42 + 8}" x2="${x(p.reduction_v)}"
          y2="${y - 8}" stroke="var(--muted)" stroke-width="1.5"
          marker-end="url(#eaArrow)"/>
        <text x="${(x(prev.reduction_v) + x(p.reduction_v)) / 2}" y="${y - 20}"
          font-size="10" text-anchor="middle" fill="var(--muted)">+${p.delta_ev} eV</text>`;
    }
  });
  s += `<defs><marker id="eaArrow" viewBox="0 0 8 8" refX="6" refY="4"
      markerWidth="6" markerHeight="6" orient="auto">
      <path d="M0,0 L8,4 L0,8 z" fill="var(--muted)"/></marker></defs>
    <text x="${(L + W) / 2}" y="${H - 8}" font-size="11" text-anchor="middle"
      fill="var(--muted)">환원 전위 (V vs Li/Li⁺) — 붉은 띠 안·오른쪽이면 환원됨</text></svg>`;
  return s;
}

/** LUMO 사다리 — 「LUMO가 낮다」가 무엇에 비해 낮은지 보여준다 */
function svgLumoLadder(d) {
  if (d.lumo_ev == null) return "";
  const refs = (d.lumo_reference || []).map(r => ({...r}));
  const all = [...refs.map(r => r.lumo_ev), d.lumo_ev];
  const lo = Math.min(...all) - 0.5, hi = Math.max(...all) + 0.5;
  const W = 780, H = 150, L = 190, R = 20;
  const y = v => H - 40 - (v - lo) / (hi - lo) * (H - 74);
  let s = `<svg viewBox="0 0 ${W} ${H}" class="esw-chart" role="img"
    aria-label="LUMO 준위 비교">
    <text x="8" y="16" font-size="11" fill="var(--muted)">LUMO (eV) — 낮을수록 전자를 받기 쉬움</text>`;
  for (const r of refs) {
    s += `<line x1="${L}" y1="${y(r.lumo_ev)}" x2="${W - R}" y2="${y(r.lumo_ev)}"
        stroke="var(--grid)" stroke-dasharray="4 3"/>
      <text x="${L - 8}" y="${y(r.lumo_ev) + 4}" font-size="10.5" text-anchor="end"
        fill="var(--muted)">${esc(r.label)}</text>
      <text x="${W - R}" y="${y(r.lumo_ev) - 3}" font-size="9.5" text-anchor="end"
        fill="var(--muted)">${r.lumo_ev}${r.reduction_v != null
          ? ` (E_red ${r.reduction_v > 0 ? "+" : ""}${r.reduction_v} V)` : ""}</text>`;
  }
  s += `<line x1="${L}" y1="${y(d.lumo_ev)}" x2="${W - R}" y2="${y(d.lumo_ev)}"
      stroke="var(--accent)" stroke-width="2.5"/>
    <text x="${L - 8}" y="${y(d.lumo_ev) + 4}" font-size="11.5" text-anchor="end"
      fill="var(--accent)" font-weight="600">${esc(d.name || "이 물질")}</text>
    <text x="${W - R}" y="${y(d.lumo_ev) - 4}" font-size="10.5" text-anchor="end"
      fill="var(--accent)" font-weight="600">${fmt(d.lumo_ev)} eV</text>`;
  return s + "</svg>";
}

/** 인과 사슬 — 구조에서 판정까지 왜 그렇게 되는지 */
function chainHtml(d) {
  const bad = d.containment?.verdict !== "안정";
  return `<div class="scroll-x"><table class="kv-table" style="min-width:660px">
    <tr><th style="width:34px"></th><th style="width:140px">단계</th>
      <th style="width:150px">값</th><th style="width:58px">근거</th><th>설명</th></tr>` +
    d.chain.map((c, i) => `<tr>
      <td class="mono muted small">${i < d.chain.length - 1 ? c.step + " ↓" : c.step}</td>
      <th>${esc(c.label)}</th>
      <td class="mono ${c.label === "판정" ? (bad ? "verdict-no" : "verdict-ok") : ""}">${
        c.value == null ? "—" : esc(String(typeof c.value === "number" ? fmt(c.value) : c.value))
      }<span class="muted small"> ${esc(c.unit || "")}</span></td>
      <td><span class="badge ${c.measured ? "verdict-ok" : "muted"}"
        style="border:1px solid currentColor">${c.measured ? "계산" : "해석"}</span></td>
      <td class="muted small">${esc(c.note || "")}</td></tr>`).join("") +
    `</table></div>`;
}

function eswDiagnoseHtml(d) {
  if (!d.available) {
    return `<p class="verdict-mid small">${esc(d.note || "진단할 수 없습니다.")}</p>`;
  }
  const c = d.containment, bad = c.verdict !== "안정";
  let h = `<h3 style="font-size:13px;color:var(--accent);margin:12px 0 4px">
      왜 «${esc(c.verdict)}» 인가 — ${esc(d.name)} · ${esc(d.electrode.label)}</h3>
    <p class="${bad ? "verdict-no" : "verdict-ok"} small" style="margin:0 0 8px">
      ${esc(c.summary)}</p>` + svgContainment(d);

  h += `<h4 style="font-size:12px;margin:14px 0 4px">원인 — 구조에서 판정까지</h4>`
     + chainHtml(d);

  const ea = svgEaStages(d);
  if (ea) {
    h += `<h4 style="font-size:12px;margin:14px 0 4px">
        전자를 실제로 넣으면 — 판정이 뒤집히는 지점</h4>` + ea
      + `<p class="muted small" style="margin:2px 0 0">${esc(d.ea_stages.note)}
         구조를 고정한 «수직» 값만 보면 안전해 보이는 물질이, 음이온 구조가 완화되고
         용매가 감싸면서 환원 전위가 크게 올라갑니다.</p>`;
  }

  if (d.groups?.length) {
    h += `<h4 style="font-size:12px;margin:14px 0 4px">검출된 환원 취약 작용기</h4>
      <ul class="log-list">` + d.groups.map(g =>
        `<li><b>${esc(g.name)}</b>${g.count > 1 ? ` ×${g.count}` : ""} — ${esc(g.why)}</li>`
      ).join("") + `</ul>`;
  }

  const ladder = svgLumoLadder(d);
  if (ladder) {
    h += `<h4 style="font-size:12px;margin:14px 0 4px">LUMO 준위 비교</h4>` + ladder
       + `<p class="muted small" style="margin:2px 0 0">참고선은 모두 «표준» 프리셋에서
          실제로 계산한 값입니다 (괄호는 그 물질의 환원 전위).</p>`;
    if (d.lumo_caveat) {
      h += `<p class="verdict-mid small" style="margin:6px 0 0">
        <b>LUMO 만으로 판정하지 마세요.</b> ${esc(d.lumo_caveat.note)}</p>`;
    }
  }

  if (d.all_electrodes?.length) {
    h += `<h4 style="font-size:12px;margin:14px 0 4px">다른 전극에서는</h4>
      <div class="scroll-x"><table class="kv-table" style="min-width:560px">
      <tr><th style="width:170px">전극</th><th style="width:60px">구분</th>
        <th style="width:90px">판정</th><th>근거</th></tr>` +
      d.all_electrodes.map(e => `<tr><th>${esc(e.label)}</th>
        <td class="muted small">${e.side === "anode" ? "음극" : "양극"}</td>
        <td class="${e.verdict === "안정" ? "verdict-ok"
                   : e.verdict === "경계" ? "verdict-mid" : "verdict-no"}">${esc(e.verdict)}</td>
        <td class="muted small">${esc(e.summary)}</td></tr>`).join("") + `</table></div>`;
  }

  if (d.remedies?.length) {
    h += `<h4 style="font-size:12px;margin:14px 0 4px">판정을 바꾸려면</h4>
      <ul class="log-list">` + d.remedies.map(r => `<li>${esc(r)}</li>`).join("") + `</ul>`;
  }
  return h;
}

window.rbEswDiagnose = async function (jobId, electrode) {
  // 비교 화면은 2초마다 다시 그려진다 — 패널 내용을 상태로 들고 있지 않으면
  // 진단 결과가 곧바로 지워진다. eswSection() 이 이 html 을 다시 넣는다.
  const paint = html => {
    ESW_DIAG = {jobId, electrode: electrode || "graphite", html};
    const box = document.getElementById("esw-diag");
    if (box) box.innerHTML = html;
  };
  paint('<p class="muted small">진단 중…</p>');
  try {
    const res = await fetch("/api/esw/diagnose", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({job_id: jobId, electrode: electrode || "graphite"}),
    });
    const d = await res.json();
    if (!res.ok) throw new Error(d.detail || "진단 실패");
    paint(`<div class="toolbar" style="margin-bottom:6px">
        <span class="small muted">전극</span>
        ${d.electrodes.map(e => `<button class="btn ${e.key === d.electrode.key ? "primary" : ""}"
          type="button" onclick="window.rbEswDiagnose('${esc(jobId)}','${e.key}')"
          >${esc(e.label)}</button>`).join("")}
        <button class="btn ghost" type="button"
          onclick="window.rbEswDiagClose()">닫기</button>
      </div>` + eswDiagnoseHtml(d));
  } catch (e) {
    paint(`<p class="verdict-no small">${esc(e.message)}</p>`);
  }
};

window.rbEswDiagClose = function () {
  ESW_DIAG = null;
  const box = document.getElementById("esw-diag");
  if (box) box.innerHTML = "";
};

/* ---------- 배치 스크리닝 (기획서 05 구현) ---------- */
let SCR_META = null;
let SCR_PARSED = null;      // 마지막 검증 결과
let SCR_DETAIL_ID = null;   // 열려 있는 캠페인 id
let SCR_TIMER = null;
let SCR_WIRED = false;

const SCR_GRADE_BADGE = {
  "적합": "verdict-ok", "조건부": "verdict-mid",
  "부적합": "verdict-no", "판정 불가": "failed",
};
const SCR_STATUS_LABEL = {
  RUNNING: "진행 중", PAUSED: "일시정지", DONE: "완료", CANCELLED: "취소됨",
};

async function scrFetch(url, opts) {
  const res = await fetch(url, opts);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `요청 실패 (${res.status})`);
  return body;
}

async function scrMeta() {
  if (!SCR_META) SCR_META = await scrFetch("/api/screening/meta");
  return SCR_META;
}

function scrEta(s) {
  if (s == null) return "";
  if (s < 90) return `${Math.round(s)}초`;
  if (s < 5400) return `${Math.round(s / 60)}분`;
  return `${(s / 3600).toFixed(1)}시간`;
}

/* ----- 캠페인 목록 ----- */
async function scrRenderList() {
  const box = $("scr-campaign-list");
  if (!box) return;
  let campaigns;
  try {
    ({campaigns} = await scrFetch("/api/screening/campaigns"));
  } catch (e) { box.textContent = e.message; return; }
  if (!campaigns.length) {
    box.className = "empty small";
    box.textContent = "캠페인이 없습니다 — «+ 새 캠페인»으로 시작하세요.";
    return;
  }
  box.className = "";
  box.innerHTML = campaigns.map(c => {
    const pct = c.n_alive ? Math.round(100 * c.n_done_stage / c.n_alive) : 0;
    const badge = c.status === "RUNNING" ? "running" : c.status === "DONE" ? "published"
      : c.status === "PAUSED" ? "queued" : "failed";
    return `<div class="job-row" style="cursor:pointer" data-scr-open="${esc(c.id)}">
      <div class="job-main">
        <div><b>${esc(c.name)}</b> <span class="mono small muted">${esc(c.id)}</span></div>
        <div class="small muted">후보 ${c.n_candidates}개 · ${c.stages.map(esc).join(" → ")}
          · ${(c.electrodes || []).map(esc).join(", ")} · 마진 ${c.margin_v} V</div>
        ${["RUNNING", "PAUSED"].includes(c.status)
          ? `<div class="progress-track"><div class="progress-fill" style="width:${pct}%"></div></div>
             <div class="small muted">${c.stageIndex + 1}단계(${esc(c.stages[c.stageIndex] || "")})
               ${c.n_done_stage}/${c.n_alive} 완료${c.n_failed ? ` · 실패 ${c.n_failed}` : ""}
               ${c.autoPaused ? " · <b>실패율 초과로 자동 일시정지</b>" : ""}</div>` : ""}
      </div>
      <span class="badge ${badge}">${SCR_STATUS_LABEL[c.status] || esc(c.status)}</span>
    </div>`;
  }).join("");
  box.querySelectorAll("[data-scr-open]").forEach(el => el.addEventListener("click", () => {
    SCR_DETAIL_ID = el.dataset.scrOpen;
    $("scr-wizard").style.display = "none";
    scrRenderDetail();
  }));
}

/* ----- 새 캠페인 마법사 ----- */
async function scrOpenWizard() {
  const meta = await scrMeta();
  $("scr-wizard").style.display = "";
  $("scr-detail").style.display = "none";
  SCR_DETAIL_ID = null;
  // 전극 체크박스 — ESW 진단과 같은 구동 범위를 쓴다
  const eBox = $("scr-electrodes");
  if (!eBox.childElementCount) {
    eBox.innerHTML = meta.electrodes.map(e =>
      `<label class="compare-check small" style="margin-right:10px">
        <input type="checkbox" data-scr-elec="${esc(e.key)}"
          ${["graphite", "ncm811"].includes(e.key) ? "checked" : ""}>
        ${esc(e.label)} <span class="muted">(${e.low.toFixed(2)}~${e.high.toFixed(2)} V)</span></label>`
    ).join("");
    eBox.querySelectorAll("input").forEach(i => i.addEventListener("change", scrEstimate));
  }
  const sSel = $("scr-solvent");
  if (!sSel.options.length) {
    sSel.add(new Option("(용매 없음 — 진공·기체)", ""));
    for (const s of PRESETS.solvents) sSel.add(new Option(`${s.abbr} — ${s.name}`, s.id));
    sSel.value = PRESETS.defaults.solventId;
  }
  const rSel = $("scr-ref");
  if (!rSel.options.length) {
    for (const r of PRESETS.referenceElectrodes) rSel.add(new Option(r, r));
    rSel.value = "Li/Li+";
  }
  const fSel = $("scr-func");
  if (!fSel.options.length) {
    for (const f of PRESETS.functionals) fSel.add(new Option(f, f));
    fSel.value = PRESETS.defaults.expert.functional;
  }
  scrEstimate();
}

function scrStages() {
  const stages = [];
  if ($("scr-st1").checked)
    stages.push({accuracy: "빠름", keep: Math.max(1, +$("scr-keep1").value || 20)});
  if ($("scr-st2").checked)
    stages.push({accuracy: "표준", keep: Math.max(1, +$("scr-keep2").value || 5)});
  if ($("scr-st3").checked) stages.push({accuracy: "정밀"});
  if (stages.length) delete stages[stages.length - 1].keep;  // 마지막 단계는 전원 판정
  return stages;
}

async function scrEstimate() {
  const out = $("scr-estimate");
  if (!out) return;
  const meta = await scrMeta();
  const n = SCR_PARSED ? SCR_PARSED.rows.filter(r => r.ok).length : 0;
  const stages = scrStages();
  if (!n || !stages.length) {
    out.textContent = n ? "깔때기 단계를 하나 이상 선택하세요."
      : "후보 목록을 검증하면 예상 계산량이 여기 표시됩니다.";
    return;
  }
  let remain = n, total = 0;
  const parts = [];
  for (const st of stages) {
    const sec = remain * (meta.estimate_s[st.accuracy] || 1200) / meta.batch_parallel;
    parts.push(`${st.accuracy} ${remain}개(≈${scrEta(sec)})`);
    total += sec;
    if (st.keep) remain = Math.min(remain, st.keep);
  }
  out.innerHTML = `예상 계산량 — ${parts.join(" → ")} ⇒ <b>총 ≈${scrEta(total)}</b>
    <span class="muted">(워커 ${meta.batch_parallel}개 기준 어림값 — 분자 크기에 따라 달라집니다)</span>`;
}

async function scrParse() {
  const err = $("scr-error");
  err.textContent = "";
  const text = $("scr-cands").value.trim();
  if (!text) { err.textContent = "후보 목록을 입력하거나 파일을 불러오세요."; return; }
  const btn = $("scr-parse-btn");
  btn.disabled = true;
  try {
    SCR_PARSED = await scrFetch("/api/screening/parse", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({text, structure: $("scr-structure").value}),
    });
    const {rows, n_ok, n_error, warning} = SCR_PARSED;
    $("scr-parse-count").textContent = `유효 ${n_ok}개 · 제외 ${n_error}개`;
    const bad = rows.filter(r => !r.ok);
    $("scr-parse-out").innerHTML = `
      ${warning ? `<p class="verdict-no small">${esc(warning)}</p>` : ""}
      ${bad.length ? `<details class="small" style="margin-top:6px" open>
        <summary>제외된 행 ${bad.length}개 — 사유</summary>
        <div class="scroll-x"><table class="table" style="min-width:420px">
          <tr><th>행</th><th>입력</th><th>사유</th></tr>
          ${bad.map(r => `<tr><td>${r.line}</td><td class="mono">${esc(r.smiles || r.name)}</td>
            <td>${esc(r.error)}</td></tr>`).join("")}
        </table></div></details>` : ""}
      ${n_ok ? `<details class="small" style="margin-top:6px">
        <summary>등록될 후보 ${n_ok}개</summary>
        <div class="scroll-x"><table class="table" style="min-width:420px">
          <tr><th>이름</th><th>SMILES</th><th>계산 구조</th><th>원자</th></tr>
          ${rows.filter(r => r.ok).map(r => `<tr><td>${esc(r.name)}</td>
            <td class="mono">${esc(r.smiles)}</td>
            <td class="mono muted">${esc(r.calc_smiles)}</td><td>${r.atoms}</td></tr>`).join("")}
        </table></div></details>` : ""}`;
    scrEstimate();
  } catch (e) {
    err.textContent = e.message;
  } finally { btn.disabled = false; }
}

async function scrSubmit() {
  const err = $("scr-error");
  err.textContent = "";
  if (!SCR_PARSED || !SCR_PARSED.rows.some(r => r.ok)) {
    err.textContent = "먼저 «목록 검증»으로 후보를 확정하세요."; return;
  }
  const electrodes = [...document.querySelectorAll("[data-scr-elec]:checked")]
    .map(i => i.dataset.scrElec);
  if (!electrodes.length) { err.textContent = "대상 활물질을 하나 이상 선택하세요."; return; }
  const stages = scrStages();
  if (!stages.length) { err.textContent = "깔때기 단계를 하나 이상 선택하세요."; return; }
  const solventId = $("scr-solvent").value || null;
  const payload = {
    name: $("scr-name").value.trim(),
    candidates: SCR_PARSED.rows.filter(r => r.ok)
      .map(r => ({name: r.name, smiles: r.smiles})),
    electrodes,
    marginV: Math.max(0, +$("scr-margin").value || 0.3),
    stages,
    settings: {
      envType: solventId ? "사용자 정의" : "진공·기체",
      solventId,
      temperature: +$("scr-temp").value || 298.15,
      structure: $("scr-structure").value,
      referenceElectrode: $("scr-ref").value,
      expert: {...PRESETS.defaults.expert, functional: $("scr-func").value},
    },
  };
  const btn = $("scr-submit");
  btn.disabled = true;
  try {
    const {campaign} = await scrFetch("/api/screening/campaigns", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    $("scr-wizard").style.display = "none";
    SCR_DETAIL_ID = campaign.id;
    await scrRenderList();
    await scrRenderDetail();
  } catch (e) {
    err.textContent = e.message;
  } finally { btn.disabled = false; }
}

/* ----- 캠페인 상세 (대시보드 + 판정표) ----- */
async function scrRenderDetail() {
  if (!SCR_DETAIL_ID) return;
  const card = $("scr-detail");
  let v;
  try {
    v = await scrFetch(`/api/screening/campaigns/${SCR_DETAIL_ID}`);
  } catch (e) {
    card.style.display = "";
    $("scr-detail-body").innerHTML = `<p class="verdict-no small">${esc(e.message)}</p>`;
    return;
  }
  card.style.display = "";
  $("scr-detail-title").textContent =
    `${v.name} — ${SCR_STATUS_LABEL[v.status] || v.status}`;
  const running = ["RUNNING", "PAUSED"].includes(v.status);
  $("scr-pause").style.display = v.status === "RUNNING" ? "" : "none";
  $("scr-resume").style.display = v.status === "PAUSED" ? "" : "none";
  $("scr-cancel").style.display = running ? "" : "none";
  $("scr-delete").style.display = running ? "none" : "";

  const stageBars = v.stages.map((st, i) => {
    const denom = st.n_entered || v.counts.alive || 1;
    const pct = Math.min(100, Math.round(100 * st.n_done / Math.max(1, denom)));
    return `<div style="margin:4px 0">
      <span class="small">${i + 1}차 — ${esc(st.accuracy)}
        <span class="muted">(${esc(st.state)}${st.keep ? ` · 통과 ${st.keep}` : ""})</span></span>
      <div class="progress-track"><div class="progress-fill" style="width:${pct}%"></div></div>
      <span class="small muted">${st.n_done}/${denom} 완료</span></div>`;
  }).join("");

  const c = v.counts;
  const summary = `<div style="display:flex;flex-wrap:wrap;gap:8px;margin:8px 0">
    <span class="badge verdict-ok">적합 ${c.fit}</span>
    <span class="badge verdict-mid">조건부 ${c.conditional}</span>
    <span class="badge verdict-no">부적합 ${c.unfit}</span>
    <span class="badge failed">판정 불가 ${c.failed}</span>
    <span class="badge queued">탈락(깔때기) ${c.cut}</span>
    <span class="muted small" style="align-self:center">총 ${c.total}개
      ${v.eta_s != null ? ` · 남은 시간 ≈${scrEta(v.eta_s)}` : ""}</span></div>`;

  const elecs = v.electrodes;
  const rows = [...v.candidates].sort((a, b) =>
    (a.rank == null) - (b.rank == null) || (a.rank || 0) - (b.rank || 0));
  const tbl = `<div class="scroll-x"><table class="table" style="min-width:760px">
    <tr><th>순위</th><th>후보</th><th>상태</th><th>판정</th>
      ${elecs.map(e => `<th class="small">${esc(e)}<br>여유(V)</th>`).join("")}
      <th>산화(V)</th><th>환원(V)</th><th></th></tr>
    ${rows.map(cd => {
      const vd = cd.verdict || {};
      const per = {};
      (vd.per_electrode || []).forEach(p => per[p.electrode] = p);
      const grade = vd.grade || (cd.failed ? "판정 불가" : "—");
      const lastJob = Object.values(cd.jobs || {}).pop();
      return `<tr>
        <td>${cd.rank || ""}</td>
        <td><b>${esc(cd.name)}</b><br><span class="mono small muted">${esc(cd.smiles)}</span></td>
        <td class="small">${esc(cd.state)}${cd.progress != null && cd.state === "계산 중"
            ? ` ${cd.progress}%` : ""}${cd.detail
            ? `<br><span class="muted">${esc(cd.detail)}</span>` : ""}</td>
        <td><span class="badge ${SCR_GRADE_BADGE[grade] || "queued"}">${esc(grade)}</span>
          ${cd.provisional ? '<span class="muted small"> 잠정</span>' : ""}</td>
        ${elecs.map(e => {
          const p = per[e];
          return `<td class="small ${p ? (p.grade === "적합" ? "verdict-ok"
            : p.grade === "조건부" ? "verdict-mid" : "verdict-no") : "muted"}">
            ${p ? p.margin_v.toFixed(2) : "—"}</td>`;
        }).join("")}
        <td class="small">${vd.oxidation_v != null ? (+vd.oxidation_v).toFixed(2) : "—"}</td>
        <td class="small">${vd.reduction_v != null ? (+vd.reduction_v).toFixed(2) : "—"}</td>
        <td>${lastJob ? `<button class="btn small" data-scr-job="${esc(lastJob)}"
          type="button">상세</button>` : ""}</td></tr>`;
    }).join("")}
  </table></div>`;

  $("scr-detail-body").innerHTML = `
    ${summary}
    <h3 style="font-size:13px;color:var(--accent)">단계 진행</h3>${stageBars}
    <h3 style="font-size:13px;color:var(--accent);margin-top:12px">판정표
      <span class="muted small">— 여유(V) = 구동 범위와 ESW 사이의 최소 간격.
      마진 ${v.margin_v} V 이상이면 적합</span></h3>
    ${tbl}
    <p class="rb-note small" style="margin-top:10px">${esc(v.thermo_note)}</p>
    <details class="small" style="margin-top:8px"><summary class="muted">캠페인 로그</summary>
      <ul class="log-list">${(v.logs || []).slice(-40).map(l => `<li>${esc(l)}</li>`).join("")}</ul>
    </details>`;

  $("scr-detail-body").querySelectorAll("[data-scr-job]").forEach(b =>
    b.addEventListener("click", async () => {
      try {
        const job = await scrFetch(`/api/jobs/${b.dataset.scrJob}`);
        if (window.rbOpenResults) window.rbOpenResults();
        if (job.status === "PUBLISHED") showResult(job);
      } catch (e) { /* 작업이 지워진 경우 — 무시 */ }
    }));
}

async function scrAction(action) {
  if (!SCR_DETAIL_ID) return;
  try {
    await scrFetch(`/api/screening/campaigns/${SCR_DETAIL_ID}/${action}`, {method: "POST"});
  } catch (e) { alert(e.message); }
  await scrRenderList();
  await scrRenderDetail();
}

function scrWire() {
  if (SCR_WIRED) return;
  SCR_WIRED = true;
  $("scr-new-btn").addEventListener("click", scrOpenWizard);
  $("scr-wizard-close").addEventListener("click", () => $("scr-wizard").style.display = "none");
  $("scr-refresh").addEventListener("click", () => { scrRenderList(); scrRenderDetail(); });
  $("scr-parse-btn").addEventListener("click", scrParse);
  $("scr-submit").addEventListener("click", scrSubmit);
  $("scr-file").addEventListener("change", (e) => {
    const f = e.target.files[0];
    if (!f) return;
    const reader = new FileReader();
    reader.onload = () => { $("scr-cands").value = reader.result; scrParse(); };
    reader.readAsText(f);
  });
  ["scr-st1", "scr-st2", "scr-st3", "scr-keep1", "scr-keep2"].forEach(id =>
    $(id).addEventListener("change", scrEstimate));
  $("scr-detail-close").addEventListener("click", () => {
    SCR_DETAIL_ID = null;
    $("scr-detail").style.display = "none";
  });
  $("scr-pause").addEventListener("click", () => scrAction("pause"));
  $("scr-resume").addEventListener("click", () => scrAction("resume"));
  $("scr-cancel").addEventListener("click", () => {
    if (confirm("캠페인을 취소할까요? 진행 중인 계산도 함께 취소됩니다.")) scrAction("cancel");
  });
  $("scr-delete").addEventListener("click", async () => {
    if (!confirm("캠페인 기록을 삭제할까요? (완료된 개별 계산 결과는 남습니다)")) return;
    try {
      await scrFetch(`/api/screening/campaigns/${SCR_DETAIL_ID}`, {method: "DELETE"});
      SCR_DETAIL_ID = null;
      $("scr-detail").style.display = "none";
      await scrRenderList();
    } catch (e) { alert(e.message); }
  });
  $("scr-export-csv").addEventListener("click", () =>
    window.open(`/api/screening/campaigns/${SCR_DETAIL_ID}/export?format=csv`, "_blank"));
  $("scr-export-json").addEventListener("click", () =>
    window.open(`/api/screening/campaigns/${SCR_DETAIL_ID}/export?format=json`, "_blank"));
  // 진행 상황 폴링 — 화면이 열려 있는 동안만
  SCR_TIMER = setInterval(() => {
    const real = document.getElementById("rb-real");
    if (!real || !real.classList.contains("mode-screen")) return;
    scrRenderList();
    if (SCR_DETAIL_ID && $("scr-detail").style.display !== "none") scrRenderDetail();
  }, 4000);
}

window.rbRenderScreen = function () {
  scrWire();
  scrRenderList();
  if (SCR_DETAIL_ID) scrRenderDetail();
};
