/* ------------------------------------------------------------------
   분자 라이브러리 · 분자 검색 및 선택 (기획서 «QuantumLab 분자 라이브러리·검색 및 선택 화면» 반영)

   · 서버 저장 라이브러리(/api/library) — 예전 물질 보관함·용매 라이브러리(브라우저 저장)를 대체한다.
     처음 열 때 브라우저에 남은 사용자 보관함·혼합 용매를 서버로 한 번 옮긴다.
   · «분자 검색 및 선택»(#rbv-molsearch): 이름 / 구조 완전 일치 / 유사도 / 부분구조 검색, SMILES·InChI 검증,
     결과 표 · 선택 분자 패널 · 빠른 계산 템플릿 · 계산 환경(단일/혼합 용매 비율) 카드
   · «분자 라이브러리»(#rbv-library): 카테고리 탭 · 필터 · 카드/목록 · 미리보기(개요·구조·계산 이력) · 분자 등록
   · 계산 화면 연결: 소재 카드 · 용매 선택(라이브러리 단일 용매 / 혼합 프리셋 / 직접 구성) · 명시적 분자 목록
   선택함(여러 분자)과 계산 환경은 두 화면이 공유한다 (브라우저 저장 — 사용자별 편의 상태).
   app.js 뒤에 로드된다 ($, esc, fmt, JOBS_CACHE, COMPARE_SEL, selected, render3D 는 전역).
   ------------------------------------------------------------------ */
