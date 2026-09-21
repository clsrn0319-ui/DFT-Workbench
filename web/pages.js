/* ------------------------------------------------------------------
   기획서 반영 페이지 — 대시보드 · 템플릿 · 설정 · 튜토리얼
   + «계산» 통합(분자 하나 / 배치 토글, 조건 동기화) · 템플릿 적용 · 같은 조건으로 재계산
   app.js 뒤에 로드 ($, esc, fmt, JOBS_CACHE, PRESETS 는 app.js 전역).
   ------------------------------------------------------------------ */
(function () {
  "use strict";
  const IS_SNAPSHOT = !!window.__RB_SNAPSHOT__;
  const h = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const setSel = (id, v) => { const el = document.getElementById(id); if (!el || v == null) return false; if ([...el.options].some(o => o.value === String(v))) { el.value = String(v); el.dispatchEvent(new Event("change")); return true; } return false; };
  const setVal = (id, v) => { const el = document.getElementById(id); if (!el || v == null) return; el.value = v; el.dispatchEvent(new Event("input")); el.dispatchEvent(new Event("change")); };

  /* ══════════ 계산 통합: 분자 하나 ↔ 배치 토글 + 조건 동기화 ══════════ */
  const SYNC = [["solvent", "scr-solvent"], ["temperature", "scr-temp"], ["ref-electrode", "scr-ref"], ["structure", "scr-structure"],
                ["functional", "scr-func"], ["basis", "scr-basis"], ["basis-anion", "scr-basis-anion"], ["li-model", "scr-li-model"],
                ["li-coord", "scr-li-coord"], ["li-sites", "scr-li-sites"], ["charge", "scr-charge"], ["multiplicity", "scr-mult"]];
  function syncFields(fromCalc) {
    let n = 0;
    SYNC.forEach(([a, b]) => {
      const src = document.getElementById(fromCalc ? a : b), dst = document.getElementById(fromCalc ? b : a);
      if (!src || !dst || src.value === "" || src.value == null) return;
      if (dst.tagName === "SELECT") { if (setSel(dst.id, src.value)) n++; }
      else { dst.value = src.value; dst.dispatchEvent(new Event("input")); dst.dispatchEvent(new Event("change")); n++; }
    });
    return n;
  }
  function modeBar(current) {
    return `<div class="calc-modebar"><span class="seg"><button type="button" data-cm="calc" class="${current === "calc" ? "on" : ""}">분자 하나 계산</button><button type="button" data-cm="screen" class="${current === "screen" ? "on" : ""}">여러 후보 배치 스크리닝</button></span>
      <span class="small muted">환경·계산 설정은 두 방식이 공유합니다 — 전환할 때 값을 그대로 가져갑니다</span>
      <label class="small" style="margin-left:auto;display:inline-flex;gap:6px;align-items:center">템플릿 <select class="input" id="tpl-apply-${current}"><option value="">(선택)</option></select></label>
      <button class="btn sm" type="button" data-tpl-save="${current}" title="지금 화면의 조건을 템플릿으로 저장">현재 조건 저장</button></div>`;
  }
  function installModeBars() {
    for (const [mode, sectionId, anchor] of [["calc", "rbv-calc", ".rb-note"], ["screen", "rbv-screen", ".rb-note"]]) {
      const sec = document.getElementById(sectionId); if (!sec || sec.querySelector(".calc-modebar")) continue;
      const note = sec.querySelector(anchor) || sec.querySelector("h1");
      const wrap = document.createElement("div"); wrap.innerHTML = modeBar(mode);
      note.insertAdjacentElement("afterend", wrap.firstElementChild);
    }
    document.querySelectorAll(".calc-modebar [data-cm]").forEach(b => b.addEventListener("click", () => {
      const to = b.dataset.cm, from = to === "calc" ? "screen" : "calc";
      const real = document.getElementById("rb-real");
      if (real && real.classList.contains("mode-" + to)) return;
      const n = syncFields(from === "calc");
      if (window.rbOpenMode) window.rbOpenMode(to, "계산");
      if (to === "screen" && window.rbScreenOpenWizard) try { window.rbScreenOpenWizard(); } catch (e) {}
      if (n) rbToast(`환경·계산 설정 ${n}개 항목을 가져왔습니다`);
    }));
    document.querySelectorAll(".calc-modebar [data-tpl-save]").forEach(b => b.addEventListener("click", () => saveTemplateFromForm(b.dataset.tplSave)));
    document.querySelectorAll(".calc-modebar select[id^='tpl-apply-']").forEach(sel => sel.addEventListener("change", () => { if (sel.value) { applyTemplate(sel.value, sel.id.endsWith("screen") ? "screen" : "calc"); sel.value = ""; } }));
    fillTemplateSelects();
  }
  function rbToast(msg) {
    let t = document.getElementById("rb-toast");
    if (!t) { t = document.createElement("div"); t.id = "rb-toast"; document.body.appendChild(t); }
    t.textContent = msg; t.classList.add("on"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("on"), 2600);
  }
  window.rbToast = rbToast;

  /* ══════════ 템플릿 ══════════ */
  let TEMPLATES = [];
  async function loadTemplates() {
    try { const r = await fetch("/api/templates"); if (r.ok) TEMPLATES = (await r.json()).templates || []; } catch (e) { TEMPLATES = TEMPLATES.length ? TEMPLATES : []; }
    fillTemplateSelects();
    return TEMPLATES;
  }
  function fillTemplateSelects() {
    document.querySelectorAll("select[id^='tpl-apply-']").forEach(sel => {
      const cur = sel.value; sel.innerHTML = '<option value="">(템플릿 적용)</option>' + TEMPLATES.map(t => `<option value="${h(t.id)}">${h(t.name)}${t.builtin ? "" : " · 사용자"}</option>`).join(""); sel.value = cur;
    });
  }
  function applySettingsToCalc(s) {
    if (!s) return 0; let n = 0;
    const exp = s.expert || {};
    if (s.envType) { const r = document.querySelector(`input[name="env"][value="${CSS.escape(s.envType)}"]`); if (r) { r.checked = true; r.dispatchEvent(new Event("change", {bubbles: true})); n++; } }
    if (s.solventId !== undefined) { if (setSel("solvent", s.solventId || "")) n++; }
    if (s.customMixedSolvent && window.rbLibSetCalcMixture) { window.rbLibSetCalcMixture(s.customMixedSolvent); n++; }
    if (s.temperature != null) { setVal("temperature", s.temperature); n++; }
    if (s.referenceElectrode) { if (setSel("ref-electrode", s.referenceElectrode)) n++; }
    if (s.structure && setSel("structure", s.structure)) n++;
    if (s.accuracy && setSel("accuracy", s.accuracy)) n++;
    if (s.purpose && setSel("purpose", s.purpose)) n++;
    const map = {functional: "functional", basis: "basis", basisAnion: "basis-anion", charge: "charge", multiplicity: "multiplicity", nConformers: "n-conformers",
                 liModel: "li-model", liCoordination: "li-coord", liMaxSites: "li-sites", logLevel: "log-level", scfMaxCycle: "scf-max-cycle", freqScale: "freq-scale",
                 startStructure: "start-structure", torsionPattern: "torsion-pattern", representative: "start-rep"};
    for (const [k, id] of Object.entries(map)) { if (exp[k] == null) continue; const el = document.getElementById(id); if (!el) continue; if (el.tagName === "SELECT") { if (setSel(id, exp[k])) n++; } else { setVal(id, exp[k]); n++; } }
    const tri = {optimizeGeometry: "optimize", thermochemistry: "thermo", redoxAdiabatic: "redox-mode", nonequilibriumSolvation: "noneq-solv", boltzmannEnsemble: "boltzmann", conformerSensitivity: "conf-sens", qrrho: "qrrho", optimizeInSolvent: "opt-solvent", bdeRelaxFragments: "bde-relax", bdeThermalCorrection: "bde-thermal", fixBackboneTorsions: "fix-torsions"};
    for (const [k, id] of Object.entries(tri)) { if (exp[k] == null) continue; const el = document.getElementById(id); if (!el || el.tagName !== "SELECT") continue; const v = exp[k] === true ? "true" : exp[k] === false ? "false" : String(exp[k]); if (setSel(id, v) || setSel(id, exp[k] ? "on" : "off") || setSel(id, exp[k] ? "1" : "0")) n++; }
    if (window.rbSyncStartStructure) window.rbSyncStartStructure();
    return n;
  }
  function applyTemplate(id, target) {
    const t = TEMPLATES.find(x => x.id === id); if (!t) return;
    const s = t.settings || {};
    let n = applySettingsToCalc(s);
    if (target === "screen" || document.getElementById("rb-real")?.classList.contains("mode-screen")) {
      n += syncFields(true);
      if (t.margin_v != null) setVal("scr-margin", t.margin_v);
      if (t.top_n != null) setVal("scr-keep1", t.top_n);
      if (Array.isArray(t.electrodes)) document.querySelectorAll("#scr-electrodes input[data-scr-elec]").forEach(i => { i.checked = t.electrodes.includes(i.dataset.scrElec); i.dispatchEvent(new Event("change")); });
      if (s.accuracy && window.wizApplyPreset) try { window.wizApplyPreset({"빠름": "빠름", "표준": "표준", "정밀": "정밀"}[s.accuracy], {silent: true}); } catch (e) {}
    }
    rbToast(`템플릿 «${t.name}» 적용 — ${n}개 항목`);
  }
  window.rbApplyTemplate = applyTemplate;
  function readCalcSettings() {
    const g = id => document.getElementById(id)?.value;
    const num = v => v === "" || v == null ? null : Number(v);
    const env = document.querySelector('input[name="env"]:checked')?.value;
    const exp = {functional: g("functional") || undefined, basis: g("basis") || null, basisAnion: g("basis-anion") || null,
                 charge: num(g("charge")) ?? 0, multiplicity: num(g("multiplicity")) ?? 1, nConformers: num(g("n-conformers")),
                 liModel: g("li-model") || null, liCoordination: num(g("li-coord")), liMaxSites: num(g("li-sites")),
                 startStructure: g("start-structure") || null,
                 torsionPattern: g("start-structure") === "pattern" ? (g("torsion-pattern") || "").trim() || null : null,
                 representative: g("start-structure") ? (g("start-rep") || "start") : null,
                 fixBackboneTorsions: g("start-structure") ? g("fix-torsions") === "true" : null};
    Object.keys(exp).forEach(k => { if (exp[k] === undefined) delete exp[k]; });
    return {envType: env, solventId: env === "진공·기체" ? null : (g("solvent") || null), temperature: num(g("temperature")) ?? 298.15,
            referenceElectrode: g("ref-electrode") || null, structure: g("structure") || "모노머", accuracy: g("accuracy") || "표준",
            purpose: g("purpose") || "전자구조(구조 최적화)", expert: exp};
  }
  async function saveTemplateFromForm(mode) {
    const name = prompt("템플릿 이름 (예: NCM811 표준 · 수계 바인더)"); if (!name) return;
    const desc = prompt("설명 (선택)", "") || "";
    if (mode === "screen") syncFields(false);
    const body = {name, desc, settings: readCalcSettings(),
                  electrodes: [...document.querySelectorAll("#scr-electrodes input:checked")].map(i => i.dataset.scrElec).filter(Boolean),
                  margin_v: Number(document.getElementById("scr-margin")?.value) || null, top_n: Number(document.getElementById("scr-keep1")?.value) || null};
    try {
      const r = await fetch("/api/templates", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
      const j = await r.json();
      if (!r.ok) { alert(j.detail || "저장 실패"); return; }
      TEMPLATES = j.templates; fillTemplateSelects(); rbToast(`템플릿 «${name}» 저장`); if (document.getElementById("rb-real")?.classList.contains("mode-tpl")) renderTemplates();
    } catch (e) { alert("저장 실패: " + e.message); }
  }
  function renderTemplates() {
    const root = document.getElementById("rbv-tpl"); if (!root) return;
    root.innerHTML = `<h1>템플릿</h1><p class="rb-note">정확도·용매·목적·전문가 설정·활물질을 묶어 이름 붙인 조건 묶음입니다. «계산» 화면 위의 템플릿 목록에서 한 번에 적용하고, «현재 조건 저장»으로 새 템플릿을 만듭니다. 사용자 템플릿은 이 서버를 쓰는 모두가 봅니다.</p>
      <div class="tpl-grid">${TEMPLATES.map(t => `<div class="tpl-card${t.builtin ? " builtin" : ""}"><div class="tpl-name">${h(t.name)} ${t.builtin ? '<span class="chip soft">기본</span>' : '<span class="chip">사용자</span>'}</div><div class="small muted">${h(t.desc || "")}</div>
        <div class="small" style="margin-top:6px">${h(t.settings?.accuracy || "")} · ${h(t.settings?.purpose || "")} · ${h(t.settings?.solventId || "진공")} · ${h(t.settings?.expert?.functional || "")}${(t.electrodes || []).length ? " · 활물질 " + t.electrodes.join(", ") : ""}</div>
        <div class="toolbar" style="margin:10px 0 0"><button class="btn primary sm" type="button" data-tpl-go="${h(t.id)}">계산에 적용</button><button class="btn sm" type="button" data-tpl-go-batch="${h(t.id)}">배치에 적용</button>${t.builtin ? "" : `<button class="btn ghost sm" type="button" data-tpl-del="${h(t.id)}">삭제</button>`}</div></div>`).join("")}
      <div class="tpl-card" style="border-style:dashed;display:flex;align-items:center;justify-content:center;color:var(--muted)">«계산» 화면에서 조건을 맞춘 뒤 «현재 조건 저장»</div></div>`;
    root.querySelectorAll("[data-tpl-go]").forEach(b => b.addEventListener("click", () => { window.rbOpenMode("calc", "계산"); setTimeout(() => applyTemplate(b.dataset.tplGo, "calc"), 150); }));
    root.querySelectorAll("[data-tpl-go-batch]").forEach(b => b.addEventListener("click", () => { window.rbOpenMode("screen", "계산"); if (window.rbScreenOpenWizard) try { window.rbScreenOpenWizard(); } catch (e) {} setTimeout(() => applyTemplate(b.dataset.tplGoBatch, "screen"), 200); }));
    root.querySelectorAll("[data-tpl-del]").forEach(b => b.addEventListener("click", async () => {
      if (!confirm("이 템플릿을 지울까요?")) return;
      const r = await fetch("/api/templates/" + encodeURIComponent(b.dataset.tplDel), {method: "DELETE"});
      if (r.ok) { TEMPLATES = (await r.json()).templates; fillTemplateSelects(); renderTemplates(); }
    }));
  }
  window.rbRenderTemplates = async () => { await loadTemplates(); renderTemplates(); };

  /* «같은 조건으로 재계산» — 결과의 설정을 계산 화면에 채운다 */
  window.rbPrefillCalc = function (job) {
    window.rbOpenMode("calc", "계산");
    setTimeout(() => {
      const n = applySettingsToCalc(job.settings || {});
      const m = job.material || {};
      const libId = m.libraryId || (m.id ? "MOL-" + String(m.id).toUpperCase() : null);
      if (libId && window.rbLibSelectInCalc) { try { window.rbLibSelectInCalc([libId]); } catch (e) {} }
      else if (m.id && window.rbSelectMaterialByName) try { window.rbSelectMaterialByName(m.name); } catch (e) {}
      if (!libId && m.smiles) { setVal("custom-smiles", m.smiles); setVal("custom-name", m.name || ""); document.getElementById("calc-custom")?.setAttribute("open", ""); }
      rbToast(`«${m.name || m.smiles}» 조건 ${n}개 항목을 채웠습니다 — 확인 후 «계산 제출»`);
    }, 200);
  };

  /* ══════════ 대시보드 ══════════ */
  async function renderDashboard() {
    const root = document.getElementById("rbv-dash"); if (!root) return;
    const jobs = (typeof JOBS_CACHE !== "undefined" ? JOBS_CACHE : []);
    const now = Date.now() / 1000, week = now - 7 * 86400;
    const running = jobs.filter(j => j.status === "RUNNING"), queued = jobs.filter(j => j.status === "QUEUED");
    const done7 = jobs.filter(j => j.status === "PUBLISHED" && (j.finishedAt || 0) > week);
    const grade = j => (j.validation || (j.result || {}).validation || {}).grade;
    const g = {PASS: 0, REVIEW: 0, FAIL: 0}; done7.forEach(j => { const k = grade(j); if (k in g) g[k]++; });
    const failed7 = jobs.filter(j => j.status === "FAILED" && (j.finishedAt || j.createdAt || 0) > week).length;
    let camps = [], bench = null;
    try { const r = await fetch("/api/screening/campaigns"); if (r.ok) camps = (await r.json()).campaigns || []; } catch (e) {}
    try { const r = await fetch("/api/benchmarks"); if (r.ok) bench = (await r.json()).sets?.[0]?.report || null; } catch (e) {}
    const runCamps = camps.filter(c => c.status === "RUNNING").length;
    const recent = [...jobs].sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0)).slice(0, 8);
    const badge = j => j.status === "RUNNING" ? `<span class="badge running">실행 ${j.progress ?? 0} %</span>` : j.status === "QUEUED" ? '<span class="badge queued">대기</span>' : j.status === "FAILED" ? '<span class="badge failed">실패</span>' : `<span class="badge ${grade(j) === "PASS" ? "published" : grade(j) === "REVIEW" ? "review" : grade(j) ? "failed" : "queued"}">${h(grade(j) || "완료")}</span>`;
    root.innerHTML = `<h1>대시보드</h1><p class="rb-note">프로젝트 전체 상황 — 실행 중인 계산, 최근 결과, 벤치마크 상태. 자주 쓰는 화면으로 바로 이동합니다.</p>
      <div class="stat-row">
        <div class="stat-tile clickable" data-go="monitor"><div class="stat-label">실행 중 · 대기</div><div class="stat-value">${running.length}<span class="stat-unit"> · ${queued.length}</span></div><div class="stat-sub">${runCamps ? `캠페인 ${runCamps}개 진행` : "캠페인 없음"} · 계산 모니터 →</div></div>
        <div class="stat-tile clickable" data-go="results"><div class="stat-label">완료 (7일)</div><div class="stat-value">${done7.length}</div><div class="stat-sub">PASS ${g.PASS} · REVIEW ${g.REVIEW} · FAIL ${g.FAIL}${failed7 ? ` · 실패 ${failed7}` : ""}</div></div>
        <div class="stat-tile clickable" data-go="calc"><div class="stat-label">새 계산</div><div class="stat-value" style="font-size:18px">분자 하나 · 배치</div><div class="stat-sub">템플릿 ${TEMPLATES.length}개 · 계산 →</div></div>
        <div class="stat-tile clickable" data-go="bench"><div class="stat-label">벤치마크</div><div class="stat-value" style="font-size:18px;color:${bench?.overall === "PASS" ? "var(--ok)" : "var(--text-1)"}">${h(bench?.overall || "—")}</div><div class="stat-sub">${bench ? `${bench.n_done}/${bench.n_total} 완료${bench.mae?.homo_ev != null ? ` · MAE HOMO ${bench.mae.homo_ev} eV` : ""}` : "세트 없음"}</div></div>
      </div>
      <div class="card"><div class="card-head"><h2>최근 작업</h2><button class="btn ghost" type="button" data-go="results">DFT 계산 결과 →</button></div>
        ${recent.length ? `<div class="scroll-x"><table class="table"><tr><th>작업</th><th>조건</th><th>진행</th><th>상태</th><th></th></tr>${recent.map(j => `<tr><td><b>${h(j.material?.name || "")}</b><div class="mono small muted">${h(j.id)}</div></td><td class="small">${h(j.result?.conditions?.method || (j.settings?.expert?.functional || "") + " · " + (j.settings?.accuracy || ""))}</td><td style="min-width:120px"><div class="progress-track"><div class="progress-fill" style="width:${j.status === "PUBLISHED" ? 100 : (j.progress || 0)}%"></div></div></td><td>${badge(j)}</td><td class="row-actions">${j.status === "PUBLISHED" ? `<button class="btn ghost" type="button" onclick="window.rbShowResultJob('${h(j.id)}')">결과</button>` : `<button class="btn ghost" type="button" onclick="window.rbOpenMonitor('${h(j.id)}')">모니터</button>`}</td></tr>`).join("")}</table></div>` : '<div class="empty small">아직 작업이 없습니다 — «계산»에서 첫 계산을 제출하세요.</div>'}</div>
      <div class="card"><div class="card-head"><h2>템플릿</h2><button class="btn ghost" type="button" data-go="tpl">관리 →</button></div>
        <div class="stat-row">${TEMPLATES.slice(0, 4).map(t => `<div class="stat-tile clickable" data-tpl="${h(t.id)}"><div class="stat-label">${h(t.name)}</div><div class="stat-sub">${h(t.desc || "")}</div></div>`).join("")}</div></div>`;
    root.querySelectorAll("[data-go]").forEach(b => b.addEventListener("click", () => window.rbOpenMode(b.dataset.go, {monitor: "계산 모니터", results: "DFT 계산 결과", calc: "계산", bench: "벤치마크", tpl: "템플릿"}[b.dataset.go] || b.dataset.go)));
    root.querySelectorAll("[data-tpl]").forEach(b => b.addEventListener("click", () => { window.rbOpenMode("calc", "계산"); setTimeout(() => applyTemplate(b.dataset.tpl, "calc"), 150); }));
  }
  window.rbRenderDash = async () => { if (!TEMPLATES.length) await loadTemplates(); renderDashboard(); };

  /* ══════════ 설정 ══════════ */
  async function renderSettings() {
    const root = document.getElementById("rbv-settings"); if (!root) return;
    let s = null;
    try { const r = await fetch("/api/settings"); if (r.ok) s = await r.json(); } catch (e) {}
    const prefs = (window.rbPrefs ? window.rbPrefs() : {});
    const b = s?.backend || {};
    const gpuOn = b.backend === "gpu";
    root.innerHTML = `<h1>설정</h1><p class="rb-note">계산 백엔드·자원은 서버 환경변수로 정하는 관리자 항목이고(여기서는 상태와 바꾸는 방법만), 단위·뷰어·테마는 이 브라우저에만 적용됩니다.</p>
      <div class="card"><div class="card-head"><h2>계산 백엔드</h2><span class="badge queued">관리자</span></div>
        ${s ? `<div class="set-switch"><span class="tg ${gpuOn ? "on" : ""}" title="환경변수 RHOBENCH_GPU 로 정합니다"><i></i></span><b>${gpuOn ? "GPU (GPU4PySCF)" : "CPU (PySCF)"}</b>
          <span class="small muted">${b.requested ? (gpuOn ? `${h(b.gpu4pyscf || "")} · ${h(b.device || "")}` : `RHOBENCH_GPU=1 이지만 GPU 를 쓸 수 없어 CPU 로 계산 중 — ${h(b.reason || "")}`) : "RHOBENCH_GPU 꺼짐 (기본)"}</span></div>` : '<div class="small muted">서버 설정을 불러오지 못했습니다.</div>'}
        <div class="small" style="margin-top:12px"><b>네이버 클라우드 GPU 서버에서 켜는 순서</b></div>
        <ol class="small" style="margin:6px 0 0 18px;padding:0;display:flex;flex-direction:column;gap:4px">
          <li>GPU 서버(NVIDIA · CUDA 12 드라이버 포함 Ubuntu 22.04)에 접속해 저장소를 받습니다.</li>
          <li>설치를 <span class="mono">./scripts/ncp_setup.sh --gpu</span> 로 합니다 — 드라이버 확인 → <span class="mono">gpu4pyscf-cuda12x</span> 설치 → 동작 검사 → <span class="mono">/etc/rhobench.env</span> 에 <span class="mono">RHOBENCH_GPU=1</span> 기록.</li>
          <li>이미 설치된 서버라면 아래 세 줄입니다.</li></ol>
        <pre class="set-code">.venv/bin/pip install gpu4pyscf-cuda12x
sudo sed -i 's/^RHOBENCH_GPU=.*/RHOBENCH_GPU=1/' /etc/rhobench.env
sudo systemctl restart rhobench</pre>
        <div class="small muted">확인: 새 작업 로그 첫 줄 «계산 백엔드: GPU (…)», 결과의 재현성 정보 <span class="mono">backend: gpu</span>. GPU 가 없으면 자동으로 CPU 로 돕니다. 연구실 PC(WSL)는 <span class="mono">RHOBENCH_GPU=1 ./scripts/start.sh --background</span>.</div></div>
      <div class="card"><div class="card-head"><h2>자원 · 엔진</h2><span class="badge queued">읽기 전용</span></div>
        ${s ? `<table class="kv-table"><tr><th>동시 계산 워커</th><td>${s.workers} <span class="muted small">(RHOBENCH_WORKERS)</span></td></tr><tr><th>동시 작업 상한</th><td>${s.limits.max_active_jobs} <span class="muted small">(RHOBENCH_MAX_ACTIVE_JOBS)</span></td></tr><tr><th>원자 수 상한</th><td>${s.limits.max_atoms} <span class="muted small">(RHOBENCH_MAX_ATOMS)</span></td></tr><tr><th>배치 동시 캠페인 · 후보 상한</th><td>${s.limits.batch_parallel} · ${s.limits.max_batch}</td></tr><tr><th>엔진</th><td>PySCF ${h(s.engine.pyscf)} · Python ${h(s.engine.python)}</td></tr><tr><th>코드</th><td class="mono">${h(s.code)}</td></tr><tr><th>저장 위치</th><td class="mono small">${h(s.data_dir)}</td></tr>${s.env_file ? `<tr><th>환경 파일</th><td class="mono small">${h(s.env_file)}</td></tr>` : ""}</table>` : ""}</div>
      <div class="card"><div class="card-head"><h2>표시 · 뷰어 · 테마</h2><span class="badge queued">이 브라우저</span></div>
        <div class="form-grid">
          <div class="field"><span class="field-label">에너지 단위 (결과 요약 카드)</span><select class="input" id="set-unit"><option value="eV">eV</option><option value="Hartree">Hartree</option><option value="kJ/mol">kJ/mol</option></select></div>
          <div class="field"><span class="field-label">전위 규약 (기록·판정)</span><select class="input" id="set-conv" disabled><option>${h(s?.potential_conventions?.[0] || "Li/Li⁺ 1.44 V")}</option></select><span class="small muted">계산·캠페인 설정에서 작업마다 지정</span></div>
          <div class="field"><span class="field-label">뷰어 기본 표현</span><select class="input" id="set-view"><option value="element">구조</option><option value="homo">HOMO</option><option value="cloud">전자밀도</option><option value="charge">부분 전하</option></select></div>
          <div class="field"><span class="field-label">테마</span><select class="input" id="set-theme"><option value="system">시스템</option><option value="light">라이트</option><option value="dark">다크</option></select><span class="small muted">화면 색 세부 설정은 «시각화 · 계정»</span></div>
        </div></div>`;
    const u = document.getElementById("set-unit"); u.value = prefs.energyUnit || "eV"; u.addEventListener("change", () => { const p = window.rbPrefs(); p.energyUnit = u.value; window.rbSavePrefs(p); rbToast("에너지 단위: " + u.value); });
    const v = document.getElementById("set-view"); v.value = prefs.viewMode || "element"; v.addEventListener("change", () => { const p = window.rbPrefs(); p.viewMode = v.value; window.rbSavePrefs(p); });
    const t = document.getElementById("set-theme"); t.value = prefs.theme || "system"; t.addEventListener("change", () => { const p = window.rbPrefs(); p.theme = t.value; window.rbSavePrefs(p); applyTheme(); });
  }
  function applyTheme() {
    const th = (window.rbPrefs ? window.rbPrefs() : {}).theme || "system";
    const root = document.documentElement;
    if (th === "dark") root.setAttribute("data-mode", "dark");
    else if (th === "light") root.removeAttribute("data-mode");
    else if (matchMedia("(prefers-color-scheme: dark)").matches) root.setAttribute("data-mode", "dark"); else root.removeAttribute("data-mode");
  }
  window.rbRenderSettings = renderSettings;
  if (window.rbPrefs && (window.rbPrefs().theme || "system") !== "system") applyTheme();

  /* ══════════ 튜토리얼 ══════════ */
  const TUT = [
    ["분자 고르기", "«계산» 화면에서 프리셋 카드 «아크릴로나이트릴(AN)»을 누릅니다. SMILES 를 직접 넣거나 3D 파일을 올려도 됩니다.", "calc", "s6-1"],
    ["조건 정하기", "정확도 «빠름», 목적 «전자구조 + 산화/환원 전위». 용매는 EC/DMC 1:1 로 둡니다.", "calc", "s6-3"],
    ["제출하고 진행 보기", "«계산 제출»을 누르면 결과 화면으로 넘어갑니다. 진행률과 단계가 올라가고, «계산 모니터»에서 SCF 잔차를 볼 수 있습니다.", "monitor", "s10-1"],
    ["결과 읽기", "상태가 PUBLISHED 가 되면 «결과 보기». 뷰어에서 HOMO·LUMO 탭을 눌러 궤도를 보고, 결과 요약의 QC 배지와 «안정 창» 탭을 확인합니다.", "results", "s7-4"],
    ["비교하고 공유하기", "«물질 비교»에 체크해 여러 결과를 나란히 놓고, «DFT 계산 결과 → HTML로 공유»로 파일 하나를 만듭니다.", "compare", "ch11"],
  ];
  function renderTutorial() {
    const root = document.getElementById("rbv-tut"); if (!root) return;
    const done = (window.rbPrefs ? window.rbPrefs() : {}).tutorialDone || [];
    root.innerHTML = `<h1>튜토리얼</h1><p class="rb-note">사용 설명서 3장 «10분 빠른 시작»을 화면 안에서 따라갑니다. 각 단계의 «화면 열기»로 이동하고 «? 설명»으로 해당 절을 봅니다. 완료 표시는 이 브라우저에 저장됩니다.</p>
      <div class="card"><ol class="tut">${TUT.map((t, i) => `<li class="${done.includes(i) ? "done" : ""}"><i>${done.includes(i) ? "✓" : i + 1}</i><div><b>${h(t[0])}</b><div class="small" style="color:var(--text-2)">${h(t[1])}</div>
        <div class="toolbar" style="margin:6px 0 0"><button class="btn sm" type="button" data-tut-go="${t[2]}">화면 열기</button><button class="btn ghost sm" type="button" data-tut-help="${t[3]}">? 설명</button><button class="btn ghost sm" type="button" data-tut-done="${i}">${done.includes(i) ? "완료 취소" : "완료 표시"}</button></div></div></li>`).join("")}</ol></div>`;
    root.querySelectorAll("[data-tut-go]").forEach(b => b.addEventListener("click", () => window.rbOpenMode(b.dataset.tutGo, {calc: "계산", monitor: "계산 모니터", results: "DFT 계산 결과", compare: "물질 비교"}[b.dataset.tutGo])));
    root.querySelectorAll("[data-tut-help]").forEach(b => b.addEventListener("click", () => { if (window.rbHelp) window.rbHelp(b.dataset.tutHelp); }));
    root.querySelectorAll("[data-tut-done]").forEach(b => b.addEventListener("click", () => { const p = window.rbPrefs(); const i = Number(b.dataset.tutDone); const d = new Set(p.tutorialDone || []); d.has(i) ? d.delete(i) : d.add(i); p.tutorialDone = [...d]; window.rbSavePrefs(p); renderTutorial(); }));
  }
  window.rbRenderTutorial = renderTutorial;

  window.rbScreenOpenWizard = function () {
    const wiz = document.getElementById("scr-wizard"), btn = document.getElementById("scr-new-btn");
    if (wiz && (wiz.hidden || getComputedStyle(wiz).display === "none") && btn) btn.click();
  };

  /* ══════════ 시작 ══════════ */
  function boot() {
    if (!document.getElementById("rbv-calc")) return;
    installModeBars();
    if (!IS_SNAPSHOT) loadTemplates(); else TEMPLATES = [];
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
