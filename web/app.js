let PRESETS = null;
let JOBS = [];
const selected = new Set();

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

/* ---------- 화면 전환 ---------- */
const VIEWS = ["dashboard", "materials", "submit", "jobs"];

function showView(name) {
  if (!VIEWS.includes(name)) name = "dashboard";
  for (const v of VIEWS) {
    $(`view-${v}`).classList.toggle("active", v === name);
  }
  document.querySelectorAll(".nav-item").forEach(btn =>
    btn.classList.toggle("active", btn.dataset.view === name));
  if (location.hash !== `#/${name}`) history.replaceState(null, "", `#/${name}`);
  if (name === "dashboard") renderDashboard();
  if (name === "materials") renderMaterialLib();
}

function currentView() {
  return (location.hash.match(/^#\/(\w+)/) || [])[1] || "dashboard";
}

/* ---------- 초기화 ---------- */
async function init() {
  PRESETS = await (await fetch("/api/presets")).json();

  document.querySelectorAll(".nav-item").forEach(btn =>
    btn.addEventListener("click", () => showView(btn.dataset.view)));
  document.querySelectorAll("[data-goto]").forEach(el =>
    el.addEventListener("click", () => showView(el.dataset.goto)));
  window.addEventListener("hashchange", () => showView(currentView()));

  buildSubmitForm();
  await refreshJobs();
  showView(currentView());
  setInterval(refreshJobs, 2000);
}

/* ---------- 대시보드 ---------- */
function renderDashboard() {
  const total = JOBS.length;
  const pub = JOBS.filter(j => j.status === "PUBLISHED").length;
  const act = JOBS.filter(j => ["QUEUED", "RUNNING"].includes(j.status)).length;
  const fail = JOBS.filter(j => j.status === "FAILED").length;
  $("dash-stats").innerHTML = [
    ["전체 작업", total, "누적"],
    ["PUBLISHED", pub, "검증 완료 결과"],
    ["실행·대기", act, "현재 큐"],
    ["실패", fail, "오류·취소 포함"],
  ].map(([label, v, sub]) => `
    <div class="stat-tile">
      <div class="stat-label">${label}</div>
      <div class="stat-value">${v}<span class="stat-unit"> 건</span></div>
      <div class="stat-sub">${sub}</div>
    </div>`).join("");

  const recent = JOBS.filter(j => j.status === "PUBLISHED").slice(0, 5);
  const box = $("dash-recent");
  if (!recent.length) {
    box.className = "empty small";
    box.textContent = "아직 완료된 계산이 없습니다. '새 계산 제출'에서 시작하세요.";
    return;
  }
  box.className = "scroll-x";
  box.innerHTML = `<table class="table">
    <tr><th>소재</th><th class="num">HOMO (eV)</th><th class="num">갭 (eV)</th><th>방법</th></tr>
    ${recent.map(j => `
      <tr>
        <td><b>${esc(j.material.abbr ?? j.material.name)}</b>
          <span class="mono small muted">${esc(j.id.slice(-6))}</span></td>
        <td class="num">${j.result.descriptors.homo_ev ?? "—"}</td>
        <td class="num">${j.result.descriptors.gap_ev ?? "—"}</td>
        <td class="small muted">${esc(j.result.conditions.method)}</td>
      </tr>`).join("")}
  </table>`;
}

/* ---------- 물질 라이브러리 ---------- */
function renderMaterialLib() {
  $("material-lib").innerHTML = PRESETS.materials.map(m => {
    const done = JOBS.filter(j => j.material.id === m.id && j.status === "PUBLISHED").length;
    return `
    <div class="mat-card">
      <div class="mat-card-top">
        <span class="initial-badge">${esc(m.abbr)}</span>
        ${done ? `<span class="badge published">결과 ${done}건</span>`
               : `<span class="badge queued">계산 전</span>`}
      </div>
      <div class="mat-name">${esc(m.name)}</div>
      <div class="small muted">${esc(m.formula)} · ${esc(m.note)}</div>
      <div class="mono small muted">${esc(m.smiles["모노머"])}</div>
      <button class="btn" data-calc="${esc(m.id)}">이 소재로 계산</button>
    </div>`;
  }).join("");
  document.querySelectorAll("[data-calc]").forEach(btn =>
    btn.addEventListener("click", () => {
      selected.clear();
      selected.add(btn.dataset.calc);
      syncMaterialCards();
      showView("submit");
    }));
}

/* ---------- 제출 폼 ---------- */
function buildSubmitForm() {
  const grid = $("material-grid");
  grid.innerHTML = "";
  for (const m of PRESETS.materials) {
    const btn = document.createElement("button");
    btn.className = "mol-card";
    btn.dataset.mid = m.id;
    btn.innerHTML = `<b>${esc(m.name)}</b>
      <span class="small muted">${esc(m.formula)} · ${esc(m.note)}</span>
      <span class="mono small muted">${esc(m.smiles["모노머"])}</span>`;
    btn.onclick = () => {
      selected.has(m.id) ? selected.delete(m.id) : selected.add(m.id);
      syncMaterialCards();
    };
    grid.appendChild(btn);
  }

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

  fillSelect("solvent", PRESETS.solvents.map(s =>
    [s.id, `${s.abbr}${s.kind === "mixed" ? " (혼합)" : ""} — ${s.note}`]), PRESETS.defaults.solventId);
  fillSelect("atmosphere", PRESETS.atmospheres.map(a => [a, a]), PRESETS.defaults.atmosphere);
  fillSelect("ref-electrode", PRESETS.referenceElectrodes.map(r => [r, r]), PRESETS.defaults.referenceElectrode);
  fillSelect("structure", PRESETS.structures.map(s => [s, s]), PRESETS.defaults.structure);
  fillSelect("accuracy", Object.keys(PRESETS.accuracy).map(k => [k, k]), PRESETS.defaults.accuracy);
  fillSelect("purpose", PRESETS.purposes.map(p => [p, p]), PRESETS.defaults.purpose);
  fillSelect("functional", PRESETS.functionals.map(f => [f, f]), PRESETS.defaults.expert.functional);
  for (const b of PRESETS.basisSets) $("basis").add(new Option(b, b));

  $("accuracy").onchange = syncAccuracyDesc;
  syncAccuracyDesc();
  syncEnvState();
  $("submit-btn").onclick = submit;
}

function syncMaterialCards() {
  document.querySelectorAll("#material-grid .mol-card").forEach(btn =>
    btn.classList.toggle("selected", selected.has(btn.dataset.mid)));
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
  const body = {
    materialIds: [...selected],
    customSmiles: $("custom-smiles").value.trim() || null,
    customName: $("custom-name").value.trim() || null,
    settings: {
      envType: env,
      solventId: env === "진공·기체" ? null : $("solvent").value,
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
    showView("jobs");
  } catch (e) {
    $("form-error").textContent = e.message;
  } finally {
    btn.disabled = false;
  }
}

/* ---------- 작업 큐 ---------- */
const badgeClass = {QUEUED: "queued", RUNNING: "running", PUBLISHED: "published", FAILED: "failed"};
const badgeLabel = {QUEUED: "대기", RUNNING: "실행", PUBLISHED: "PUBLISHED", FAILED: "실패"};

async function refreshJobs() {
  try {
    JOBS = (await (await fetch("/api/jobs")).json()).jobs;
  } catch { return; }
  renderJobList();
  if ($("view-dashboard").classList.contains("active")) renderDashboard();
}

function renderJobList() {
  const list = $("job-list");
  if (!JOBS.length) {
    list.className = "empty small";
    list.textContent = "작업이 없습니다.";
    return;
  }
  list.className = "";
  list.innerHTML = "";
  for (const job of JOBS) {
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
             <div class="small muted">${esc(job.stage)}</div>` : ""}
        ${job.error ? `<div class="small" style="color:var(--danger)">${esc(job.error)}</div>` : ""}
        <details><summary class="small muted">로그 (${job.logs.length})</summary>
          <ul class="log-list">${job.logs.map(l => `<li>${esc(l)}</li>`).join("")}</ul></details>
      </div>
      <div class="job-side">
        <span class="badge ${badgeClass[job.status] || "queued"}">${badgeLabel[job.status] || esc(job.status)}</span>
        ${job.status === "PUBLISHED"
          ? `<button class="btn ghost" data-view-job="${esc(job.id)}">결과 보기</button>` : ""}
        ${["QUEUED", "RUNNING"].includes(job.status)
          ? `<button class="btn ghost danger" data-cancel="${esc(job.id)}">취소</button>`
          : `<button class="btn ghost danger" data-del="${esc(job.id)}">삭제</button>`}
      </div>`;
    div.querySelector("[data-view-job]")?.addEventListener("click", () => showResult(job));
    div.querySelector("[data-cancel]")?.addEventListener("click", () =>
      fetch(`/api/jobs/${job.id}/cancel`, {method: "POST"}).then(refreshJobs));
    div.querySelector("[data-del]")?.addEventListener("click", () =>
      fetch(`/api/jobs/${job.id}`, {method: "DELETE"}).then(refreshJobs));
    list.appendChild(div);
  }
}

/* ---------- 결과 상세 ---------- */
const DESC_LABELS = {
  total_energy_hartree: ["전자 에너지", "Ha"],
  homo_ev: ["HOMO", "eV"], lumo_ev: ["LUMO", "eV"], gap_ev: ["HOMO–LUMO 갭", "eV"],
  dipole_debye: ["쌍극자 모멘트", "D"],
  zpe_kcal: ["영점 진동 에너지 (ZPE)", "kcal/mol"],
  gibbs_correction_kcal: ["깁스 보정 (G − E, 기체상)", "kcal/mol"],
  gibbs_energy_hartree: ["깁스 자유에너지 (E+G보정)", "Ha"],
  entropy_cal_mol_k: ["엔트로피 S", "cal/(mol·K)"],
  n_imaginary_freqs: ["허수 진동수 개수", ""],
  solvation_energy_kcal: ["용매화 에너지 ΔE(solv−gas)", "kcal/mol"],
  smd_cds_kcal: ["SMD CDS 항", "kcal/mol"],
  ip_vertical_ev: ["수직 이온화 에너지 (IP)", "eV"],
  ea_vertical_ev: ["수직 전자 친화도 (EA)", "eV"],
  ip_adiabatic_ev: ["단열 이온화 에너지 (IP)", "eV"],
  ea_adiabatic_ev: ["단열 전자 친화도 (EA)", "eV"],
  oxidation_potential_v: ["산화 전위", "V"],
  reduction_potential_v: ["환원 전위", "V"],
  oxidation_potential_gibbs_v: ["산화 전위 (ΔG 기반)", "V"],
  reduction_potential_gibbs_v: ["환원 전위 (ΔG 기반)", "V"],
};

function showResult(job) {
  const r = job.result;
  $("result-title").textContent = `결과 상세 — ${job.material.name} (${job.id})`;
  const ref = r.descriptors.potential_reference;
  let rows = "";
  for (const [key, val] of Object.entries(r.descriptors)) {
    if (key === "potential_reference" || val == null) continue;
    const [label, unit] = DESC_LABELS[key] || [key, ""];
    const suffix = key.includes("potential") && ref ? ` vs ${ref}` : "";
    rows += `<tr><th>${esc(label)}</th><td>${typeof val === "number" ? val : esc(val)} ${unit}${suffix}</td></tr>`;
  }
  let condRows = "";
  for (const [k, v] of Object.entries(r.conditions)) {
    condRows += `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`;
  }
  $("result-body").innerHTML = `
    <h3 style="font-size:13px;color:var(--accent)">기술자 (실계산 값)</h3>
    <table class="kv-table">${rows}</table>
    <h3 style="font-size:13px;color:var(--accent);margin-top:16px">계산 조건</h3>
    <table class="kv-table">${condRows}
      <tr><th>wall time</th><td>${r.wall_time_s} s</td></tr></table>
    <h3 style="font-size:13px;color:var(--accent);margin-top:16px">주의사항</h3>
    <ul class="log-list">${r.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul>
    <h3 style="font-size:13px;color:var(--accent);margin-top:16px">최종 구조 (XYZ)</h3>
    <pre class="xyz">${esc(r.structure_xyz)}</pre>`;
  $("result-card").style.display = "";
  $("result-card").scrollIntoView({behavior: "smooth"});
}

init();