(function () {
  const IS_SNAPSHOT = !!window.__RB_SNAPSHOT__;
  const h = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const LS = {
    get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
  };
  const toast = m => { if (window.rbToast) window.rbToast(m); };
  const nf = (v, d = 2) => v == null || isNaN(v) ? "—" : Number(v).toFixed(d);
  const CAT_LABEL = {monomer: "바인더 모노머", polymer: "고분자·올리고머", solvent: "용매", additive: "첨가제", salt: "리튬염·이온", other: "기타"};
  const ROLE_LABEL = {solute: "용질", solvent: "용매"};
  const TEMPLATES = {opt: ["구조 최적화", "Geometry"], sp: ["단일점", "Single point"], orb: ["오비탈 분석", "HOMO / LUMO"]};

  const L = window.RBLIB = {
    data: null, by: {}, loading: null,
    sel: LS.get("rb-lib-sel", []),
    env: LS.get("rb-lib-env", null) || {mode: "implicit", basis: "부피비", comps: [{id: "MOL-EC", ratio: 1}, {id: "MOL-DMC", ratio: 1}], explicit: 2},
    ext: LS.get("rb-lib-ext", {structure: "모노머", liModel: ""}),
    tpl: null,
    ui: {cat: "all", q: "", f: {role: [], el: [], groups: [], charge: [], calc: [], src: []}, mw: 400, sort: "recent", grid: "grid", preview: null, ptab: "overview",
         mode: "name", sq: "", kind: "smiles", stereo: false, salts: true, thr: 0.35, rows: null, note: "", tq: "", tstate: "", tsort: "score", focus: null, spanel3d: false},
  };
  const saveSel = () => LS.set("rb-lib-sel", L.sel);
  const saveEnv = () => LS.set("rb-lib-env", L.env);
  const saveExt = () => LS.set("rb-lib-ext", L.ext);

  /* ── 데이터 ── */
  async function load(force) {
    if (L.data && !force) return L.data;
    if (!L.loading || force) {
      L.loading = fetch("/api/library").then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(new Error(e.detail || "HTTP " + r.status))))
        .then(d => { L.data = d; L.by = Object.fromEntries(d.molecules.map(m => [m.id, m])); L.sel = L.sel.filter(id => L.by[id]); saveSel(); return d; })
        .catch(e => {
          L.loading = null;
          // 서버에 /api/library 가 없으면(예전 버전 서버) 계산 화면은 예전 방식(프리셋·브라우저 보관함)으로 되돌린다
          if (/404|Not Found/i.test(e.message) && !L.failed) {
            L.failed = true;
            try { if (typeof buildMaterialGrid === "function") buildMaterialGrid(); if (typeof buildSolventOptions === "function") buildSolventOptions(); } catch (x) {}
          }
          throw e;
        });
    }
    const d = await L.loading;
    if (!IS_SNAPSHOT && !LS.get("rb-lib-migrated", false)) migrateBrowser();
    return d;
  }
  L.load = load;
  const mols = () => (L.data ? L.data.molecules : []);
  const mixes = () => (L.data ? L.data.mixtures : []);
  const solvents = () => mols().filter(m => m.solvent);
  const rec = id => L.by[id];

  /* 예전 브라우저 보관함·용매 라이브러리 → 서버 라이브러리 (한 번) */
  async function migrateBrowser() {
    LS.set("rb-lib-migrated", true);
    const items = [];
    const catOf = t => /용매/.test(t || "") ? "solvent" : /염|salt/i.test(t || "") ? "salt" : /첨가/.test(t || "") ? "additive" : /모노머|바인더|고분자/.test(t || "") ? "monomer" : "other";
    try {
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (!k || !k.startsWith("dft-workbench")) continue;
        const v = JSON.parse(localStorage.getItem(k));
        for (const m of (v && v.materials) || []) if (m && m.smiles && !m.builtin) items.push({name: m.name, smiles: m.smiles, category: catOf(m.type), tags: ["브라우저 보관함"]});
        for (const s of (v && v.solvents) || []) if (s && s.kind === "mixed" && !s.builtin && (s.components || []).length >= 2)
          items.push({mixture: {name: s.abbr || s.name, basis: "부피비", components: s.components.map(c => ({abbr: c.abbr, ratio: c.ratio}))}});
      }
    } catch (e) { return; }
    if (!items.length) return;
    try {
      const r = await fetch("/api/library/import", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({items})});
      if (!r.ok) return;
      const out = await r.json();
      if (out.added || out.mixtures) { toast(`예전 브라우저 보관함에서 분자 ${out.added}개 · 혼합 용매 ${out.mixtures}개를 분자 라이브러리로 옮겼습니다`); await load(true); rerender(); }
    } catch (e) {}
  }

  /* ── 공통 조각 ── */
  function calcState(m) {
    const js = m.jobs || [];
    if (js.some(j => j.status === "RUNNING" || j.status === "QUEUED")) return ["running", "계산 중"];
    if (js.some(j => j.status === "PUBLISHED")) return ["published", "계산 완료"];
    if (js.length) return ["failed", "실패"];
    return ["queued", "미계산"];
  }
  const lastDone = m => (m.jobs || []).find(j => j.status === "PUBLISHED") || null;
  const svgOf = (m, cls = "") => `<span class="lb-svg ${cls}">${m.svg || `<span class="small muted">${h(m.formula)}</span>`}</span>`;
  const fmtFormula = f => h(f || "").replace(/(\d+)/g, "<sub>$1</sub>");
  const when = t => t ? new Date(t * 1000).toLocaleString("ko-KR", {month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false}) : "";
  const gradeBadge = j => `<span class="badge ${j.grade === "PASS" ? "published" : j.grade === "REVIEW" ? "review" : j.grade || j.status === "FAILED" ? "failed" : j.status === "PUBLISHED" ? "published" : "running"}">${h(j.grade || (j.status === "PUBLISHED" ? "완료" : j.status === "FAILED" ? "실패" : j.status === "QUEUED" ? "대기" : `실행 ${j.progress ?? 0}%`))}</span>`;
  const jobLink = (j, short) => `<a class="btn ghost sm lb-joblink" data-job="${h(j.id)}" title="${h(j.id)} — 결과·모니터 열기">${h(short ? "…" + j.id.slice(-6) : j.id)}</a>`;
  function wireJobLinks(root) {
    root.querySelectorAll("[data-job]").forEach(a => a.addEventListener("click", e => {
      e.stopPropagation();
      const id = a.dataset.job, j = (typeof JOBS_CACHE !== "undefined" ? JOBS_CACHE : []).find(x => x.id === id);
      if (j && j.status === "PUBLISHED" && window.rbShowResultJob) window.rbShowResultJob(id);
      else if (window.rbOpenMonitor) window.rbOpenMonitor(id);
    }));
  }

  /* ── 유효 매질 (서버 library.resolve_mixture 와 같은 식) ── */
  function effMedium(env) {
    const comps = (env.comps || []).filter(c => +c.ratio > 0 && rec(c.id) && rec(c.id).solvent);
    if (!comps.length) return {ok: false, error: "용매 성분이 없습니다", comps: []};
    const ids = comps.map(c => c.id);
    if (new Set(ids).size !== ids.length) return {ok: false, error: "같은 용매 성분이 두 번 들어 있습니다", comps};
    const basis = env.basis || "부피비", tot = comps.reduce((s, c) => s + +c.ratio, 0);
    const vol = [];
    for (const c of comps) {
      const m = rec(c.id), f = +c.ratio / tot;
      if (basis === "부피비") vol.push(f);
      else {
        if (!m.solvent.density) return {ok: false, error: `${basis}로 환산하려면 ${m.name} 의 밀도가 필요합니다 — 라이브러리에서 밀도를 입력하세요`, comps};
        vol.push(f * (basis === "몰비" ? m.mw : 1) / m.solvent.density);
      }
    }
    const vt = vol.reduce((s, v) => s + v, 0), w = vol.map(v => v / vt);
    const vec = [0, 1, 2, 3, 4, 5, 6, 7].map(i => comps.reduce((s, c, k) => s + w[k] * rec(c.id).solvent.vec[i], 0));
    const auto = comps.map(c => rec(c.id).name).join("/") + (comps.length > 1 ? " " + comps.map(c => +c.ratio).join(":") : "");
    return {ok: true, comps, w, vec, eps: vec[5], n: vec[0], alpha: vec[2], beta: vec[3], gamma: vec[4], basis, name: (env.name || "").trim() || auto};
  }
  /* 현재 구성 → 계산 설정 값 (solventId 또는 customMixedSolvent) */
  function envToSettings(env) {
    if (env.mode === "vacuum") return {envType: "진공·기체", solventId: null, customMixedSolvent: null};
    const eff = effMedium(env);
    if (!eff.ok) return {envType: "사용자 정의", error: eff.error};
    if (eff.comps.length === 1) { const m = rec(eff.comps[0].id); return {envType: "사용자 정의", solventId: m.solventId || m.id, customMixedSolvent: null, label: m.name}; }
    const same = mixes().find(x => x.basis === eff.basis && x.components.length === eff.comps.length
      && x.components.every(c => eff.comps.some(e => e.id === c.id && Math.abs(+e.ratio / eff.comps.reduce((s, q) => s + +q.ratio, 0) - c.ratio / x.components.reduce((s, q) => s + q.ratio, 0)) < 1e-6)));
    if (same) return {envType: "사용자 정의", solventId: same.presetSolventId || same.id, customMixedSolvent: null, label: same.name};
    return {envType: "사용자 정의", solventId: null, customMixedSolvent: {name: eff.name, basis: eff.basis, components: eff.comps.map(c => ({id: c.id, ratio: +c.ratio}))}, label: eff.name};
  }
  function envLabel(env) {
    if (env.mode === "vacuum") return "진공";
    const eff = effMedium(env);
    return eff.ok ? `${eff.name}${eff.comps.length > 1 ? " (" + eff.basis + ")" : ""} · ε ${nf(eff.eps, 1)}${env.mode === "cluster" ? " · 명시적 " + env.explicit + "개" : ""}` : "용매 구성 오류";
  }
  /* 명시적 분자 배분 — 부피분율에 따라 N개를 성분별로 (최대 나머지 방식) */
  function explicitSplit(env) {
    const eff = effMedium(env); if (!eff.ok) return [];
    const n = Math.max(1, Math.min(10, +env.explicit || 1));
    const raw = eff.w.map(x => x * n), base = raw.map(Math.floor);
    let left = n - base.reduce((s, v) => s + v, 0);
    raw.map((v, i) => [v - base[i], i]).sort((a, b) => b[0] - a[0]).forEach(([, i]) => { if (left > 0) { base[i]++; left--; } });
    return eff.comps.map((c, i) => ({smiles: rec(c.id).smiles, name: rec(c.id).name, count: base[i]})).filter(x => x.count > 0);
  }

  /* ── 혼합 용매 편집기 (계산 환경 카드 · 계산 화면 공용) ── */
  function composerHtml(env, opts = {}) {
    const eff = effMedium(env), sv = solvents(), colors = ["#0f766e", "#2a78d6", "#d97706", "#8a3fc4", "#e34948", "#1baf7a"];
    const opt = sel => sv.map(m => `<option value="${h(m.id)}" ${m.id === sel ? "selected" : ""}>${h(m.name)} · ${h(m.full || "")} (ε ${nf(m.solvent.eps, 1)})</option>`).join("");
    return `<div class="lb-comp lb-comp-head"><span>성분 (분자 라이브러리 · 용매 역할)</span><span>비율</span><span style="text-align:right">부피분율</span><span></span></div>
      ${(env.comps || []).map((c, i) => { const k = eff.ok ? eff.comps.indexOf(c) : -1; return `<div class="lb-comp"><select class="input" data-ci="${i}">${opt(c.id)}</select><input class="input" type="number" min="0" step="0.5" value="${h(c.ratio)}" data-cr="${i}"><span class="lb-pct">${k >= 0 ? (eff.w[k] * 100).toFixed(1) + "%" : "—"}</span><button class="btn ghost sm" type="button" data-cx="${i}" title="성분 빼기" ${(env.comps || []).length <= 1 ? "disabled" : ""}>✕</button></div>`; }).join("")}
      <div class="toolbar" style="margin:6px 0 0;gap:8px"><button class="btn sm" type="button" data-cadd="1" ${(env.comps || []).length >= 6 ? "disabled" : ""}>+ 성분 추가</button>
        <span class="small muted">비율 기준</span><span class="seg">${(L.data?.bases || ["부피비", "몰비", "질량비"]).map(b => `<button type="button" class="${env.basis === b ? "on" : ""}" data-cb="${b}">${b}</button>`).join("")}</span>
        <input class="input" data-cname="1" placeholder="이름 (비우면 자동)" value="${h(env.name || "")}" style="max-width:190px"></div>
      <div class="lb-bar">${eff.ok ? eff.comps.map((c, i) => `<i style="width:${eff.w[i] * 100}%;background:${colors[i % 6]}" title="${h(rec(c.id).name)} ${(eff.w[i] * 100).toFixed(1)}%"></i>`).join("") : ""}</div>
      ${eff.ok ? "" : `<div class="form-error" style="margin:0 0 6px">${h(eff.error)}</div>`}
      <div class="lb-presets"><span class="small muted">프리셋</span>${mixes().map(x => `<button type="button" data-cp="${h(x.id)}" title="${h(x.note || "")}">${h(x.name)}${x.builtin ? "" : " ★"}</button>`).join("")}${sv.map(m => `<button type="button" data-cs="${h(m.id)}">${h(m.name)}</button>`).join("")}
        ${opts.save && !IS_SNAPSHOT ? `<button type="button" data-csave="1" class="lb-save" ${eff.ok && eff.comps.length > 1 ? "" : "disabled"}>이 혼합을 프리셋으로 저장</button>` : ""}</div>`;
  }
  function effTable(env, opts = {}) {
    const eff = effMedium(env);
    if (env.mode === "vacuum") return '<div class="small muted">용매 없음 — 기체상 계산</div>';
    if (!eff.ok) return `<div class="form-error">${h(eff.error)}</div>`;
    // opts.raw: 계산 화면 «직접 구성» — 프리셋과 같아도 성분·비율 그대로 전송되므로 그 값을 보여 준다
    const st = opts.raw ? {customMixedSolvent: {name: eff.name, basis: eff.basis, components: eff.comps.map(c => ({id: c.id, ratio: +c.ratio}))}} : envToSettings(env);
    return `<table class="kv-table"><tr><th>이름</th><td>${h(eff.name)}${eff.comps.length > 1 ? ` <span class="small muted">(${h(eff.basis)})</span>` : ""}</td></tr>
      <tr><th>유전율 ε</th><td><b>${nf(eff.eps, 2)}</b> <span class="small muted">${eff.comps.length > 1 ? "부피분율 가중 평균 (유효 매질 근사)" : "단일 용매 SMD 값"}</span></td></tr>
      <tr><th>굴절률 n</th><td>${nf(eff.n, 4)}</td></tr><tr><th>H-결합 α / β</th><td>${nf(eff.alpha, 2)} / ${nf(eff.beta, 2)}</td></tr><tr><th>표면장력 γ</th><td>${nf(eff.gamma, 1)} cal/mol·Å²</td></tr>
      <tr><th>계산 설정 값</th><td class="mono small" style="word-break:break-all">${st.customMixedSolvent ? h(`customMixedSolvent = ${JSON.stringify(st.customMixedSolvent)}`) : h(`solventId = "${st.solventId}"`)}</td></tr></table>
      ${eff.comps.length > 1 ? `<p class="small muted" style="margin:6px 0 0">혼합 ε 는 성분 SMD 파라미터의 부피분율 가중 평균이며 실제 혼합물 측정값과 다를 수 있습니다.${eff.basis !== "부피비" ? " 몰비·질량비는 몰질량과 라이브러리에 등록된 밀도로 부피분율로 환산했습니다." : ""}</p>` : ""}`;
  }
  function wireComposer(root, env, onChange, opts = {}) {
    const ch = () => { onChange(); };
    // 프리셋에서 가져온 이름은 성분·비율을 바꾸면 자동 이름으로 되돌린다 (직접 입력한 이름은 유지)
    const edited = () => { if (env.nameAuto) { env.name = ""; env.nameAuto = false; } };
    root.querySelectorAll("[data-ci]").forEach(s => s.addEventListener("change", () => { env.comps[+s.dataset.ci].id = s.value; edited(); ch(); }));
    root.querySelectorAll("[data-cr]").forEach(i => i.addEventListener("change", () => { env.comps[+i.dataset.cr].ratio = Math.max(0, +i.value || 0); edited(); ch(); }));
    root.querySelectorAll("[data-cx]").forEach(b => b.addEventListener("click", () => { env.comps.splice(+b.dataset.cx, 1); edited(); ch(); }));
    root.querySelectorAll("[data-cb]").forEach(b => b.addEventListener("click", () => { env.basis = b.dataset.cb; edited(); ch(); }));
    const nm = root.querySelector("[data-cname]"); if (nm) nm.addEventListener("change", () => { env.name = nm.value.trim(); env.nameAuto = false; ch(); });
    const add = root.querySelector("[data-cadd]"); if (add) add.addEventListener("click", () => { const used = new Set(env.comps.map(c => c.id)); const m = solvents().find(x => !used.has(x.id)); if (m) env.comps.push({id: m.id, ratio: 1}); edited(); ch(); });
    root.querySelectorAll("[data-cp]").forEach(b => b.addEventListener("click", () => { const x = mixes().find(m => m.id === b.dataset.cp); if (!x) return; env.comps = x.components.map(c => ({id: c.id, ratio: c.ratio})); env.basis = x.basis; env.name = x.name; env.nameAuto = true; if (env.mode === "vacuum") env.mode = "implicit"; ch(); }));
    root.querySelectorAll("[data-cs]").forEach(b => b.addEventListener("click", () => { env.comps = [{id: b.dataset.cs, ratio: 1}]; env.name = ""; env.nameAuto = false; if (env.mode === "vacuum") env.mode = "implicit"; ch(); }));
    const sv = root.querySelector("[data-csave]"); if (sv) sv.addEventListener("click", async () => {
      const eff = effMedium(env); if (!eff.ok) return;
      const name = prompt("혼합 용매 프리셋 이름", eff.name); if (!name) return;
      const r = await fetch("/api/library/mixtures", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({name, basis: eff.basis, components: eff.comps.map(c => ({id: c.id, ratio: +c.ratio}))})});
      const out = await r.json().catch(() => ({}));
      if (!r.ok) { alert(out.detail || "저장하지 못했습니다"); return; }
      env.name = name; await load(true); toast(`혼합 용매 «${name}» 저장 — 계산·배치 스크리닝의 용매 목록에도 나타납니다`); ch(); if (opts.after) opts.after();
    });
  }

  /* ── 창 크기 조절 — 세로 분할선(열 너비) · 가로 분할선(높이). 값은 브라우저에 저장, 두 번 누르면 기본값 ── */
  const LAYOUT_DEF = {msL: 320, msR: 380, msH: 0, libF: 210, libP: 420};
  const layout = () => Object.assign({}, LAYOUT_DEF, LS.get("rb-lib-layout", {}));
  function applyLayout(grid, keys) {
    const lay = layout();
    if (lay.msH) grid.style.setProperty("--ms-h", lay.msH + "px");
    // 왼쪽·오른쪽 열 너비 — 화면보다 넓으면 가운데 최소 폭(320px)을 남기도록 비율대로 줄이고,
    // 그래도 모자라면(좁은 화면) 한 줄로 쌓는다 (분할선 숨김)
    const sides = keys.filter(k => k[0] !== "msH");
    const hs = sides.map(([k]) => grid.querySelector(`[data-sp="${k}"]`));
    const mins = hs.map(hd => +(hd?.dataset.min || 180));
    let w = sides.map(([k]) => lay[k] || LAYOUT_DEF[k]);
    const avail = grid.clientWidth - 12 * sides.length - (+(grid.dataset.midMin || 320));
    if (grid.clientWidth > 0 && w.reduce((a, b) => a + b, 0) > avail) { const f = avail / w.reduce((a, b) => a + b, 0); w = w.map(x => Math.round(x * f)); }
    const stack = grid.clientWidth > 0 && w.some((x, i) => x < mins[i]);
    grid.classList.toggle("lb-stack", stack);
    sides.forEach(([, cssVar], i) => grid.style.setProperty(cssVar, w[i] + "px"));
    // 가운데 열이 좁으면(결과 표 이름 칸이 사라질 폭) 보조 칸을 숨긴다
    const mid = stack ? grid.clientWidth : grid.clientWidth - 12 * sides.length - w.reduce((a, b) => a + b, 0);
    grid.classList.toggle("lb-midnarrow", grid.clientWidth > 0 && mid < 540);
  }
  function initSplits(grid, keys) {
    if (grid.dataset.splitInit) { applyLayout(grid, keys); return; }
    grid.dataset.splitInit = "1";
    applyLayout(grid, keys);
    if (window.ResizeObserver) new ResizeObserver(() => applyLayout(grid, keys)).observe(grid);
    grid.querySelectorAll("[data-sp]").forEach(hd => {
      const key = hd.dataset.sp, sign = +(hd.dataset.sign || 1), min = +(hd.dataset.min || 180), max = +(hd.dataset.max || 900);
      hd.title = "끌어서 창 너비 조절 · 두 번 누르면 기본값";
      hd.addEventListener("dblclick", () => { const lay = LS.get("rb-lib-layout", {}); delete lay[key]; LS.set("rb-lib-layout", lay); grid.style.removeProperty(keys.find(k => k[0] === key)[1]); applyLayout(grid, keys); });
      hd.addEventListener("pointerdown", e => {
        e.preventDefault(); hd.setPointerCapture(e.pointerId); hd.classList.add("on");
        const cssVar = keys.find(k => k[0] === key)[1], x0 = e.clientX, w0 = parseFloat(getComputedStyle(grid).getPropertyValue(cssVar)) || layout()[key] || LAYOUT_DEF[key];
        const other = keys.filter(k => k[0] !== key && k[0] !== "msH").reduce((t, [k]) => t + (parseFloat(getComputedStyle(grid).getPropertyValue(keys.find(x => x[0] === k)[1])) || LAYOUT_DEF[k]), 0);
        const room = grid.clientWidth - other - 24 - 320;
        const move = ev => { const w = Math.round(Math.max(min, Math.min(max, room, w0 + sign * (ev.clientX - x0)))); grid.style.setProperty(cssVar, w + "px"); hd.dataset.w = w; };
        const up = () => { hd.classList.remove("on"); hd.removeEventListener("pointermove", move); hd.removeEventListener("pointerup", up); if (hd.dataset.w) { const lay = LS.get("rb-lib-layout", {}); lay[key] = +hd.dataset.w; LS.set("rb-lib-layout", lay); } };
        hd.addEventListener("pointermove", move); hd.addEventListener("pointerup", up);
      });
    });
    const hs = grid.parentNode.querySelector(`[data-hs="${grid.id}"]`);
    if (hs) {
      hs.title = "끌어서 창 높이 조절 · 두 번 누르면 기본값";
      hs.addEventListener("dblclick", () => { const lay = LS.get("rb-lib-layout", {}); delete lay.msH; LS.set("rb-lib-layout", lay); grid.style.removeProperty("--ms-h"); });
      hs.addEventListener("pointerdown", e => {
        e.preventDefault(); hs.setPointerCapture(e.pointerId); hs.classList.add("on");
        const y0 = e.clientY, h0 = grid.getBoundingClientRect().height;
        const move = ev => { const hh = Math.max(380, Math.min(1600, h0 + ev.clientY - y0)); grid.style.setProperty("--ms-h", hh + "px"); hs.dataset.h = hh; };
        const up = () => { hs.classList.remove("on"); hs.removeEventListener("pointermove", move); hs.removeEventListener("pointerup", up); if (hs.dataset.h) { const lay = LS.get("rb-lib-layout", {}); lay.msH = +hs.dataset.h; LS.set("rb-lib-layout", lay); } };
        hs.addEventListener("pointermove", move); hs.addEventListener("pointerup", up);
      });
    }
  }
  const MS_KEYS = [["msL", "--ms-l"], ["msR", "--ms-r"], ["msH", "--ms-h"]];
  const LIB_KEYS = [["libF", "--lib-f"], ["libP", "--lib-p"]];

  /* 계산 화면에 넣을 분자를 고르는 중 — 두 화면 위에 안내 막대 */
  function renderPickBar(rootId) {
    const root = document.getElementById(rootId); if (!root) return;
    let bar = root.querySelector(".lb-pickbar");
    if (!L.pickForCalc) { if (bar) bar.remove(); return; }
    if (!bar) { bar = document.createElement("div"); bar.className = "banner success lb-pickbar"; root.prepend(bar); }
    bar.innerHTML = `<b>계산 화면에 넣을 분자를 고르는 중</b> — 체크하거나 «선택»을 누르면 선택함에 담깁니다. 선택함 <b>${L.sel.length}</b>개
      <span class="sp"><button class="btn primary sm" type="button" data-pk="go" ${L.sel.length ? "" : "disabled"}>계산 화면에 넣기 →</button><button class="btn sm" type="button" data-pk="cancel">취소</button></span>`;
    bar.querySelector('[data-pk="go"]').onclick = () => { const ids = L.sel.slice(); L.pickForCalc = false; window.rbOpenMode("calc", "계산"); load().then(() => { rbLibAddToCalc(ids); toast(`분자 ${ids.length}개를 계산 화면에 넣었습니다`); }); };
    bar.querySelector('[data-pk="cancel"]').onclick = () => { L.pickForCalc = false; window.rbOpenMode("calc", "계산"); };
  }

  /* ══════════ 분자 검색 및 선택 ══════════ */
  const MODE_NOTE = {
    name: "이름·약어·CAS·화학식·태그 검색 — 같은 화학식의 이성질체는 각각 다른 행으로 나옵니다. SMILES 를 넣으면 구조 일치도 함께 찾습니다.",
    exact: "구조 완전 일치 — InChIKey 로 비교합니다. 기본: 입체 무시(연결성) · 염·용매화물은 가장 큰 조각으로.",
    sim: "유사도 — Morgan 지문(r=2, 2048 bit) Tanimoto 점수순. 유사도가 «같은 구조»를 뜻하지는 않습니다.",
    sub: "부분구조 — 입력 모티프(SMILES/SMARTS)를 포함하는 분자. 일치한 원자·결합을 구조에서 강조합니다.",
  };
  let searchTimer = null, parseTimer = null;
  async function runSearch() {
    const u = L.ui, q = u.sq.trim();
    if (IS_SNAPSHOT || (u.mode === "name" && !q)) {
      const ql = q.toLowerCase();
      u.rows = mols().filter(m => !ql || [m.name, m.full, m.formula, m.cas, m.smiles, ...(m.tags || [])].join(" ").toLowerCase().includes(ql)).map(m => ({id: m.id, score: 0}));
      u.note = IS_SNAPSHOT && u.mode !== "name" ? "공유용 사본에서는 구조 검색을 할 수 없습니다 (이름 검색만)" : q ? "" : "전체 목록 — 검색어를 넣거나 구조 검색 탭을 쓰세요";
      renderTable(); return;
    }
    if (u.mode !== "name" && !q) { u.rows = []; u.note = "SMILES 또는 SMARTS 를 입력하세요"; renderTable(); return; }
    try {
      const r = await fetch("/api/library/search", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({mode: u.mode, query: q, threshold: u.thr, stereo: u.stereo, stripSalts: u.salts})});
      const out = await r.json();
      if (!r.ok) throw new Error(out.detail || "HTTP " + r.status);
      u.rows = out.rows; u.note = out.error || out.note || "";
      if (q) { const rec = LS.get("rb-lib-recent", []).filter(x => x.q !== q); rec.unshift({q, mode: u.mode, t: Date.now()}); LS.set("rb-lib-recent", rec.slice(0, 8)); }
    } catch (e) { u.rows = []; u.note = "검색 실패 — " + e.message; }
    renderTable(); renderRecent();
  }
  async function runParse() {
    const box = document.getElementById("lb-parse"); if (!box) return;
    const q = L.ui.sq.trim(), u = L.ui;
    const smilesish = u.mode !== "name" || /[=#()\[\]@]|\d/.test(q);
    if (!q || !smilesish || IS_SNAPSHOT) { box.innerHTML = ""; setGoEnabled(); return; }
    try {
      const r = await fetch("/api/library/parse", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({text: q, kind: u.kind})});
      const p = await r.json(); L.ui.parsed = p;
      if (!p.ok) {
        box.innerHTML = u.mode === "sub" ? `<div class="small muted">SMARTS 패턴으로 검색합니다 (SMILES 검증 생략)</div>` : `<div class="form-error" style="margin:0">✗ ${h(p.error)}</div><div class="small muted">수정 후 다시 검색하세요 — 오류가 있으면 «계산 설정으로 이동»이 꺼집니다.</div>`;
      } else {
        box.innerHTML = `<div class="lb-parsed"><span class="lb-svg">${p.svg}</span><div><div class="small" style="color:var(--ok)">✓ 파싱 OK · 원자가 검사 통과</div>
          <div class="small">정규화 <span class="mono">${h(p.canonical)}</span></div><div class="small">${fmtFormula(p.formula)} · ${nf(p.mw, 3)} g/mol · 전하 ${p.charge > 0 ? "+" : ""}${p.charge}${p.fragments > 1 ? ` · <b>${p.fragments}조각</b>` : ""}${p.stereo_centers ? ` · 입체 중심 ${p.stereo_centers}` : ""}</div>
          <div class="small" style="margin-top:4px">${p.existing ? `라이브러리에 있음 → <a class="btn ghost sm" data-open="${h(p.existing)}">${h(p.existing_name)}</a>` : `<button class="btn sm" type="button" id="lb-add-parsed">라이브러리에 추가</button> <span class="muted">새 분자</span>`}</div></div></div>`;
        const o = box.querySelector("[data-open]"); if (o) o.addEventListener("click", () => { L.ui.focus = o.dataset.open; renderSelPanel(); renderTable(); });
        const a = box.querySelector("#lb-add-parsed"); if (a) a.addEventListener("click", () => openAddForm({smiles: p.canonical}));
      }
    } catch (e) { box.innerHTML = ""; }
    setGoEnabled();
  }
  function setGoEnabled() {
    const go = document.getElementById("lb-tgo"); if (!go) return;
    const bad = L.ui.mode !== "name" && L.ui.mode !== "sub" && L.ui.parsed && L.ui.parsed.ok === false && L.ui.sq.trim();
    go.disabled = !L.sel.length || !!bad;
    go.textContent = L.sel.length > 1 ? `배치 스크리닝으로 이동 (${L.sel.length}건) →` : "계산 설정으로 이동 →";
  }

  function renderMolSearch() {
    const root = document.getElementById("rbv-molsearch"); if (!root) return;
    if (!root.dataset.built) {
      root.dataset.built = "1";
      root.innerHTML = `<div class="lb-head"><div><h1>분자 검색 및 선택</h1><p class="rb-note">이름·구조·SMILES 로 정확히 찾고, 구조를 검토한 뒤 계산 대상을 확정합니다. «분자 라이브러리»와 즐겨찾기·선택함·계산 환경을 공유합니다.</p></div>
          <div class="lb-steps"><span class="on"><b>1</b>검색</span><i></i><span class="on"><b>2</b>선택</span><i></i><span><b>3</b>계산 설정</span><i></i><span><b>4</b>실행·결과</span></div></div>
        <div class="lb-sel3" id="lb-sel3" data-mid-min="400">
          <div class="card lb-left">
            <div class="lb-tabs" id="lb-stabs">${[["name", "이름", "이름·약어·CAS·화학식 검색"], ["exact", "구조", "구조 완전 일치 (InChIKey)"], ["sim", "유사도", "Morgan 지문 Tanimoto 유사도"], ["sub", "부분구조", "SMARTS 부분구조 포함"]].map(([k, l, t]) => `<button type="button" data-m="${k}" title="${t}">${l}</button>`).join("")}</div>
            <div class="small muted" id="lb-mode-note" style="margin-bottom:8px"></div>
            <div class="toolbar" style="margin:0 0 6px;gap:6px"><span class="seg" id="lb-kind"><button type="button" data-k="smiles" class="on">SMILES</button><button type="button" data-k="inchi">InChI</button></span></div>
            <div style="display:flex;gap:6px"><input class="input grow" id="lb-sq" autocomplete="off" placeholder="이름 · 약어 · CAS · 화학식 · SMILES (예: EC, C3H6O3, C=CC#N)"><button class="btn primary" type="button" id="lb-sgo">검색</button></div>
            <div id="lb-parse" style="margin-top:8px"></div>
            <div class="lb-opts" id="lb-opts"></div>
            <div id="lb-pubchem-wrap" style="margin-top:8px"></div>
            <div class="lb-bind"><b>계산 구조 · Li⁺</b>
              <div class="toolbar" style="margin:6px 0 0;gap:6px">반복단위 전개 <select class="input" id="lb-structure"><option value="모노머">모노머</option><option value="2량체">2량체</option><option value="3량체">3량체</option></select> <span class="small muted">양 끝 H 캡핑</span></div>
              <div class="toolbar" style="margin:6px 0 0;gap:6px">Li⁺ 모델 <select class="input" id="lb-li"><option value="">(정확도 프리셋)</option><option value="competition">용매 경쟁 (Li(solv)n⁺ 참조)</option><option value="bare">고립 Li⁺ 결합만</option></select></div>
              <div class="small muted" style="margin-top:4px">«계산» 화면의 구조·Li⁺ 모델 칸에 그대로 채워집니다 (프리셋 모노머는 서버 정의 2·3량체 사용).</div></div>
            <div class="lb-mini2"><div><h5>최근 검색</h5><ul id="lb-recent"></ul></div><div><h5>즐겨찾기</h5><div id="lb-favs" class="lb-favs"></div></div></div>
          </div>
          <div class="lb-split" data-sp="msL" data-sign="1" data-min="240" data-max="560"></div>
          <div class="card lb-mid">
            <div class="toolbar" style="gap:8px;margin-bottom:8px"><h2 style="margin:0;font-size:15px">검색 결과 <span id="lb-tcount" style="color:var(--accent)"></span></h2>
              <input class="input" id="lb-tq" placeholder="결과 내 재검색" style="max-width:200px"><select class="input" id="lb-tstate"><option value="">모든 상태</option><option value="계산 완료">계산 완료</option><option value="계산 중">계산 중</option><option value="미계산">미계산</option></select>
              <select class="input" id="lb-tsort"><option value="score">검색 점수순</option><option value="mw">분자량 (낮은순)</option><option value="name">이름순</option><option value="recent">최근 계산순</option></select></div>
            <div class="small muted" id="lb-tnote" style="margin-bottom:6px"></div>
            <div class="lb-tablewrap"><table class="table lb-table" id="lb-table"></table></div>
            <div class="lb-tfoot"><span id="lb-tsel"></span><span class="sp"><button class="btn" type="button" id="lb-tclear">선택 초기화</button><button class="btn" type="button" id="lb-tfav">☆ 즐겨찾기에 추가</button><button class="btn primary" type="button" id="lb-tgo">계산 설정으로 이동 →</button></span></div>
          </div>
          <div class="lb-split" data-sp="msR" data-sign="-1" data-min="260" data-max="760"></div>
          <div class="card lb-right" id="lb-spanel"></div>
        </div>
        <div class="lb-hsplit" data-hs="lb-sel3"></div>
        <div class="card" id="lb-envcard"></div>`;
      const u = L.ui;
      root.querySelectorAll("#lb-stabs button").forEach(b => b.addEventListener("click", () => { u.mode = b.dataset.m; if (u.mode === "sim" && !u.sq && u.focus && rec(u.focus)) u.sq = rec(u.focus).smiles; syncSearchUi(); runSearch(); runParse(); }));
      root.querySelectorAll("#lb-kind button").forEach(b => b.addEventListener("click", () => { u.kind = b.dataset.k; syncSearchUi(); runParse(); }));
      const sq = root.querySelector("#lb-sq");
      sq.addEventListener("input", () => { u.sq = sq.value; clearTimeout(searchTimer); clearTimeout(parseTimer); searchTimer = setTimeout(runSearch, u.mode === "name" ? 250 : 450); parseTimer = setTimeout(runParse, 350); });
      sq.addEventListener("keydown", e => { if (e.key === "Enter") { clearTimeout(searchTimer); runSearch(); runParse(); } });
      root.querySelector("#lb-sgo").addEventListener("click", () => { u.sq = sq.value; runSearch(); runParse(); });
      root.querySelector("#lb-tq").addEventListener("input", e => { u.tq = e.target.value; renderTable(); });
      root.querySelector("#lb-tstate").addEventListener("change", e => { u.tstate = e.target.value; renderTable(); });
      root.querySelector("#lb-tsort").addEventListener("change", e => { u.tsort = e.target.value; renderTable(); });
      root.querySelector("#lb-tclear").addEventListener("click", () => { L.sel = []; saveSel(); rerender(); });
      root.querySelector("#lb-tfav").addEventListener("click", async () => { for (const id of L.sel) await setFav(id, true, true); await load(true); rerender(); toast("선택한 분자를 즐겨찾기에 추가했습니다 — 분자 라이브러리와 공유"); });
      root.querySelector("#lb-tgo").addEventListener("click", () => goCalc(L.sel));
      const st = root.querySelector("#lb-structure"), li = root.querySelector("#lb-li");
      st.value = L.ext.structure || "모노머"; li.value = L.ext.liModel || "";
      st.addEventListener("change", () => { L.ext.structure = st.value; saveExt(); renderSelPanel(); });
      li.addEventListener("change", () => { L.ext.liModel = li.value; saveExt(); renderSelPanel(); });
    }
    syncSearchUi();
    if (!L.ui.rows) runSearch(); else renderTable();
    renderSelPanel(); renderEnvCard(); renderRecent();
    initSplits(document.getElementById("lb-sel3"), MS_KEYS);
    renderPickBar("rbv-molsearch");
  }
  function syncSearchUi() {
    const u = L.ui, root = document.getElementById("rbv-molsearch"); if (!root) return;
    root.querySelectorAll("#lb-stabs button").forEach(b => b.classList.toggle("on", b.dataset.m === u.mode));
    root.querySelectorAll("#lb-kind button").forEach(b => b.classList.toggle("on", b.dataset.k === u.kind));
    root.querySelector("#lb-kind").style.display = u.mode === "name" ? "none" : "";
    root.querySelector("#lb-mode-note").textContent = MODE_NOTE[u.mode];
    const sq = root.querySelector("#lb-sq"); if (sq.value !== u.sq) sq.value = u.sq;
    sq.placeholder = u.mode === "name" ? "이름 · 약어 · CAS · 화학식 · SMILES (예: EC, C3H6O3, C=CC#N)" : u.mode === "sub" ? "부분구조 SMILES/SMARTS (예: C=C, C#N, [OX2][CX3](=O)[OX2])" : u.kind === "inchi" ? "InChI=1S/…" : "SMILES (예: O=C1OCCO1)";
    const opts = root.querySelector("#lb-opts");
    opts.innerHTML = u.mode === "exact" ? `<label class="compare-check small"><input type="checkbox" id="lb-o-stereo" ${u.stereo ? "checked" : ""}> 입체화학 구분</label><label class="compare-check small"><input type="checkbox" id="lb-o-salts" ${u.salts ? "checked" : ""}> 염·용매화물 제외 (가장 큰 조각)</label>`
      : u.mode === "sim" ? `<label class="small" style="display:flex;gap:6px;align-items:center">Tanimoto 기준 <input type="range" id="lb-o-thr" min="0.1" max="0.9" step="0.05" value="${u.thr}" style="accent-color:var(--accent)"> <b class="mono" id="lb-o-thrv">${u.thr.toFixed(2)}</b></label>` : "";
    const s1 = opts.querySelector("#lb-o-stereo"); if (s1) s1.addEventListener("change", () => { u.stereo = s1.checked; runSearch(); });
    const s2 = opts.querySelector("#lb-o-salts"); if (s2) s2.addEventListener("change", () => { u.salts = s2.checked; runSearch(); });
    const s3 = opts.querySelector("#lb-o-thr"); if (s3) s3.addEventListener("input", () => { u.thr = +s3.value; opts.querySelector("#lb-o-thrv").textContent = u.thr.toFixed(2); clearTimeout(searchTimer); searchTimer = setTimeout(runSearch, 300); });
    const pw = root.querySelector("#lb-pubchem-wrap");
    pw.innerHTML = u.mode === "name" && !IS_SNAPSHOT ? `<button class="btn sm" type="button" id="lb-pubchem">PubChem 에서 찾기 (라이브러리에 없을 때)</button><div id="lb-pubchem-out"></div>` : "";
    const pb = pw.querySelector("#lb-pubchem"); if (pb) pb.addEventListener("click", pubchemLookup);
  }
  async function pubchemLookup() {
    const out = document.getElementById("lb-pubchem-out"), q = L.ui.sq.trim(); if (!out) return;
    if (!q) { out.innerHTML = '<div class="small muted">검색어(영문 이름·CAS·SMILES)를 넣으세요</div>'; return; }
    out.innerHTML = '<div class="small muted">PubChem 조회 중…</div>';
    try {
      const r = await fetch("/api/lookup", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({query: q})});
      const d = await r.json(); if (!r.ok) throw new Error(d.detail || "HTTP " + r.status);
      const pc = d.pubchem || {}, smi = pc.smiles || d.local?.canonical_smiles || d.smiles;
      if (!smi) { out.innerHTML = `<div class="small muted">찾지 못했습니다 ${d.pubchem_error ? "— " + h(d.pubchem_error) : ""}</div>`; return; }
      const name = pc.title || pc.iupac_name || q;
      out.innerHTML = `<div class="lb-pc"><b>${h(name)}</b> <span class="small muted">${h(pc.formula || d.local?.formula || "")} · CID ${h(pc.cid || "—")}${pc.cas ? " · CAS " + h(pc.cas) : ""}</span><div class="mono small">${h(smi)}</div>
        <div class="toolbar" style="margin:6px 0 0;gap:6px"><button class="btn sm primary" type="button" id="lb-pc-add">라이브러리에 추가</button>${pc.url ? `<a class="btn ghost sm" href="${h(pc.url)}" target="_blank" rel="noopener">PubChem 페이지</a>` : ""}</div></div>`;
      out.querySelector("#lb-pc-add").addEventListener("click", () => openAddForm({smiles: smi, name: /^[A-Za-z0-9 ,()\-]+$/.test(q) && q.length <= 12 ? q.toUpperCase() === q ? q : name : name, full: pc.iupac_name || name, cas: pc.cas || "", synonyms: pc.synonyms || [], source: "PubChem"}));
    } catch (e) { out.innerHTML = `<div class="form-error">PubChem 조회 실패 — ${h(e.message)} (인터넷 연결 확인)</div>`; }
  }
  function tableRows() {
    const u = L.ui;
    let rows = (u.rows || []).filter(r => rec(r.id)).map(r => ({...r, m: rec(r.id)}));
    if (u.tq) { const q = u.tq.toLowerCase(); rows = rows.filter(r => [r.m.name, r.m.full, r.m.formula, r.m.smiles, ...(r.m.tags || [])].join(" ").toLowerCase().includes(q)); }
    if (u.tstate) rows = rows.filter(r => calcState(r.m)[1] === u.tstate);
    if (u.tsort === "mw") rows.sort((a, b) => a.m.mw - b.m.mw);
    else if (u.tsort === "name") rows.sort((a, b) => a.m.name.localeCompare(b.m.name));
    else if (u.tsort === "recent") rows.sort((a, b) => ((b.m.jobs[0] || {}).when || 0) - ((a.m.jobs[0] || {}).when || 0));
    return rows;
  }
  function renderTable() {
    const t = document.getElementById("lb-table"); if (!t) return;
    const u = L.ui, rows = tableRows(), showScore = u.mode === "sim" || u.mode === "sub";
    document.getElementById("lb-tcount").textContent = `${rows.length}개`;
    document.getElementById("lb-tnote").textContent = u.note || "";
    if (!rows.length) {
      t.innerHTML = `<tr><td class="empty small">${u.mode === "name" && u.sq ? "라이브러리에 없습니다 — 왼쪽 «PubChem 에서 찾기»로 가져오거나 SMILES 로 «라이브러리에 추가»하세요." : "결과가 없습니다."}</td></tr>`;
    } else {
      // 5열로 압축 — 선택 · 구조 · 분자(이름·정식 명칭·화학식·분자량·ID) · 상태/최근 계산 · 선택 버튼
      t.innerHTML = `<colgroup><col style="width:30px"><col style="width:84px"><col><col style="width:128px"><col style="width:86px"></colgroup><tr><th></th><th>구조</th><th>분자</th><th>${showScore ? (u.mode === "sim" ? "유사도 · " : "일치 · ") : ""}상태 · 최근 계산</th><th></th></tr>`
        + rows.map(r => { const m = r.m, [cls, st] = calcState(m), j = m.jobs[0], on = L.sel.includes(m.id), foc = u.focus === m.id;
          return `<tr data-row="${h(m.id)}" class="${foc ? "row-active" : ""}"><td><input type="checkbox" data-selk="${h(m.id)}" ${on ? "checked" : ""} title="선택함에 담기"></td>
            <td class="lb-st">${r.svg ? `<span class="lb-svg">${r.svg}</span>` : svgOf(m)}</td>
            <td class="lb-molcell"><b>${h(m.name)}</b> <button class="lb-star ${m.fav ? "on" : ""}" type="button" data-fav="${h(m.id)}" title="즐겨찾기">★</button><div class="small muted lb-ell">${h(m.full || "")}</div><div class="small">${fmtFormula(m.formula)} · ${nf(m.mw, 2)} g/mol <span class="mono muted">${h(m.id)}</span></div></td>
            <td class="small">${showScore ? `<b class="mono">${nf(r.score, 2)}</b> · ` : ""}<span class="badge ${cls}">${st}</span>${j ? `<div>${jobLink(j, true)} <span class="muted">${h(when(j.when))}</span></div>` : ""}</td>
            <td><button class="btn sm ${on ? "primary" : ""}" type="button" data-pick="${h(m.id)}" title="${on ? "누르면 선택 취소" : "선택함에 담고 오른쪽에 표시"}">${on ? "선택됨 ✕" : "선택"}</button></td></tr>`; }).join("");
    }
    t.querySelectorAll("[data-selk]").forEach(c => c.addEventListener("change", () => toggleSel(c.dataset.selk, c.checked)));
    t.querySelectorAll("[data-pick]").forEach(b => b.addEventListener("click", () => {
      const id = b.dataset.pick;
      if (L.sel.includes(id)) { L.sel = L.sel.filter(x => x !== id); if (u.focus === id) u.focus = L.sel[L.sel.length - 1] || null; }   // 선택 취소
      else { L.sel.push(id); u.focus = id; }
      saveSel(); rerender();
    }));
    t.querySelectorAll("[data-fav]").forEach(b => b.addEventListener("click", e => { e.stopPropagation(); setFav(b.dataset.fav, !rec(b.dataset.fav).fav); }));
    t.querySelectorAll("tr[data-row]").forEach(tr => tr.addEventListener("click", e => { if (e.target.closest("button,input,a")) return; u.focus = tr.dataset.row; renderTable(); renderSelPanel(); }));
    wireJobLinks(t);
    const ts = document.getElementById("lb-tsel");
    if (ts) ts.innerHTML = `선택된 분자 <b>${L.sel.length}</b>개${L.sel.length ? " (" + L.sel.map(id => h(rec(id)?.name || id)).join(", ") + ")" : ""}`;
    setGoEnabled();
  }
  function renderRecent() {
    const ul = document.getElementById("lb-recent"); if (!ul) return;
    const rec_ = LS.get("rb-lib-recent", []);
    ul.innerHTML = rec_.length ? rec_.map(x => `<li data-q="${h(x.q)}" data-m="${h(x.mode)}"><span>${h(x.q)}</span><span class="muted">${{name: "이름", exact: "구조", sim: "유사", sub: "부분"}[x.mode] || ""}</span></li>`).join("") : '<li class="muted">없음</li>';
    ul.querySelectorAll("li[data-q]").forEach(li => li.addEventListener("click", () => { L.ui.sq = li.dataset.q; L.ui.mode = li.dataset.m || "name"; syncSearchUi(); runSearch(); runParse(); }));
    const fv = document.getElementById("lb-favs");
    if (fv) { const f = mols().filter(m => m.fav).slice(0, 6); fv.innerHTML = f.length ? f.map(m => `<button type="button" data-k="${h(m.id)}" title="${h(m.full || "")}">${svgOf(m, "sm")}<b>${h(m.name)}</b></button>`).join("") : '<span class="small muted">★ 로 표시한 분자</span>'; fv.querySelectorAll("[data-k]").forEach(b => b.addEventListener("click", () => { L.ui.focus = b.dataset.k; renderTable(); renderSelPanel(); })); }
  }

  /* 선택 분자 패널 (분자 검색 및 선택 오른쪽) */
  function panelInfo(m) {
    const j = lastDone(m), run = m.jobs.find(x => x.status === "RUNNING" || x.status === "QUEUED"), [cls, st] = calcState(m);
    const valid = m.fragments > 1 ? `<span class="badge review">${m.fragments}조각 (염·이온쌍)</span>` : '<span class="badge published">RDKit 파싱·원자가 OK</span>';
    return `<table class="kv-table lb-kv"><tr><th>레코드 ID</th><td class="mono">${h(m.id)}</td></tr><tr><th>화학식</th><td>${fmtFormula(m.formula)} · ${nf(m.mw, 3)} g/mol</td></tr>
      <tr><th>SMILES</th><td class="mono small" style="word-break:break-all">${h(m.smiles)}</td></tr><tr><th>InChIKey</th><td class="mono small">${h(m.inchikey || "—")}</td></tr><tr><th>CAS</th><td>${h(m.cas || "—")}</td></tr>
      <tr><th>형식 전하</th><td>${m.charge > 0 ? "+" : ""}${m.charge} <span class="small muted">· 다중도 1 (기본)</span></td></tr><tr><th>입체 중심</th><td>${m.stereo_centers || 0}</td></tr>
      <tr><th>구조 검증</th><td>${valid}</td></tr><tr><th>역할</th><td>${(m.roles || []).map(r => `<span class="chip">${ROLE_LABEL[r] || r}</span>`).join(" ")}</td></tr>
      <tr><th>상태</th><td><span class="badge ${cls}">${st}</span>${run ? " " + jobLink(run) : ""}</td></tr>
      <tr><th>최근 계산</th><td>${j ? `${jobLink(j)} ${gradeBadge(j)}<div class="small muted">${h(j.method)} · ${h(j.solvent)} · ${h(j.structure)}</div>` : '<span class="badge queued">미계산</span>'}</td></tr>
      <tr><th>출처</th><td>${h(m.source || "")}${m.builtin ? ' <span class="small muted">(기본 레코드)</span>' : ""}</td></tr></table>`;
  }
  function viewer(m, id3d) {
    return `<div class="lb-pv"><div class="lb-pv-body" id="${id3d}">${svgOf(m, "lg")}</div><div class="lb-pv-tools"><button type="button" class="on" data-v2="2d">2D</button><button type="button" data-v2="3d">3D</button></div><div class="lb-pv-src" id="${id3d}-src">2D 구조 (RDKit)</div></div>`;
  }
  async function show3D(box, m, srcEl) {
    box.innerHTML = '<div class="small muted" style="padding:20px">3D 구조 불러오는 중…</div>';
    try {
      let xyz = null, src = "";
      const j = lastDone(m), jj = j && (typeof JOBS_CACHE !== "undefined" ? JOBS_CACHE : []).find(x => x.id === j.id);
      if (jj && jj.result && jj.result.structure_xyz && j.structure === "모노머") { xyz = jj.result.structure_xyz; src = `DFT 최적화 구조 (${j.id})`; }
      else if (!IS_SNAPSHOT) { const r = await fetch(`/api/library/molecules/${encodeURIComponent(m.id)}/structure`); const d = await r.json(); if (!r.ok) throw new Error(d.detail); xyz = d.xyz; src = d.source; }
      if (!xyz) throw new Error("사본에는 계산된 구조만 있습니다");
      box.innerHTML = "";
      render3D({structure_xyz: xyz, mulliken_charges: []}, {box, mode: "element", view: {iso: 0.03, alpha: 0.7, style: "none", labels: false}, cam: {yaw: 0.6, pitch: -0.4, zoom: 1}});
      if (srcEl) srcEl.textContent = "구조 출처: " + src;
    } catch (e) { box.innerHTML = `<div class="small muted" style="padding:20px">3D 구조를 만들지 못했습니다 — ${h(e.message)}</div>`; }
  }
  function wireViewer(root, m, id3d) {
    root.querySelectorAll("[data-v2]").forEach(b => b.addEventListener("click", () => {
      root.querySelectorAll("[data-v2]").forEach(x => x.classList.toggle("on", x === b));
      const box = root.querySelector("#" + id3d), src = root.querySelector("#" + id3d + "-src");
      if (b.dataset.v2 === "3d") show3D(box, m, src); else { box.innerHTML = svgOf(m, "lg"); if (src) src.textContent = "2D 구조 (RDKit)"; }
    }));
  }
  function renderSelPanel() {
    const box = document.getElementById("lb-spanel"); if (!box) return;
    const u = L.ui, m = rec(u.focus) || rec(L.sel[L.sel.length - 1]);
    if (!m) { box.innerHTML = '<h2 style="font-size:15px;margin:0">선택한 분자</h2><div class="empty small">표에서 «선택»을 누르거나 행을 누르면 여기에 구조·식별자·계산 이력이 나타납니다.</div>'; return; }
    u.focus = m.id;
    const t = L.tpl ? TEMPLATES[L.tpl][0] : "미선택";
    const inSel = L.sel.includes(m.id);
    box.innerHTML = `<div class="card-head" style="margin-bottom:4px"><h2 style="font-size:15px;margin:0">${inSel ? "선택한 분자" : "분자 보기"}</h2><span class="row-actions">${inSel ? `<button class="btn sm" type="button" data-unsel="${h(m.id)}">선택 취소</button>` : `<button class="btn sm primary" type="button" data-addsel="${h(m.id)}">선택함에 담기</button>`}<button class="btn ghost sm" type="button" data-openlib="${h(m.id)}">라이브러리 →</button></span></div>
      <div style="font-weight:800;font-size:17px">${h(m.name)} <span class="chip">${h(CAT_LABEL[m.category] || m.category)}</span></div><div class="small muted">${h(m.full || "")}</div>
      ${viewer(m, "lb-sp3d")}${panelInfo(m)}${m.solvent ? solventTable(m) : ""}
      <div class="lb-sub">빠른 계산 시작 <span class="small muted">— 템플릿만 고르고 «계산» 화면에서 전하·다중도·범함수·기저를 확인 후 제출 (즉시 실행하지 않음)</span></div>
      <div class="lb-quick">${Object.entries(TEMPLATES).map(([k, [a, b]]) => `<button type="button" data-tpl="${k}" class="${L.tpl === k ? "on" : ""}"><b>${a}</b>${b}</button>`).join("")}</div>
      <div class="lb-sub">추가 작업</div>
      <div class="lb-acts2">${IS_SNAPSHOT ? "" : `<div class="lb-dl"><span class="small muted">입력 파일</span> ${["xyz", "sdf", "mol", "smi"].map(f => `<a class="btn ghost sm" href="/api/library/molecules/${encodeURIComponent(m.id)}/export?fmt=${f}">${f.toUpperCase()}</a>`).join("")}</div>`}
        <button class="btn sm" type="button" data-sim="${h(m.id)}">유사한 분자 찾기</button><button class="btn sm" type="button" data-cmp="${h(m.id)}" ${lastDone(m) ? "" : "disabled title=\"계산 완료 결과가 있어야 비교할 수 있습니다\""}>이 분자 결과 비교에 추가</button></div>
      <div class="lb-bindnote"><b>계산으로 넘어갈 값</b><div class="small muted">분자 ${h(m.id)} (${h(m.smiles)}) · 구조 ${h(L.ext.structure)} · Li⁺ ${h(L.ext.liModel || "프리셋")} · 템플릿 ${h(t)} · 환경 ${h(envLabel(L.env))}</div></div>`;
    wireViewer(box, m, "lb-sp3d"); wireJobLinks(box);
    box.querySelectorAll("[data-tpl]").forEach(b => b.addEventListener("click", () => { L.tpl = L.tpl === b.dataset.tpl ? null : b.dataset.tpl; renderSelPanel(); if (L.tpl) toast(`템플릿 «${TEMPLATES[L.tpl][0]}» — «계산 설정으로 이동»을 누르면 계산 화면에 미리 채워집니다`); }));
    const sim = box.querySelector("[data-sim]"); if (sim) sim.addEventListener("click", () => { u.mode = "sim"; u.sq = m.smiles; syncSearchUi(); runSearch(); runParse(); });
    const cmp = box.querySelector("[data-cmp]"); if (cmp) cmp.addEventListener("click", () => { const j = lastDone(m); if (!j) return; COMPARE_SEL.add(j.id); toast(`«${m.name}» 결과(${j.id})를 물질 비교에 추가했습니다 (${COMPARE_SEL.size}건)`); if (COMPARE_SEL.size >= 2 && window.rbOpenMode) window.rbOpenMode("compare", "물질 비교"); });
    const ol = box.querySelector("[data-openlib]"); if (ol) ol.addEventListener("click", () => { L.ui.preview = m.id; window.rbOpenMode("library", "분자 라이브러리"); });
    const us = box.querySelector("[data-unsel]"); if (us) us.addEventListener("click", () => { L.sel = L.sel.filter(x => x !== m.id); saveSel(); rerender(); });
    const as_ = box.querySelector("[data-addsel]"); if (as_) as_.addEventListener("click", () => { if (!L.sel.includes(m.id)) L.sel.push(m.id); saveSel(); rerender(); });
  }
  function solventTable(m) {
    const s = m.solvent;
    return `<div class="lb-sub">용매 물성 (SMD 파라미터)</div><table class="kv-table lb-kv"><tr><th>유전율 ε</th><td>${nf(s.eps, 3)}</td></tr><tr><th>굴절률 n</th><td>${nf(s.n, 4)}</td></tr><tr><th>H-결합 α / β</th><td>${nf(s.alpha, 2)} / ${nf(s.beta, 2)}</td></tr><tr><th>표면장력 γ</th><td>${nf(s.gamma, 1)} cal/mol·Å²</td></tr><tr><th>밀도</th><td>${s.density ? nf(s.density, 3) + " g/mL" : '<span class="muted">미등록 (몰비·질량비 환산 불가)</span>'}</td></tr></table>
      <button class="btn sm" type="button" data-addsolv="${h(m.id)}" style="margin-top:6px">계산 환경의 용매로 추가</button>`;
  }

  /* 계산 환경 카드 */
  function renderEnvCard() {
    const box = document.getElementById("lb-envcard"); if (!box) return;
    const env = L.env, solute = L.sel.map(rec).filter(Boolean);
    box.innerHTML = `<div class="card-head"><h2>계산 환경 — 분자 라이브러리로 용매 구성</h2><span class="small muted">«계산» 화면 2. 환경과 배치 스크리닝 용매에 그대로 전달됩니다</span></div>
      <div class="lb-envrow"><div>
        <div class="lb-sub" style="margin-top:0">용질 (계산 대상 · 선택함)</div>
        <div>${solute.length ? solute.map(m => `<span class="chip lb-chip">${h(m.name)} · ${fmtFormula(m.formula)}</span>`).join(" ") : '<span class="small muted">위 표에서 분자를 선택하세요</span>'}</div>
        <div class="lb-sub">용매 모델 <span class="seg" style="margin-left:8px">${[["vacuum", "진공·기체"], ["implicit", "암묵적 (SMD)"], ["cluster", "명시적 + SMD"]].map(([k, l]) => `<button type="button" class="${env.mode === k ? "on" : ""}" data-em="${k}">${l}</button>`).join("")}</span></div>
        ${env.mode === "vacuum" ? '<div class="small muted">용매 없음 — 기체상 계산</div>' : `<div class="small muted" style="margin-bottom:6px">분자 라이브러리에서 역할 «용매»(SMD 파라미터 보유)인 분자만 고를 수 있습니다. 성분 1개면 단일 용매, 2개 이상이면 혼합 용매입니다.</div>
          <div id="lb-env-comp">${composerHtml(env, {save: true})}</div>
          ${env.mode === "cluster" ? `<div class="toolbar" style="margin-top:8px;gap:6px"><span class="small">명시적 용매 분자</span><input class="input" type="number" min="1" max="10" id="lb-env-n" value="${h(env.explicit || 2)}" style="width:70px"><span class="small muted">개 — 부피분율대로 성분 배분: ${explicitSplit(env).map(x => `${h(x.name)} ${x.count}`).join(" · ") || "—"} · 나머지는 SMD</span></div>` : ""}`}
      </div><div>
        <div class="lb-sub" style="margin-top:0">유효 매질 (자동 계산)</div>${effTable(env)}
        <div class="toolbar" style="margin-top:10px;gap:6px"><button class="btn primary" type="button" id="lb-env-go" ${solute.length ? "" : "disabled"}>${solute.length > 1 ? "용질 + 이 환경으로 배치 스크리닝 →" : "용질 + 이 환경으로 계산 설정 →"}</button><button class="btn" type="button" id="lb-env-lib">라이브러리에서 용매 고르기</button></div>
      </div></div>`;
    const ch = () => { saveEnv(); renderEnvCard(); renderBasket(); renderSelPanel(); };
    box.querySelectorAll("[data-em]").forEach(b => b.addEventListener("click", () => { env.mode = b.dataset.em; ch(); }));
    if (env.mode !== "vacuum") wireComposer(box.querySelector("#lb-env-comp"), env, ch, {after: ch});
    const n = box.querySelector("#lb-env-n"); if (n) n.addEventListener("change", () => { env.explicit = Math.max(1, Math.min(10, +n.value || 1)); ch(); });
    box.querySelector("#lb-env-go").addEventListener("click", () => goCalc(L.sel));
    box.querySelector("#lb-env-lib").addEventListener("click", () => { L.ui.cat = "solvent"; window.rbOpenMode("library", "분자 라이브러리"); toast("용매 탭 — 카드의 «용매로» 버튼으로 계산 환경에 추가하세요"); });
  }
  function addSolvent(id) {
    const m = rec(id); if (!m || !m.solvent) return;
    if (!L.env.comps.some(c => c.id === id)) L.env.comps.push({id, ratio: 1});
    if (L.env.mode === "vacuum") L.env.mode = "implicit";
    saveEnv(); rerender();
    toast(`«${m.name}» 을 계산 환경의 용매 구성에 추가했습니다 (${envLabel(L.env)}) — «분자 검색 및 선택» 아래 카드에서 비율을 정하세요`);
  }

  /* ══════════ 분자 라이브러리 ══════════ */
  function libFiltered() {
    const u = L.ui, q = u.q.trim().toLowerCase(), f = u.f;
    return mols().filter(m => (u.cat === "all" || (u.cat === "user" ? !m.builtin : u.cat === "fav" ? m.fav : m.category === u.cat))
      && (!f.role.length || f.role.some(r => m.roles.includes(r)))
      && (!f.el.length || f.el.every(e => m.elements.includes(e)))
      && (!f.groups.length || f.groups.some(g => m.groups.includes(g)))
      && (!f.charge.length || f.charge.includes(m.charge > 0 ? "+" : m.charge < 0 ? "-" : "0"))
      && (!f.calc.length || f.calc.includes(calcState(m)[1]))
      && (!f.src.length || f.src.includes(m.builtin ? "기본" : "사용자"))
      && (u.mw >= 400 || m.mw <= u.mw)
      && (!q || [m.name, m.full, m.formula, m.cas, m.smiles, ...(m.tags || []), ...(m.synonyms || [])].join(" ").toLowerCase().includes(q)));
  }
  function libSorted(list) {
    const s = L.ui.sort, gap = m => { const j = lastDone(m); return j && j.gap != null ? j.gap : Infinity; };
    const l = [...list];
    if (s === "recent") l.sort((a, b) => ((b.jobs[0] || {}).when || 0) - ((a.jobs[0] || {}).when || 0));
    else if (s === "fav") l.sort((a, b) => (b.fav ? 1 : 0) - (a.fav ? 1 : 0));
    else if (s === "name") l.sort((a, b) => a.name.localeCompare(b.name));
    else if (s === "mw") l.sort((a, b) => a.mw - b.mw);
    else if (s === "gap") l.sort((a, b) => gap(a) - gap(b));
    return l;
  }
  function renderLibrary() {
    const root = document.getElementById("rbv-library"); if (!root) return;
    const u = L.ui;
    if (!root.dataset.built) {
      root.dataset.built = "1";
      root.innerHTML = `<div class="lb-head"><div><h1>분자 라이브러리</h1><p class="rb-note">바인더 모노머·용매·첨가제·리튬염·올리고머와 직접 등록한 분자를 한 곳에서 훑고, 후보를 골라 DFT 계산으로 넘깁니다. 서버에 저장되어 모든 PC 에서 같은 목록이 보입니다. <b id="lb-total"></b></p></div>
          <div class="lb-steps"><span class="on"><b>1</b>찾기</span><i></i><span><b>2</b>선택</span><i></i><span><b>3</b>계산 설정</span><i></i><span><b>4</b>실행·결과</span></div></div>
        <div class="toolbar"><div class="lb-search">🔍 <input id="lb-q" placeholder="이름 · 약어 · 화학식 · SMILES · CAS · 태그 (예: FEC, C3H6O3, 바인더)"></div>
          <button class="btn" type="button" id="lb-go-search">구조 검색 / 정밀 선택 →</button>${IS_SNAPSHOT ? "" : '<button class="btn primary" type="button" id="lb-add">+ 분자 등록</button>'}</div>
        <div id="lb-addform"></div>
        <div class="lb-cats" id="lb-cats"></div>
        <div class="lb-lib" id="lb-lib" data-stack-at="900"><div class="card lb-filter" id="lb-filter"></div>
          <div class="lb-split" data-sp="libF" data-sign="1" data-min="170" data-max="420"></div>
          <div class="lb-libmain"><div class="toolbar" style="gap:8px"><b id="lb-rcount"></b><span class="lb-sorts" id="lb-sorts"></span><span class="seg" style="margin-left:auto" id="lb-view"><button type="button" data-v="grid">▦ 카드</button><button type="button" data-v="list">☰ 목록</button></span></div><div id="lb-results"></div></div>
          <div class="lb-split" data-sp="libP" data-sign="-1" data-min="300" data-max="900"></div>
          <div class="card lb-panel" id="lb-panel"></div></div>`;
      root.querySelector("#lb-q").addEventListener("input", e => { u.q = e.target.value; renderLibResults(); renderLibCats(); });
      root.querySelector("#lb-go-search").addEventListener("click", () => { L.ui.sq = u.q; L.ui.mode = "name"; L.ui.rows = null; window.rbOpenMode("molsearch", "분자 검색 및 선택"); });
      const add = root.querySelector("#lb-add"); if (add) add.addEventListener("click", () => openAddForm({}));
      root.querySelectorAll("#lb-view button").forEach(b => b.addEventListener("click", () => { u.grid = b.dataset.v; renderLibResults(); }));
    }
    root.querySelector("#lb-q").value = u.q;
    root.querySelector("#lb-total").textContent = `${mols().length}개 분자 · 혼합 용매 ${mixes().length}개`;
    renderLibCats(); renderLibFilter(); renderLibResults(); renderLibPanel();
    initSplits(document.getElementById("lb-lib"), LIB_KEYS);
    renderPickBar("rbv-library");
  }
  function renderLibCats() {
    const box = document.getElementById("lb-cats"); if (!box) return;
    const u = L.ui, all = mols();
    const tabs = [["all", "전체", all.length], ...(L.data?.categories || []).map(c => [c.id, c.label, all.filter(m => m.category === c.id).length]), ["user", "사용자 등록", all.filter(m => !m.builtin).length], ["fav", "★ 즐겨찾기", all.filter(m => m.fav).length]];
    box.innerHTML = tabs.map(([k, l, n]) => `<button type="button" class="${u.cat === k ? "on" : ""}" data-c="${k}">${h(l)} <span>${n}</span></button>`).join("");
    box.querySelectorAll("button").forEach(b => b.addEventListener("click", () => { u.cat = b.dataset.c; renderLibCats(); renderLibResults(); }));
  }
  function renderLibFilter() {
    const box = document.getElementById("lb-filter"); if (!box) return;
    const u = L.ui, f = u.f, all = mols(), cnt = fn => all.filter(fn).length;
    const active = Object.values(f).reduce((s, a) => s + a.length, 0) + (u.mw < 400 ? 1 : 0);
    const grp = (title, key, items) => `<h4>${title}</h4>${items.filter(it => it[2] > 0 || f[key].includes(it[0])).map(([v, l, n]) => `<label><input type="checkbox" data-f="${key}" value="${h(v)}" ${f[key].includes(v) ? "checked" : ""}> ${h(l)}<span class="n">${n}</span></label>`).join("")}`;
    const els = [...new Set(all.flatMap(m => m.elements))].sort((a, b) => (a === "C" ? -2 : a === "H" ? -1 : 0) - (b === "C" ? -2 : b === "H" ? -1 : 0) || a.localeCompare(b));
    box.innerHTML = `<div class="card-head" style="margin-bottom:4px"><b>필터 ${active ? `<span class="badge running">${active}</span>` : ""}</b><button class="btn ghost sm" type="button" id="lb-freset">모두 초기화</button></div>`
      + grp("역할", "role", [["solute", "용질 (계산 대상)", cnt(m => m.roles.includes("solute"))], ["solvent", "용매 (SMD 파라미터 보유)", cnt(m => m.roles.includes("solvent"))]])
      + grp("원소 조성 (모두 포함)", "el", els.map(e => [e, e, cnt(m => m.elements.includes(e))]))
      + `<h4>분자량 (g/mol)</h4><input type="range" id="lb-mw" min="20" max="400" step="10" value="${u.mw}" style="width:100%;accent-color:var(--accent)"><div class="small muted">0 ~ <b id="lb-mwv">${u.mw >= 400 ? "제한 없음" : u.mw}</b></div>`
      + grp("기능기", "groups", (L.data?.fgroups || []).map(g => [g, g, cnt(m => m.groups.includes(g))]))
      + grp("전하", "charge", [["0", "중성", cnt(m => !m.charge)], ["+", "양이온", cnt(m => m.charge > 0)], ["-", "음이온", cnt(m => m.charge < 0)]])
      + grp("계산 상태", "calc", ["계산 완료", "계산 중", "미계산", "실패"].map(s => [s, s, cnt(m => calcState(m)[1] === s)]))
      + grp("출처", "src", [["기본", "기본 레코드", cnt(m => m.builtin)], ["사용자", "사용자 등록", cnt(m => !m.builtin)]]);
    box.querySelectorAll("input[type=checkbox]").forEach(c => c.addEventListener("change", () => { const a = f[c.dataset.f]; const i = a.indexOf(c.value); if (c.checked && i < 0) a.push(c.value); if (!c.checked && i >= 0) a.splice(i, 1); renderLibFilter(); renderLibResults(); }));
    box.querySelector("#lb-mw").addEventListener("input", e => { u.mw = +e.target.value; box.querySelector("#lb-mwv").textContent = u.mw >= 400 ? "제한 없음" : u.mw; renderLibResults(); });
    box.querySelector("#lb-freset").addEventListener("click", () => { Object.keys(f).forEach(k => f[k] = []); u.mw = 400; renderLibFilter(); renderLibResults(); });
  }
  function renderLibResults() {
    const box = document.getElementById("lb-results"); if (!box) return;
    const u = L.ui, list = libSorted(libFiltered());
    document.getElementById("lb-rcount").textContent = `총 ${list.length}개${u.q ? ` · «${u.q}»` : ""}`;
    document.querySelectorAll("#lb-view button").forEach(b => b.classList.toggle("on", b.dataset.v === u.grid));
    const sb = document.getElementById("lb-sorts");
    sb.innerHTML = [["recent", "최근 계산순"], ["fav", "즐겨찾기"], ["name", "이름"], ["mw", "분자량"], ["gap", "HOMO–LUMO gap (계산된 것만)"]].map(([k, l]) => `<button type="button" class="${u.sort === k ? "on" : ""}" data-s="${k}">${l}</button>`).join("");
    sb.querySelectorAll("button").forEach(b => b.addEventListener("click", () => { u.sort = b.dataset.s; renderLibResults(); }));
    if (!list.length) { box.innerHTML = `<div class="card empty small">조건에 맞는 분자가 없습니다 — 필터를 줄이거나 «구조 검색 / 정밀 선택»에서 PubChem 으로 찾아 추가하세요.</div>`; return; }
    if (u.grid === "grid") {
      box.innerHTML = `<div class="lb-grid">${list.map(m => { const [cls, st] = calcState(m), on = L.sel.includes(m.id);
        return `<div class="lb-card ${on ? "on" : ""} ${u.preview === m.id ? "focus" : ""}" data-k="${h(m.id)}">
          <div class="lb-card-top"><button class="lb-star ${m.fav ? "on" : ""}" type="button" data-fav="${h(m.id)}" title="즐겨찾기">★</button><input type="checkbox" data-selk="${h(m.id)}" ${on ? "checked" : ""} title="선택함에 담기"></div>
          <div class="lb-thumb">${svgOf(m)}<span class="f">${fmtFormula(m.formula)}</span></div>
          <div class="lb-nm">${h(m.name)}</div><div class="lb-full">${h(m.full || "")}</div><div class="mono small muted">${h(m.id)} · ${h(m.source || "")}</div>
          <div class="lb-tags">${(m.tags || []).slice(0, 2).map(t => `<span class="chip">${h(t)}</span>`).join("")}${m.roles.includes("solvent") ? '<span class="chip lb-solv">용매</span>' : ""}<span class="badge ${cls}">${st}</span></div>
          <div class="lb-acts"><button class="btn primary sm" type="button" data-go="${h(m.id)}" title="이 분자로 계산 설정 화면 열기 (바로 실행하지 않음)">계산 →</button>${m.solvent ? `<button class="btn sm" type="button" data-addsolv="${h(m.id)}" title="계산 환경의 용매 구성에 추가">용매로</button>` : ""}<button class="btn sm" type="button" data-detail="${h(m.id)}">상세</button></div></div>`; }).join("")}</div>`;
    } else {
      box.innerHTML = `<div class="card" style="padding:0 6px"><div class="scroll-x"><table class="table lb-table"><tr><th></th><th>구조</th><th>분자</th><th>화학식</th><th class="num">분자량</th><th>역할·태그</th><th>상태</th><th>최근 계산</th><th></th></tr>${list.map(m => { const [cls, st] = calcState(m), j = m.jobs[0];
        return `<tr data-k="${h(m.id)}" class="${u.preview === m.id ? "row-active" : ""}"><td><input type="checkbox" data-selk="${h(m.id)}" ${L.sel.includes(m.id) ? "checked" : ""}></td><td class="lb-st">${svgOf(m)}</td><td><b>${h(m.name)}</b> <button class="lb-star ${m.fav ? "on" : ""}" type="button" data-fav="${h(m.id)}">★</button><div class="small muted">${h(m.full || "")}</div></td><td>${fmtFormula(m.formula)}</td><td class="num">${nf(m.mw, 2)}</td><td>${m.roles.map(r => `<span class="chip">${ROLE_LABEL[r]}</span>`).join(" ")} ${(m.tags || []).slice(0, 2).map(t => `<span class="chip">${h(t)}</span>`).join(" ")}</td><td><span class="badge ${cls}">${st}</span></td><td class="small">${j ? jobLink(j) : "—"}</td><td class="row-actions"><button class="btn ghost sm" type="button" data-go="${h(m.id)}">계산 설정 →</button>${m.solvent ? `<button class="btn ghost sm" type="button" data-addsolv="${h(m.id)}">용매로</button>` : ""}</td></tr>`; }).join("")}</table></div></div>`;
    }
    box.querySelectorAll("[data-k]").forEach(c => c.addEventListener("click", e => { if (e.target.closest("button,input,a")) return; u.preview = c.dataset.k; u.ptab = "overview"; renderLibResults(); renderLibPanel(); }));
    box.querySelectorAll("[data-selk]").forEach(c => c.addEventListener("change", () => toggleSel(c.dataset.selk, c.checked)));
    box.querySelectorAll("[data-fav]").forEach(b => b.addEventListener("click", () => setFav(b.dataset.fav, !rec(b.dataset.fav).fav)));
    box.querySelectorAll("[data-go]").forEach(b => b.addEventListener("click", () => goCalc([b.dataset.go])));
    box.querySelectorAll("[data-addsolv]").forEach(b => b.addEventListener("click", () => addSolvent(b.dataset.addsolv)));
    box.querySelectorAll("[data-detail]").forEach(b => b.addEventListener("click", () => { u.preview = b.dataset.detail; u.ptab = "overview"; renderLibResults(); renderLibPanel(); document.getElementById("lb-panel")?.scrollIntoView({block: "nearest", behavior: "smooth"}); }));
    wireJobLinks(box);
  }
  function renderLibPanel() {
    const box = document.getElementById("lb-panel"); if (!box) return;
    const u = L.ui, m = rec(u.preview);
    if (!m) { box.innerHTML = '<h2 style="font-size:15px;margin:0">분자 미리보기</h2><div class="empty small">카드를 누르면 여기에 구조·식별자·계산 이력이 나타납니다.</div>'; return; }
    const j = lastDone(m), [cls, st] = calcState(m), same = mols().filter(x => x.formula === m.formula && x.id !== m.id);
    const tabs = [["overview", "개요"], ["struct", "구조"], ["calc", `계산 이력 (${m.n_jobs || 0})`]];
    let body = "";
    if (u.ptab === "overview") {
      body = `<table class="kv-table lb-kv"><tr><th>레코드 ID</th><td class="mono">${h(m.id)}</td></tr><tr><th>화학식</th><td>${fmtFormula(m.formula)}</td></tr><tr><th>분자량</th><td>${nf(m.mw, 3)} g/mol</td></tr><tr><th>CAS</th><td>${h(m.cas || "—")}</td></tr><tr><th>SMILES</th><td class="mono small" style="word-break:break-all">${h(m.smiles)}</td></tr><tr><th>출처</th><td>${h(m.source || "")}</td></tr>${m.note ? `<tr><th>메모</th><td class="small">${h(m.note)}</td></tr>` : ""}</table>
        <div class="lb-sub">주요 물성 <span class="small muted">${j ? `— ${h(j.id)} · ${h(j.method)} · ${h(j.solvent)} · ${h(j.structure)} 기준` : "— 계산 기록 없음"}</span></div>
        ${j ? `<table class="kv-table lb-kv"><tr><th>HOMO</th><td>${nf(j.homo, 3)} eV</td></tr><tr><th>LUMO</th><td>${nf(j.lumo, 3)} eV</td></tr><tr><th>HOMO–LUMO gap</th><td>${nf(j.gap, 3)} eV <span class="small muted">궤도 에너지 차이 — 전위·광학 갭 아님</span></td></tr><tr><th>검증</th><td>${gradeBadge(j)} ${jobLink(j)}</td></tr></table>`
          : `<div class="banner warn" style="margin:4px 0">이 분자는 아직 계산 결과가 없습니다. HOMO·LUMO 는 구조·전하·계산법·용매가 연결된 실제 결과가 있을 때만 표시합니다.</div>`}
        ${m.solvent ? solventTable(m) : ""}
        <div style="margin-top:8px">${(m.tags || []).map(t => `<span class="chip">${h(t)}</span>`).join(" ")}</div>`;
    } else if (u.ptab === "struct") {
      body = `<table class="kv-table lb-kv"><tr><th>입력 원본</th><td class="mono small" style="word-break:break-all">${h(m.input || m.smiles)}</td></tr><tr><th>InChIKey</th><td class="mono small">${h(m.inchikey || "—")}</td></tr><tr><th>형식 전하</th><td>${m.charge > 0 ? "+" : ""}${m.charge}</td></tr><tr><th>조각 수</th><td>${m.fragments}${m.fragments > 1 ? ' <span class="badge review">염·이온쌍</span>' : ""}</td></tr><tr><th>입체 중심</th><td>${m.stereo_centers || 0}</td></tr><tr><th>원자 수 (H 포함)</th><td>${m.n_atoms}</td></tr><tr><th>원소</th><td>${m.elements.join(" · ")}</td></tr><tr><th>기능기</th><td>${m.groups.join(" · ") || "—"}</td></tr><tr><th>역할</th><td>${m.roles.map(r => ROLE_LABEL[r]).join(" · ")}</td></tr>${m.oligomers ? `<tr><th>올리고머</th><td class="small">${Object.entries(m.oligomers).map(([k, v]) => `${h(k)} <span class="mono">${h(v)}</span>`).join("<br>")}</td></tr>` : ""}<tr><th>동일 화학식</th><td>${same.map(x => h(x.name)).join(", ") || "없음"}</td></tr></table>
        <p class="small muted">이성질체·토토머·염은 별도 레코드로 관리합니다. 3D 는 계산된 최적화 구조가 있으면 그것을, 없으면 RDKit 생성 conformer 를 보여 줍니다.</p>`;
    } else {
      body = m.jobs.length ? `<table class="table lb-table"><tr><th>작업</th><th>조건</th><th>상태</th></tr>${m.jobs.map(x => `<tr><td>${jobLink(x)}<div class="small muted">${h(when(x.when))}</div></td><td class="small">${h(x.method)}<br>${h(x.solvent)} · ${h(x.structure)}</td><td>${gradeBadge(x)}</td></tr>`).join("")}</table>${m.n_jobs > m.jobs.length ? `<p class="small muted">최근 ${m.jobs.length}건만 표시 (전체 ${m.n_jobs}건)</p>` : ""}` : '<div class="banner warn">계산 이력이 없습니다 — «DFT 계산 설정으로 이동»에서 첫 계산을 만드세요.</div>';
    }
    box.innerHTML = `<div class="card-head" style="margin-bottom:4px"><h2 style="font-size:15px;margin:0">분자 미리보기</h2><button class="lb-star ${m.fav ? "on" : ""}" type="button" data-fav="${h(m.id)}" style="font-size:20px">★</button></div>
      ${viewer(m, "lb-pv3d")}<div style="font-weight:800;font-size:17px">${h(m.name)} <span style="font-weight:400;font-size:13px;color:var(--text-2)">${fmtFormula(m.formula)}</span></div>
      <div class="small muted">${h(m.full || "")} · <span class="badge ${cls}">${st}</span> · ${h(CAT_LABEL[m.category] || m.category)}</div>
      <div class="lb-ptabs">${tabs.map(([k, l]) => `<button type="button" class="${u.ptab === k ? "on" : ""}" data-pt="${k}">${l}</button>`).join("")}</div>${body}
      <div class="lb-panel-acts"><button class="btn primary" type="button" data-go="${h(m.id)}">DFT 계산 설정으로 이동 →</button>
        <div class="lb-acts2"><button class="btn sm" type="button" data-sim="${h(m.id)}">유사 분자 보기</button><button class="btn sm" type="button" data-tosel="${h(m.id)}">구조 검색에서 열기</button>
        ${!m.builtin && !IS_SNAPSHOT ? `<button class="btn sm" type="button" data-edit="${h(m.id)}">편집</button><button class="btn ghost danger sm" type="button" data-del="${h(m.id)}">삭제</button>` : ""}</div></div>`;
    wireViewer(box, m, "lb-pv3d"); wireJobLinks(box);
    box.querySelectorAll("[data-pt]").forEach(b => b.addEventListener("click", () => { u.ptab = b.dataset.pt; renderLibPanel(); }));
    box.querySelector("[data-fav]").addEventListener("click", () => setFav(m.id, !m.fav));
    box.querySelector("[data-go]").addEventListener("click", () => goCalc([m.id]));
    const as = box.querySelector("[data-addsolv]"); if (as) as.addEventListener("click", () => addSolvent(m.id));
    box.querySelector("[data-sim]").addEventListener("click", () => { L.ui.mode = "sim"; L.ui.sq = m.smiles; L.ui.focus = m.id; L.ui.rows = null; window.rbOpenMode("molsearch", "분자 검색 및 선택"); setTimeout(() => { runSearch(); runParse(); }, 50); });
    box.querySelector("[data-tosel]").addEventListener("click", () => { L.ui.mode = "exact"; L.ui.sq = m.smiles; L.ui.focus = m.id; L.ui.rows = null; window.rbOpenMode("molsearch", "분자 검색 및 선택"); setTimeout(() => { runSearch(); runParse(); }, 50); });
    const ed = box.querySelector("[data-edit]"); if (ed) ed.addEventListener("click", () => openAddForm({...m, _edit: true}));
    const dl = box.querySelector("[data-del]"); if (dl) dl.addEventListener("click", async () => {
      if (!confirm(`«${m.name}» 레코드를 라이브러리에서 지울까요? (계산 결과는 지워지지 않습니다)`)) return;
      const r = await fetch(`/api/library/molecules/${encodeURIComponent(m.id)}`, {method: "DELETE"}); const out = await r.json().catch(() => ({}));
      if (!r.ok) { alert(out.detail || "삭제 실패"); return; }
      L.sel = L.sel.filter(x => x !== m.id); saveSel(); u.preview = null; await load(true); rerender(); toast(`«${m.name}» 을 지웠습니다`);
    });
  }

  /* 분자 등록 · 편집 */
  function openAddForm(pre) {
    if (IS_SNAPSHOT) return;
    const onLib = document.getElementById("rbv-library")?.offsetParent !== null && document.getElementById("rb-real")?.classList.contains("mode-library");
    if (!onLib) { L.pendingAdd = pre; window.rbOpenMode("library", "분자 라이브러리"); return; }
    const box = document.getElementById("lb-addform"); if (!box) return;
    const edit = !!pre._edit, s = pre.solvent || {};
    box.innerHTML = `<div class="card lb-addcard"><div class="card-head"><h2>${edit ? `«${h(pre.name)}» 편집` : "분자 등록"}</h2><button class="btn ghost" type="button" id="lb-af-close">닫기</button></div>
      <div class="form-grid">
        <div class="field" style="grid-column:1/-1"><span class="field-label">SMILES 또는 InChI ${edit ? "(구조는 바꿀 수 없습니다 — 새로 등록하세요)" : ""}</span><input class="input" id="lb-af-smi" value="${h(pre.smiles || "")}" ${edit ? "disabled" : ""} placeholder="예: O=C1OC(C)CO1"></div>
        <div class="field"><span class="field-label">이름 (약어 또는 영어)</span><input class="input" id="lb-af-name" value="${h(pre.name || "")}" placeholder="예: PC"></div>
        <div class="field"><span class="field-label">정식 명칭 (영어)</span><input class="input" id="lb-af-full" value="${h(pre.full || "")}" placeholder="예: Propylene carbonate"></div>
        <div class="field"><span class="field-label">분류</span><select class="input" id="lb-af-cat">${(L.data?.categories || []).map(c => `<option value="${c.id}" ${(pre.category || "other") === c.id ? "selected" : ""}>${h(c.label)}</option>`).join("")}</select></div>
        <div class="field"><span class="field-label">CAS</span><input class="input" id="lb-af-cas" value="${h(pre.cas || "")}"></div>
        <div class="field"><span class="field-label">태그 (쉼표로 구분)</span><input class="input" id="lb-af-tags" value="${h((pre.tags || []).join(", "))}"></div>
        <div class="field"><span class="field-label">역할</span><div><label class="compare-check small"><input type="checkbox" id="lb-af-solute" ${(pre.roles || ["solute"]).includes("solute") ? "checked" : ""}> 용질 (계산 대상)</label> <label class="compare-check small"><input type="checkbox" id="lb-af-solvent" ${(pre.roles || []).includes("solvent") ? "checked" : ""}> 용매 (SMD)</label></div></div>
      </div>
      <div id="lb-af-smd" class="lb-smd" ${(pre.roles || []).includes("solvent") ? "" : "hidden"}><div class="small muted" style="margin-bottom:4px">용매로 쓰려면 SMD 파라미터가 필요합니다 (Minnesota Solvent Descriptor Database 값). 밀도는 몰비·질량비 혼합 환산에 씁니다.</div>
        <div class="form-grid">${[["n", "굴절률 n (20 °C)", s.n], ["eps", "유전율 ε", s.eps], ["alpha", "H-결합 산도 α", s.alpha], ["beta", "H-결합 염기도 β", s.beta], ["gamma", "표면장력 γ (cal/mol·Å²)", s.gamma], ["density", "밀도 (g/mL)", s.density]].map(([k, l, v]) => `<div class="field"><span class="field-label">${l}</span><input class="input" type="number" step="any" id="lb-af-${k}" value="${v != null ? h(v) : ""}"></div>`).join("")}</div></div>
      <div id="lb-af-parse" style="margin-top:8px"></div><div class="form-error" id="lb-af-err"></div>
      <div class="form-actions"><button class="btn primary" type="button" id="lb-af-save">${edit ? "저장" : "라이브러리에 등록"}</button></div></div>`;
    box.scrollIntoView({block: "start", behavior: "smooth"});
    const $f = id => box.querySelector("#lb-af-" + id);
    $f("solvent").addEventListener("change", () => { box.querySelector("#lb-af-smd").hidden = !$f("solvent").checked; });
    box.querySelector("#lb-af-close").addEventListener("click", () => { box.innerHTML = ""; });
    let pt = null;
    const check = async () => {
      const v = $f("smi").value.trim(), out = box.querySelector("#lb-af-parse"); if (!v || edit) { out.innerHTML = ""; return; }
      const r = await fetch("/api/library/parse", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({text: v})}); const p = await r.json();
      out.innerHTML = p.ok ? `<div class="lb-parsed"><span class="lb-svg">${p.svg}</span><div class="small">✓ ${fmtFormula(p.formula)} · ${nf(p.mw, 3)} g/mol · 전하 ${p.charge}${p.existing ? `<div class="form-error">이미 있음: ${h(p.existing_name)} (${h(p.existing)})</div>` : ""}</div></div>` : `<div class="form-error">✗ ${h(p.error)}</div>`;
      if (p.ok && !$f("name").value) $f("name").placeholder = p.formula;
    };
    $f("smi").addEventListener("input", () => { clearTimeout(pt); pt = setTimeout(check, 350); });
    check();
    box.querySelector("#lb-af-save").addEventListener("click", async () => {
      const err = box.querySelector("#lb-af-err"); err.textContent = "";
      const roles = [$f("solute").checked && "solute", $f("solvent").checked && "solvent"].filter(Boolean);
      const num = k => { const v = $f(k).value; return v === "" ? null : +v; };
      const smd = roles.includes("solvent") ? {n: num("n"), eps: num("eps"), alpha: num("alpha") || 0, beta: num("beta") || 0, gamma: num("gamma") || 0} : null;
      const body = {name: $f("name").value.trim() || null, full: $f("full").value.trim() || null, category: $f("cat").value, cas: $f("cas").value.trim() || null,
        tags: $f("tags").value.split(",").map(x => x.trim()).filter(Boolean), roles: roles.length ? roles : ["solute"], density: num("density"), smd: smd && smd.n != null && smd.eps != null ? smd : (roles.includes("solvent") ? {n: 0, eps: 0} : null)};
      let r;
      if (edit) r = await fetch(`/api/library/molecules/${encodeURIComponent(pre.id)}`, {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
      else r = await fetch("/api/library/molecules", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({...body, smiles: $f("smi").value.trim(), synonyms: pre.synonyms || [], source: pre.source || null})});
      const out = await r.json().catch(() => ({}));
      if (!r.ok) { err.textContent = out.detail || "저장하지 못했습니다"; return; }
      const m = out.molecule; box.innerHTML = ""; await load(true); L.ui.preview = m.id; rerender();
      toast(edit ? `«${m.name}» 을 저장했습니다` : `«${m.name}» (${m.id}) 을 라이브러리에 등록했습니다`);
    });
  }

  /* ── 선택함 · 즐겨찾기 ── */
  function toggleSel(id, on) { const i = L.sel.indexOf(id); if (on && i < 0) L.sel.push(id); if (!on && i >= 0) L.sel.splice(i, 1); saveSel(); rerender(); }
  function refreshPickBars() { renderPickBar("rbv-molsearch"); renderPickBar("rbv-library"); }
  async function setFav(id, v, silent) {
    const m = rec(id); if (!m) return;
    if (IS_SNAPSHOT) { m.fav = v; rerender(); return; }
    const r = await fetch(`/api/library/molecules/${encodeURIComponent(id)}`, {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify({fav: v})});
    if (r.ok) { m.fav = v; if (!silent) rerender(); }
  }
  function renderBasket() {
    let b = document.getElementById("lb-basket");
    const real = document.getElementById("rb-real"), onPage = real && (real.classList.contains("mode-molsearch") || real.classList.contains("mode-library"));
    if (!onPage || !L.sel.length) { if (b) b.hidden = true; return; }
    if (!b) { b = document.createElement("div"); b.id = "lb-basket"; b.className = "lb-basket"; real.appendChild(b); }
    b.hidden = false;
    const names = L.sel.slice(0, 3).map(id => h(rec(id)?.name || id)).join(", ") + (L.sel.length > 3 ? ` 외 ${L.sel.length - 3}개` : "");
    b.innerHTML = `<span>선택함 <b>${L.sel.length}</b>개 · ${names}</span><span class="lb-bsolv">| 용매 ${h(envLabel(L.env))}</span>
      <button class="btn ghost sm" type="button" data-b="clear">비우기</button><button class="btn sm" type="button" data-b="cmp">물질 비교</button><button class="btn primary sm" type="button" data-b="go">${L.sel.length > 1 ? "배치 스크리닝으로 →" : "계산 설정으로 →"}</button>`;
    b.querySelector('[data-b="clear"]').onclick = () => { L.sel = []; saveSel(); rerender(); };
    b.querySelector('[data-b="go"]').onclick = () => goCalc(L.sel);
    b.querySelector('[data-b="cmp"]').onclick = () => {
      const ids = L.sel.map(rec).filter(Boolean).map(lastDone).filter(Boolean).map(j => j.id);
      if (ids.length < 2) { toast("계산 완료 결과가 있는 분자를 2개 이상 선택하세요 (결과가 있는 분자만 비교됩니다)"); return; }
      ids.forEach(i => COMPARE_SEL.add(i)); window.rbOpenMode("compare", "물질 비교");
    };
  }

  /* ══════════ 계산 화면으로 넘기기 ══════════ */
  function goCalc(ids) {
    ids = (ids || []).filter(rec);
    if (!ids.length) { toast("분자를 먼저 선택하세요"); return; }
    const envS = envToSettings(L.env);
    if (envS.error) { toast("계산 환경 오류 — " + envS.error); return; }
    L.pickForCalc = false;
    if (ids.length > 1) return goBatch(ids, envS);
    const m = rec(ids[0]);
    window.rbOpenMode("calc", "계산");
    const apply = () => {
      if (!document.getElementById("material-grid")) return;
      rbLibSelectInCalc([m.id]);
      const radio = document.querySelector(`input[name="env"][value="${CSS.escape(envS.envType)}"]`); if (radio) { radio.checked = true; radio.dispatchEvent(new Event("change", {bubbles: true})); }
      if (envS.envType !== "진공·기체") {
        if (envS.customMixedSolvent) rbLibSetCalcMixture(envS.customMixedSolvent);
        else { fillSolventSelect(document.getElementById("solvent"), {compose: true}); setSelect("solvent", envS.solventId); calcSolventChanged(); }
      }
      const rows = document.getElementById("explicit-rows");
      if (rows) { rows.innerHTML = ""; if (L.env.mode === "cluster") for (const x of explicitSplit(L.env)) { if (typeof addExplicitRow === "function") { addExplicitRow(); const row = rows.lastElementChild; const sel = row.querySelector('[data-role="species"]'); if ([...sel.options].some(o => o.value === x.smiles)) sel.value = x.smiles; else { sel.value = "__custom__"; sel.dispatchEvent(new Event("change")); row.querySelector('[data-role="custom"]').value = x.smiles; } row.querySelector('[data-role="count"]').value = x.count; } } }
      setSelect("structure", L.ext.structure || "모노머");
      if (L.ext.liModel != null) setSelect("li-model", L.ext.liModel);
      if (L.tpl === "opt") { setSelect("purpose", "전자구조(구조 최적화)"); setSelect("optimize", "true"); }
      else if (L.tpl === "sp") { setSelect("optimize", "false"); setSelect("thermo", "false"); }
      else if (L.tpl === "orb") { setSelect("purpose", "전자구조(구조 최적화)"); }
      const cs = document.getElementById("custom-smiles"); if (cs && cs.value.trim() === m.smiles) { cs.value = ""; const cn = document.getElementById("custom-name"); if (cn) cn.value = ""; }
      toast(`«${m.name}» · 환경 ${envLabel(L.env)}${L.tpl ? " · " + TEMPLATES[L.tpl][0] : ""} 을 계산 화면에 채웠습니다 — 전하·다중도·범함수·기저를 확인하고 «계산 제출»`);
      document.getElementById("material-grid")?.scrollIntoView({block: "center"});
    };
    load().then(() => setTimeout(apply, 120)).catch(() => {});
  }
  function goBatch(ids, envS) {
    window.rbOpenMode("screen", "계산");
    if (window.rbScreenOpenWizard) try { window.rbScreenOpenWizard(); } catch (e) {}
    setTimeout(() => {
      const ta = document.getElementById("scr-cands");
      if (ta) { ta.value = ids.map(rec).map(m => `${m.name.replace(/,/g, " ")},${m.smiles}`).join("\n"); if (typeof scrParse === "function") scrParse(); }
      const ss = document.getElementById("scr-solvent");
      if (ss) {
        fillSolventSelect(ss, {compose: false});
        if (envS.envType === "진공·기체") ss.value = "";
        else if (envS.customMixedSolvent) { const v = "mix:" + JSON.stringify(envS.customMixedSolvent); ss.add(new Option(`${envS.label} (구성한 혼합 · ${envS.customMixedSolvent.basis})`, v)); ss.value = v; }
        else setSelect("scr-solvent", envS.solventId);
        ss.dispatchEvent(new Event("change"));
      }
      setSelect("scr-structure", L.ext.structure || "모노머");
      toast(`배치 스크리닝 마법사에 ${ids.length}개 후보와 환경 «${envLabel(L.env)}» 을 채웠습니다 — 목록 검증 결과를 확인하세요${L.env.mode === "cluster" ? " (배치에서는 명시적 분자 없이 SMD 만 씁니다)" : ""}`);
      document.getElementById("scr-wizard")?.scrollIntoView({block: "start"});
    }, 250);
  }
  function setSelect(id, v) { const el = document.getElementById(id); if (!el || v == null) return false; if ([...el.options].some(o => o.value === String(v))) { el.value = String(v); el.dispatchEvent(new Event("change")); return true; } return false; }

  /* 계산 화면 — 소재: 분자 검색 및 선택 · 분자 라이브러리에서 고른 분자 목록 */
  const calcItem = m => ({key: m.id, name: m.name, smiles: m.smiles, formula: m.formula, dictId: m.presetId || null, libraryId: m.id});
  function rbLibBuildMaterialGrid() {
    const grid = document.getElementById("material-grid"); if (!grid) return;
    grid.classList.remove("mol-grid"); grid.classList.add("lb-calcsel");
    if (!L.data) { grid.innerHTML = '<div class="small muted">분자 라이브러리 불러오는 중…</div>'; load().then(rbLibBuildMaterialGrid).catch(e => { if (!L.failed) grid.innerHTML = `<div class="form-error">분자 라이브러리를 불러오지 못했습니다 — ${h(e.message)}</div>`; }); return; }
    for (const key of [...selected.keys()]) if (!rec(key)) selected.delete(key);
    const list = [...selected.keys()].map(rec).filter(Boolean);
    grid.innerHTML = `${list.length ? `<div class="lb-calcchips">${list.map(m => `<span class="lb-calcchip" title="${h(m.smiles)}">${svgOf(m, "xs")}<span class="nm"><b>${h(m.name)}</b><span class="small muted">${fmtFormula(m.formula)} · ${h(CAT_LABEL[m.category] || "")}</span></span><button class="btn ghost sm" type="button" data-calcrm="${h(m.id)}" title="계산 목록에서 빼기">✕</button></span>`).join("")}</div>`
        : '<div class="lb-calcempty">계산할 분자를 아직 고르지 않았습니다. 아래 버튼으로 분자 검색 및 선택 또는 분자 라이브러리에서 고르세요.</div>'}
      <div class="toolbar" style="margin:10px 0 0;gap:8px"><button class="btn primary" type="button" data-calcpick="molsearch">＋ 분자 검색 및 선택에서 고르기</button><button class="btn" type="button" data-calcpick="library">＋ 분자 라이브러리에서 고르기</button>
        <span class="small muted">${list.length ? `${list.length}개 — 분자마다 작업이 따로 만들어집니다` : ""}</span>${list.length ? '<button class="btn ghost sm" type="button" data-calcclear="1">모두 빼기</button>' : ""}</div>`;
    grid.querySelectorAll("[data-calcrm]").forEach(b => b.addEventListener("click", () => { selected.delete(b.dataset.calcrm); rbLibBuildMaterialGrid(); }));
    const cl = grid.querySelector("[data-calcclear]"); if (cl) cl.addEventListener("click", () => { selected.clear(); rbLibBuildMaterialGrid(); });
    grid.querySelectorAll("[data-calcpick]").forEach(b => b.addEventListener("click", () => {
      L.pickForCalc = true; L.sel = [...selected.keys()]; saveSel();
      window.rbOpenMode(b.dataset.calcpick, b.dataset.calcpick === "molsearch" ? "분자 검색 및 선택" : "분자 라이브러리");
    }));
  }
  function rbLibSelectInCalc(ids) {
    selected.clear();
    for (const id of ids) { const m = rec(id); if (m) selected.set(m.id, calcItem(m)); }
    rbLibBuildMaterialGrid();
  }
  function rbLibAddToCalc(ids) {
    for (const id of ids) { const m = rec(id); if (m && !selected.has(m.id)) selected.set(m.id, calcItem(m)); }
    rbLibBuildMaterialGrid();
  }

  /* 계산 화면 — 용매 선택 (단일 / 혼합 프리셋 / 직접 구성) */
  const CALC_MIX = {mode: "implicit", basis: "부피비", comps: [{id: "MOL-EC", ratio: 1}, {id: "MOL-DMC", ratio: 1}], name: ""};
  function fillSolventSelect(sel, opts = {}) {
    if (!sel) return;
    if (!L.data) { load().then(() => { fillSolventSelect(sel, opts); if (sel.id === "solvent") calcSolventChanged(); }).catch(() => {}); return; }
    const prev = sel.value;
    sel.innerHTML = "";
    sel.add(new Option("(용매 없음 — 기체상)", ""));
    const g1 = document.createElement("optgroup"); g1.label = "단일 용매 (분자 라이브러리)";
    for (const m of solvents()) g1.appendChild(new Option(`${m.name} — ${m.full || ""} (ε ${nf(m.solvent.eps, 1)})`, m.solventId || m.id));
    sel.appendChild(g1);
    const g2 = document.createElement("optgroup"); g2.label = "혼합 용매 프리셋";
    for (const x of mixes()) { const eff = effMedium({comps: x.components, basis: x.basis}); g2.appendChild(new Option(`${x.name} (${x.basis})${eff.ok ? " · ε " + nf(eff.eps, 1) : ""}${x.builtin ? "" : " · 저장"}`, x.presetSolventId || x.id)); }
    sel.appendChild(g2);
    if (opts.compose) {
      const o = new Option("직접 구성 — 라이브러리 성분 + 비율…", "mix:" + JSON.stringify(composedPayload()));
      o.dataset.compose = "1"; sel.add(o);
    }
    if (prev && [...sel.options].some(o => o.value === prev)) sel.value = prev;
    else if (prev && prev.startsWith("mix:") && opts.compose) sel.value = sel.options[sel.options.length - 1].value;
    else if (typeof PRESETS !== "undefined" && PRESETS && [...sel.options].some(o => o.value === PRESETS.defaults.solventId)) sel.value = PRESETS.defaults.solventId;
  }
  function composedPayload() { const eff = effMedium(CALC_MIX); return {name: eff.ok ? eff.name : (CALC_MIX.name || "혼합"), basis: CALC_MIX.basis, components: CALC_MIX.comps.filter(c => +c.ratio > 0).map(c => ({id: c.id, ratio: +c.ratio}))}; }
  function calcSolventChanged() {
    const sel = document.getElementById("solvent"); if (!sel) return;
    let info = document.getElementById("lb-solv-info");
    if (!info) { info = document.createElement("div"); info.id = "lb-solv-info"; info.className = "lb-solvinfo"; const field = sel.closest(".form-grid"); field.parentNode.insertBefore(info, field.nextSibling); }
    const opt = sel.options[sel.selectedIndex], env = document.querySelector('input[name="env"]:checked')?.value;
    if (!L.data || env === "진공·기체" || !sel.value) { info.innerHTML = ""; return; }
    if (opt && opt.dataset.compose) {
      info.innerHTML = `<div class="lb-sub" style="margin-top:0">혼합 용매 직접 구성 <span class="small muted">— 분자 라이브러리의 용매 성분과 비율(부피비·몰비·질량비)</span></div><div class="lb-envrow"><div id="lb-calc-comp">${composerHtml(CALC_MIX, {save: true})}</div><div>${effTable(CALC_MIX, {raw: true})}</div></div>`;
      wireComposer(info.querySelector("#lb-calc-comp"), CALC_MIX, () => { opt.value = "mix:" + JSON.stringify(composedPayload()); sel.value = opt.value; calcSolventChanged(); }, {after: () => { fillSolventSelect(sel, {compose: true}); calcSolventChanged(); }});
      return;
    }
    let env2 = null;
    const m = solvents().find(x => (x.solventId || x.id) === sel.value), x = mixes().find(y => (y.presetSolventId || y.id) === sel.value);
    if (m) env2 = {mode: "implicit", basis: "부피비", comps: [{id: m.id, ratio: 1}]};
    else if (x) env2 = {mode: "implicit", basis: x.basis, comps: x.components, name: x.name};
    else if (sel.value.startsWith("mix:")) { try { const p = JSON.parse(sel.value.slice(4)); env2 = {mode: "implicit", basis: p.basis || "부피비", comps: (p.components || []).map(c => ({id: c.id || (solvents().find(s => s.name === (c.abbr === "H2O" ? "Water" : c.abbr)) || {}).id, ratio: c.ratio})), name: p.name}; } catch (e) {} }
    if (!env2) { info.innerHTML = ""; return; }
    const eff = effMedium(env2);
    info.innerHTML = eff.ok ? `<div class="small muted">${eff.comps.length > 1 ? `혼합 ${h(eff.name)} — ${eff.comps.map((c, i) => `${h(rec(c.id).name)} ${(eff.w[i] * 100).toFixed(0)}%`).join(" · ")} (부피분율) · ` : ""}유효 ε <b>${nf(eff.eps, 2)}</b> · n ${nf(eff.n, 3)}${x && !x.builtin && !IS_SNAPSHOT ? ` · <a class="btn ghost sm" data-delmix="${h(x.id)}">이 프리셋 삭제</a>` : ""}</div>` : `<div class="form-error">${h(eff.error)}</div>`;
    const dm = info.querySelector("[data-delmix]"); if (dm) dm.addEventListener("click", async () => { if (!confirm(`혼합 용매 프리셋 «${x.name}» 을 지울까요?`)) return; const r = await fetch(`/api/library/mixtures/${encodeURIComponent(x.id)}`, {method: "DELETE"}); if (r.ok) { await load(true); fillSolventSelect(sel, {compose: true}); calcSolventChanged(); } });
  }
  function rbLibSetCalcMixture(cm) {
    const sel = document.getElementById("solvent"); if (!sel) return;
    const go = () => {
      CALC_MIX.basis = cm.basis || "부피비"; CALC_MIX.name = cm.name || "";
      CALC_MIX.comps = (cm.components || []).map(c => ({id: c.id || (solvents().find(s => s.name === (c.abbr === "H2O" ? "Water" : c.abbr)) || {}).id, ratio: c.ratio})).filter(c => c.id);
      fillSolventSelect(sel, {compose: true});
      const o = [...sel.options].find(x => x.dataset.compose); if (o) { o.value = "mix:" + JSON.stringify(composedPayload()); sel.value = o.value; }
      calcSolventChanged();
    };
    if (L.data) go(); else load().then(go).catch(() => {});
  }
  function explicitSpecies() {
    const sv = solvents(), rest = mols().filter(m => !m.solvent && m.fragments === 1 && m.n_atoms <= 30);
    return [...sv.map(m => [m.smiles, `${m.name} — ${m.full || ""} (용매)`]), ...rest.map(m => [m.smiles, `${m.name} — ${m.full || ""}`])];
  }

  /* app.js 가 부르는 연결점 */
  window.rbLibBuildMaterialGrid = rbLibBuildMaterialGrid;
  window.rbLibFillSolventSelect = (sel, opts) => { fillSolventSelect(sel, opts); if (sel && sel.id === "solvent") { if (!sel.dataset.lbWired) { sel.dataset.lbWired = "1"; sel.addEventListener("change", calcSolventChanged); document.querySelectorAll('input[name="env"]').forEach(r => r.addEventListener("change", calcSolventChanged)); } setTimeout(calcSolventChanged, 0); } };
  window.rbLibSetCalcMixture = rbLibSetCalcMixture;
  window.rbLibExplicitSpecies = () => (L.data ? explicitSpecies() : null);
  window.rbLibSelectInCalc = ids => load().then(() => rbLibSelectInCalc(ids));
  window.rbLibAddToCalc = ids => load().then(() => rbLibAddToCalc(ids));
  window.rbLibGoCalc = goCalc;

  /* ── 화면 진입 ── */
  function rerender() {
    const real = document.getElementById("rb-real");
    if (real?.classList.contains("mode-molsearch")) { renderTable(); renderSelPanel(); renderEnvCard(); renderRecent(); }
    if (real?.classList.contains("mode-library")) { renderLibCats(); renderLibFilter(); renderLibResults(); renderLibPanel(); const t = document.getElementById("lb-total"); if (t) t.textContent = `${mols().length}개 분자 · 혼합 용매 ${mixes().length}개`; }
    renderBasket(); refreshPickBars();
  }
  async function enter(fn, rootId) {
    const root = document.getElementById(rootId); if (!root) return;
    if (!L.data) root.innerHTML = root.dataset.built ? root.innerHTML : '<div class="empty">분자 라이브러리 불러오는 중…</div>';
    try { await load(); } catch (e) {
      root.innerHTML = `<div class="card"><div class="form-error">분자 라이브러리를 불러오지 못했습니다 — ${h(e.message)}</div>${L.failed ? '<p class="small muted">서버가 아직 이전 버전입니다. 관리자가 운영 서버를 재시작하면 분자 검색 및 선택 · 분자 라이브러리를 쓸 수 있습니다. 그동안 «계산» 화면은 예전 소재·용매 목록으로 동작합니다.</p>' : ""}</div>`;
      delete root.dataset.built; return;
    }
    if (!root.dataset.built) root.innerHTML = "";
    fn(); renderBasket();
    renderPickBar(rootId);
    if (rootId === "rbv-library" && L.pendingAdd) { const p = L.pendingAdd; L.pendingAdd = null; openAddForm(p); }
  }
  window.rbRenderMolSearch = () => enter(renderMolSearch, "rbv-molsearch");
  window.rbRenderLibrary = () => enter(renderLibrary, "rbv-library");
  window.rbLibRefresh = async () => { if (!L.data) return; await load(true); rerender(); };
  // 계산 결과가 생기면 계산 이력·상태를 갱신 (라이브러리 화면을 보고 있을 때만, 30초 간격)
  if (!IS_SNAPSHOT) setInterval(() => { const real = document.getElementById("rb-real"); if (real && (real.classList.contains("mode-molsearch") || real.classList.contains("mode-library")) && L.data && !document.hidden) window.rbLibRefresh(); }, 30000);
  document.addEventListener("click", e => { const b = e.target.closest && e.target.closest("[data-addsolv]"); if (b && document.getElementById("lb-spanel")?.contains(b)) addSolvent(b.dataset.addsolv); });
})();
