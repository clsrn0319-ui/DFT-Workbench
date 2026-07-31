let PRESETS = null;
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
  let src = document.getElementById("material-src-note");
  if (!src) {
    src = document.createElement("p");
    src.id = "material-src-note";
    src.className = "muted small";
    src.style.margin = "10px 0 0";
    grid.after(src);
  }
  src.textContent = lib
    ? `물질 보관함과 연동됨 (${items.length}종) — 보관함에서 추가·수정한 소재는 이 페이지를 다시 열면 반영됩니다. `
      + "사전 등록 소재는 2량체/3량체 구조를 지원하고, 사용자 등록 소재는 입력한 SMILES 구조 그대로 계산합니다."
    : "물질 보관함을 읽지 못해 기본 소재 프리셋을 표시합니다.";
}
window.rbReloadMaterials = buildMaterialGrid;

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
  $("add-explicit").onclick = () => addExplicitRow();
  $("submit-btn").onclick = submit;
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
             <div class="small muted">${esc(job.stage)}</div>` : ""}
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
