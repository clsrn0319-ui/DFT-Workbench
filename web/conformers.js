/* ------------------------------------------------------------------
   Conformer 탐색 (#rbv-conf) — 구조 준비 작업공간
     구조 찾기(역장, 수 초)와 DFT 계산(큐, 수 시간)을 나눈다.
     왼쪽: 세트·conformer 목록 · 가운데: 3D 작업공간 + 썸네일 · 오른쪽: 준비/Conformer/DFT 패널
     POST /api/conformers/search · GET /api/conformers[/{id}] · POST /{id}/rank · DELETE /{id}
   ------------------------------------------------------------------ */
(function () {
  "use strict";
  var IS_SNAPSHOT = !!window.__RB_SNAPSHOT__;
  var S = {
    sets: [], doc: null, cur: 1, sel: new Set(), tab: "prep", overlay: false,
    busy: false, error: "", timer: null,
    lib: null, libOpen: false, libQuery: "",
    play: {on: false, order: "energy", pos: 0, raf: null, t0: 0},   // 탐색 과정 재생
    form: {smiles: "", name: "", libraryId: null, structure: "모노머", reference: "all-trans",
           pattern: "T G T G'", nConformers: 20, seed: 42, pruneRms: 0.5},
  };
  var CAT = {monomer: "바인더 모노머", polymer: "고분자·올리고머", solvent: "용매", additive: "첨가제", salt: "리튬염·이온", other: "기타"};
  var $ = function (id) { return document.getElementById(id); };
  function h(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c];
    });
  }
  function f2(v) { return v == null || isNaN(v) ? "—" : Number(v).toFixed(2); }
  function root() { return $("rbv-conf"); }
  function confs() { return (S.doc && S.doc.conformers) || []; }
  function byIndex(i) { return confs().find(function (c) { return c.index === i; }); }
  function xyz(c) {
    var name = (S.doc.molecule.name || "") + " conf #" + c.index;
    return c.atoms.length + "\n" + name + "\n" +
      c.atoms.map(function (a) { return a[0] + " " + a[1] + " " + a[2] + " " + a[3]; }).join("\n");
  }
  function refLabel() {
    var s = (S.doc && S.doc.settings) || {};
    return s.reference === "all-trans" ? "all-trans"
      : s.reference === "pattern" ? "패턴 " + (s.pattern || "") : "최저 에너지";
  }

  /* ── 통신 ── */
  async function api(url, opts) {
    var res = await fetch(url, opts);
    if (!res.ok) {
      var e = await res.json().catch(function () { return {}; });
      throw new Error(e.detail || ("HTTP " + res.status));
    }
    return res.json();
  }
  async function loadSets() {
    try { S.sets = (await api("/api/conformers")).sets || []; } catch (e) { S.sets = []; }
  }
  async function openSet(id) {
    try {
      S.doc = await api("/api/conformers/" + encodeURIComponent(id));
      S.cur = (confs()[0] || {}).index || 1;
      S.sel = new Set(confs().filter(function (c) { return c.is_reference; }).map(function (c) { return c.index; }));
      if (!S.sel.size && confs().length) S.sel.add(confs()[0].index);
      S.error = "";
    } catch (e) { S.error = e.message; }
    render();
    pollRank();
  }
  async function search() {
    if (S.busy) return;
    S.busy = true; S.error = ""; render();
    try {
      var body = Object.assign({}, S.form);
      body.nConformers = +body.nConformers; body.seed = +body.seed; body.pruneRms = +body.pruneRms;
      if (body.reference !== "pattern") body.pattern = null;
      S.doc = await api("/api/conformers/search", {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
      });
      S.cur = (confs()[0] || {}).index || 1;
      S.sel = new Set(confs().filter(function (c) { return c.is_reference; }).map(function (c) { return c.index; }));
      if (!S.sel.size && confs().length) S.sel.add(confs()[0].index);
      await loadSets();
    } catch (e) { S.error = e.message; }
    S.busy = false; render();
  }
  async function rank() {
    if (!S.doc || !S.sel.size) return;
    try {
      S.doc = await api("/api/conformers/" + encodeURIComponent(S.doc.id) + "/rank", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({indices: [...S.sel]}),
      });
      if (window.rbToast) window.rbToast("DFT 재순위를 시작했습니다 — 끝나면 표가 갱신됩니다");
    } catch (e) { S.error = e.message; }
    render(); pollRank();
  }
  function pollRank() {
    clearTimeout(S.timer);
    var st = S.doc && S.doc.rank_status;
    if (!st || st.state !== "running") return;
    S.timer = setTimeout(async function () {
      if (!S.doc) return;
      try {
        var d = await api("/api/conformers/" + encodeURIComponent(S.doc.id));
        S.doc = d; render(); pollRank();
      } catch (e) { /* 다음 주기에 다시 */ }
    }, 5000);
  }
  async function removeSet() {
    if (!S.doc || !confirm(S.doc.id + " 세트를 지울까요? 이 세트로 만든 계산 결과는 그대로 남습니다.")) return;
    try { await api("/api/conformers/" + encodeURIComponent(S.doc.id), {method: "DELETE"}); } catch (e) { S.error = e.message; }
    S.doc = null; await loadSets(); render();
  }
  function toCalc() {
    if (!S.doc || !S.sel.size) return;
    window.rbConfPick = {setId: S.doc.id, name: S.doc.molecule.name, reference: refLabel(),
                         indices: [...S.sel].sort(function (a, b) { return a - b; })};
    if (window.rbSyncConfPick) window.rbSyncConfPick();
    if (window.rbOpenCalc) window.rbOpenCalc();
  }
  async function openLib() {
    S.libOpen = !S.libOpen;
    if (S.libOpen && !S.lib) {
      try { S.lib = (await api("/api/library")).molecules || []; }
      catch (e) { S.error = "분자 라이브러리를 불러오지 못했습니다 — " + e.message; S.libOpen = false; }
    }
    render();
  }
  function pickMolecule(id) {
    var m = (S.lib || []).find(function (x) { return x.id === id; });
    if (!m) return;
    S.form.smiles = m.smiles; S.form.name = m.name; S.form.libraryId = m.id;
    S.libOpen = false; S.error = "";
    render();
  }
  function libRows() {
    var q = (S.libQuery || "").trim().toLowerCase();
    var list = (S.lib || []).filter(function (m) {
      if (!q) return true;
      return [m.name, m.full, m.formula, m.smiles, (m.tags || []).join(" ")]
        .some(function (v) { return (v || "").toLowerCase().indexOf(q) >= 0; });
    });
    var sel = (window.RBLIB && window.RBLIB.sel) || [];
    list.sort(function (a, b) { return (sel.indexOf(b.id) >= 0) - (sel.indexOf(a.id) >= 0); });
    return list.slice(0, 200).map(function (m) {
      return '<div class="cf-librow" data-mol="' + h(m.id) + '">' +
        "<b>" + h(m.name) + "</b>" +
        '<span class="small muted">' + h(m.formula || "") + " · " + h(CAT[m.category] || m.category || "") +
        (sel.indexOf(m.id) >= 0 ? ' · <span class="chip">선택함</span>' : "") + "</span>" +
        '<span class="mono small muted sp">' + h((m.smiles || "").slice(0, 28)) + "</span></div>";
    }).join("") || '<div class="small muted">맞는 분자가 없습니다.</div>';
  }

  /* ── 그리기 ── */
  function viewer() {
    var box = $("cf-view");
    if (!box || !S.doc) return;
    var list = S.overlay ? [...S.sel].map(byIndex).filter(Boolean) : [byIndex(S.cur)].filter(Boolean);
    if (!list.length) return;
    box.innerHTML = "";
    if (S.overlay) {
      // 겹쳐 보기 — 선택 구조를 나란히 (뷰어 하나에 여러 분자를 섞지 않고 격자로)
      box.className = "cf-grid";
      list.forEach(function (c) {
        var cell = document.createElement("div");
        cell.className = "cf-cell";
        cell.innerHTML = '<div class="small muted">#' + c.index + (c.is_reference ? " · 기준" : "") +
          " · " + f2(c.ff_energy) + " kcal/mol</div><div class='cf-box'></div>";
        box.appendChild(cell);
        window.render3D({structure_xyz: xyz(c)}, {box: cell.querySelector(".cf-box"), mode: "element", static: true});
      });
    } else {
      box.className = "";
      var d = document.createElement("div");
      d.className = "cf-box main";
      box.appendChild(d);
      window.render3D({structure_xyz: xyz(list[0])}, {box: d, mode: "element"});
    }
  }
  /* ── 탐색 과정 재생 ──────────────────────────────────────────────────────────
     ETKDG 는 구조를 독립적으로 무작위 생성하므로 «경로»가 있는 것은 아니다.
     여기서 보여 주는 것은 생성된 구조들을 한 줄로 세워 이어 보는 것이고,
     순서는 에너지 순(어떻게 접히며 안정해지는가)과 생성 순(탐색이 훑은 차례) 둘이다.
     구조 사이는 좌표를 선형 보간해 부드럽게 넘긴다 — 중간 모습은 보기 위한 전환이다. */
  var STEP_MS = 900;

  function energyOf(c) { return c.dft_energy != null ? c.dft_rel_kcal != null ? c.dft_rel_kcal : c.ff_energy : c.ff_energy; }
  function ordered() {
    var list = confs().slice();
    if (S.play.order === "energy") list.sort(function (a, b) { return energyOf(a) - energyOf(b); });
    else list.sort(function (a, b) { return a.index - b.index; });
    return list;
  }
  /** 비틀림각을 T / G / G' 로 — 사슬이 어떤 모양인지 한 줄로 */
  function torsionWord(c) {
    return (c.torsions || []).map(function (t) {
      var v = ((t + 180) % 360 + 360) % 360 - 180;
      return Math.abs(v) > 150 ? "T" : v > 0 ? "G" : "G'";
    }).join(" ") || "—";
  }
  function lerpXyz(a, b, t) {
    var name = (S.doc.molecule.name || "") + " 재생";
    var lines = a.atoms.map(function (at, i) {
      var bt = b.atoms[i] || at;
      return at[0] + " " + (at[1] + (bt[1] - at[1]) * t).toFixed(4) + " " +
        (at[2] + (bt[2] - at[2]) * t).toFixed(4) + " " + (at[3] + (bt[3] - at[3]) * t).toFixed(4);
    });
    return a.atoms.length + "\n" + name + "\n" + lines.join("\n");
  }
  function playFrame(ts) {
    var P = S.play, list = ordered();
    if (!P.on || list.length < 2) return;
    if (!P.t0) P.t0 = ts;
    var span = (ts - P.t0) / STEP_MS;
    var i = P.pos + Math.floor(span), t = span - Math.floor(span);
    if (i >= list.length - 1) { i = list.length - 1; t = 0; P.on = false; }
    var a = list[i], b = list[Math.min(i + 1, list.length - 1)];
    var box = $("cf-view");
    if (box) window.render3D({structure_xyz: t > 0.01 ? lerpXyz(a, b, t) : xyz(a)}, {box: box, mode: "element"});
    if (S.cur !== a.index) { S.cur = a.index; syncCurrent(); }
    updatePlayBar(i, list);
    if (P.on) P.raf = requestAnimationFrame(playFrame);
    else { P.pos = i; P.t0 = 0; updatePlayBar(i, list); }
  }
  function playToggle() {
    var P = S.play;
    if (P.on) { P.on = false; cancelAnimationFrame(P.raf); P.t0 = 0; var l = ordered(); P.pos = Math.max(0, l.findIndex(function (c) { return c.index === S.cur; })); }
    else {
      var list = ordered();
      if (P.pos >= list.length - 1) P.pos = 0;
      P.on = true; P.t0 = 0; P.raf = requestAnimationFrame(playFrame);
    }
    updatePlayBar(S.play.pos, ordered());
  }
  function playSeek(i) {
    var P = S.play, list = ordered();
    P.on = false; cancelAnimationFrame(P.raf); P.t0 = 0;
    P.pos = Math.max(0, Math.min(list.length - 1, i));
    S.cur = list[P.pos].index;
    viewer(); syncCurrent(); updatePlayBar(P.pos, list);
  }
  /** 재생 중에는 전체를 다시 그리지 않고 강조만 옮긴다 */
  function syncCurrent() {
    var el = root();
    if (!el) return;
    el.querySelectorAll(".cf-node").forEach(function (n) { n.classList.toggle("on", +n.dataset.conf === S.cur); });
    el.querySelectorAll(".cf-thumb").forEach(function (n) { n.classList.toggle("on", +n.dataset.conf === S.cur); });
    el.querySelectorAll("tr[data-conf]").forEach(function (n) { n.classList.toggle("on", +n.dataset.conf === S.cur); });
    if (S.tab === "map") drawMap();
  }
  function playBarHtml() {
    var list = ordered();
    if (list.length < 2) return "";
    var seg = function (v, on) { return '<button type="button" class="btn sm ' + (on ? "primary" : "") + '" data-ord="' + v + '">' + (v === "energy" ? "에너지 순" : "생성 순") + "</button>"; };
    return '<div class="cf-play"><div class="cf-playrow">' +
      '<button class="btn sm" type="button" id="cf-playbtn" data-act="play">' + (S.play.on ? "⏸ 멈춤" : "▶ 재생") + "</button>" +
      seg("energy", S.play.order === "energy") + seg("gen", S.play.order === "gen") +
      '<span class="small muted" id="cf-playpos" style="margin-left:auto"></span></div>' +
      '<div class="cf-ebar" id="cf-ebar"></div>' +
      '<div class="small" id="cf-playlab"></div>' +
      '<p class="small muted" style="margin:2px 0 0">구조 사이는 보기 위한 전환입니다 — 실제 분자가 지나간 경로가 아닙니다.</p></div>';
  }
  function updatePlayBar(i, list) {
    var bar = $("cf-ebar"), pos = $("cf-playpos"), lab = $("cf-playlab");
    if (!bar) return;
    list = list || ordered();
    var es = list.map(energyOf), hi = Math.max.apply(null, es) || 1;
    bar.innerHTML = list.map(function (c, k) {
      var hgt = 6 + (energyOf(c) / hi) * 26;
      return '<i data-seek="' + k + '" class="' + (k === i ? "on" : k < i ? "done" : "") + '" style="height:' + hgt.toFixed(1) + 'px" title="#' + c.index + " · " + f2(energyOf(c)) + ' kcal/mol"></i>';
    }).join("");
    bar.querySelectorAll("[data-seek]").forEach(function (b) {
      b.addEventListener("click", function () { playSeek(+b.dataset.seek); });
    });
    var c = list[i];
    if (pos) pos.textContent = (i + 1) + " / " + list.length;
    if (lab && c) {
      lab.innerHTML = "#" + c.index + (c.is_reference ? ' <span class="star">★</span>' : "") +
        " · ΔE " + f2(energyOf(c)) + " kcal/mol" +
        (c.population_pct != null ? " · 존재 비율 " + c.population_pct + "%" : "") +
        " · 비틀림 " + h(torsionWord(c));
    }
  }

  function thumbs() {
    var strip = $("cf-strip");
    if (!strip || !S.doc) return;
    strip.innerHTML = confs().map(function (c) {
      return '<div class="cf-thumb ' + (S.cur === c.index ? "on" : "") + '" data-conf="' + c.index + '">' +
        '<div class="cf-tbox" data-tb="' + c.index + '"></div>' +
        '<div class="cap">' + (c.is_reference ? '<span class="star">★</span>' : "") + "#" + c.index +
        " · " + f2(c.ff_energy) + "</div></div>";
    }).join("");
    confs().forEach(function (c) {
      var box = strip.querySelector('[data-tb="' + c.index + '"]');
      if (box) window.render3D({structure_xyz: xyz(c)}, {box: box, mode: "element", static: true});
    });
  }

  /* ── 지도 — 주사슬 비틀림각 평면에 구조를 찍는다 (어디를 훑었고 어디가 비었나) ── */
  function panelMap() {
    var n = ((confs()[0] || {}).torsions || []).length;
    if (n < 2) {
      return '<div class="cf-sect"><h4>비틀림각 지도</h4><p class="small muted">주사슬 비틀림이 ' + n +
        '개뿐이라 평면으로 그릴 수 없습니다. 2량체·3량체로 탐색하면 지도가 나옵니다.</p></div>';
    }
    return '<div class="cf-sect"><h4>비틀림각 지도</h4>' +
      '<div id="cf-map"></div>' +
      '<p class="small muted" style="margin:6px 0 0">가로·세로는 주사슬 첫 두 비틀림각(φ₁ · φ₂)입니다. ' +
      '점이 몰린 곳은 여러 번 나온 모양, 빈 곳은 탐색이 닿지 않은 영역입니다 — 빈 곳이 넓으면 개수를 늘려 보세요. ' +
      '점을 누르면 그 구조로 갑니다.</p></div>';
  }
  function drawMap() {
    var box = $("cf-map");
    if (!box) return;
    var list = confs().filter(function (c) { return (c.torsions || []).length >= 2; });
    if (!list.length) { box.innerHTML = ""; return; }
    var W = 300, H = 300, M = 26;
    var X = function (v) { return M + (((v + 180) % 360 + 360) % 360) / 360 * (W - M - 8); };
    var Y = function (v) { return H - M - (((v + 180) % 360 + 360) % 360) / 360 * (H - M - 8); };
    var es = list.map(energyOf), hi = Math.max.apply(null, es) || 1;
    var s = '<svg viewBox="0 0 ' + W + " " + H + '" style="width:100%;max-width:320px" role="img" aria-label="비틀림각 지도">';
    [-180, -90, 0, 90, 180].forEach(function (g) {
      s += '<line x1="' + X(g) + '" y1="' + M + '" x2="' + X(g) + '" y2="' + (H - M) + '" class="gridline"/>' +
        '<line x1="' + M + '" y1="' + Y(g) + '" x2="' + (W - 8) + '" y2="' + Y(g) + '" class="gridline"/>' +
        '<text x="' + X(g) + '" y="' + (H - M + 13) + '" text-anchor="middle" class="axis-label">' + g + "</text>" +
        '<text x="' + (M - 5) + '" y="' + (Y(g) + 3.5) + '" text-anchor="end" class="axis-label">' + g + "</text>";
    });
    s += '<text x="' + (W / 2) + '" y="' + (H - 4) + '" text-anchor="middle" class="axis-label">φ₁ (°)</text>' +
      '<text x="8" y="' + (M - 10) + '" class="axis-label">φ₂ (°)</text>';
    list.forEach(function (c) {
      var on = c.index === S.cur, t = energyOf(c) / hi;
      s += '<circle data-mapi="' + c.index + '" cx="' + X(c.torsions[0]) + '" cy="' + Y(c.torsions[1]) +
        '" r="' + (on ? 7 : 4.5) + '" fill="' + (on ? "var(--accent)" : "var(--muted)") +
        '" fill-opacity="' + (on ? 1 : (1 - t * 0.6).toFixed(2)) + '" style="cursor:pointer">' +
        "<title>#" + c.index + " · ΔE " + f2(energyOf(c)) + " kcal/mol · " + torsionWord(c) + "</title></circle>";
    });
    box.innerHTML = s + "</svg>";
    box.querySelectorAll("[data-mapi]").forEach(function (p) {
      p.addEventListener("click", function () {
        var list2 = ordered(), i = list2.findIndex(function (c) { return c.index === +p.dataset.mapi; });
        playSeek(i < 0 ? 0 : i);
      });
    });
  }

  function panelPrep() {
    var m = S.doc.molecule, s = S.doc.settings;
    var steps = [["분자 입력", m.structure], ["3D 생성 (ETKDG)", "seed " + s.seed],
                 ["역장 최적화", s.forcefield], ["Conformer 탐색", s.n_generated + "개 → " + confs().length + "개"],
                 ["기준 구조", refLabel()]];
    return '<div class="cf-sect"><h4>분자</h4><div class="cf-kv">' +
      kv("이름", m.name) + kv("SMILES", '<span class="mono small">' + h(m.smiles) + "</span>") +
      kv("구조", m.structure) + kv("원자 수", m.n_atoms) +
      kv("주사슬", (s.backbone || []).join("") || "—") +
      kv("세트", '<span class="mono small">' + h(S.doc.id) + "</span>") + "</div></div>" +
      '<div class="cf-sect"><h4>준비 단계</h4>' + steps.map(function (p) {
        return '<div class="cf-step"><span class="mk">✓</span>' + h(p[0]) +
          '<span class="sp">' + h(p[1]) + "</span></div>";
      }).join("") +
      '<div class="cf-step"><span class="mk ' + (anyRanked() ? "" : "todo") + '">' + (anyRanked() ? "✓" : "·") +
      '</span>DFT 재순위<span class="sp">' + rankText() + "</span></div></div>" +
      '<div class="cf-sect"><h4>다음</h4><p class="small muted" style="margin:0 0 8px">' +
      '고른 구조로 계산을 보내면 conformer 마다 작업이 하나씩 생기고, 결과에 기준 구조와 conformer 번호가 남습니다.</p>' +
      '<button class="btn primary" style="width:100%" data-act="tocalc">선택 ' + S.sel.size + '개로 계산 →</button></div>';
  }
  function panelConf() {
    var rows = confs().map(function (c) {
      var flip = c.dft_energy != null && lowestFf() !== c.index && c.dft_energy === lowestDft();
      return '<tr data-conf="' + c.index + '" class="' + (S.cur === c.index ? "on" : "") + '">' +
        '<td><input type="checkbox" data-chk="' + c.index + '"' + (S.sel.has(c.index) ? " checked" : "") + "></td>" +
        "<td>" + (c.is_reference ? '<span class="star">★</span>' : "") + c.index + "</td>" +
        '<td class="num">' + f2(c.ff_energy) + "</td>" +
        '<td class="num">' + (c.dft_energy == null ? "—" : f2(c.dft_energy) + (flip ? " ↑" : "")) + "</td>" +
        '<td class="num">' + (c.population_pct == null ? "—" : c.population_pct + "%") + "</td>" +
        '<td class="num">' + f2(c.rmsd_to_reference) + "</td></tr>";
    }).join("");
    var c = byIndex(S.cur) || {};
    return '<div class="cf-sect"><h4>Conformer ' + confs().length + "개 <span class='sp'>선택 " + S.sel.size + "</span></h4>" +
      '<div class="cf-tw"><table><thead><tr><th></th><th>#</th><th class="num">역장 ΔE</th>' +
      '<th class="num">DFT ΔE</th><th class="num">비율</th><th class="num">RMSD</th></tr></thead><tbody>' +
      rows + "</tbody></table></div>" +
      '<p class="small muted" style="margin:6px 0 0">ΔE kcal/mol (가장 낮은 구조 기준) · RMSD Å (1번 구조 대비) · ↑ = DFT 로 순위가 올라간 구조</p></div>' +
      '<div class="cf-sect"><h4>선택 구조 #' + S.cur + "</h4><div class='cf-kv'>" +
      kv("기준 구조", c.is_reference ? "예" : "아니오") +
      kv("주사슬 비틀림", (c.torsions || []).map(function (t) { return Math.round(t) + "°"; }).join(" · ") || "—") +
      kv("역장 ΔE", f2(c.ff_energy) + " kcal/mol") +
      kv("DFT ΔE", c.dft_energy == null ? "재순위 안 함" : f2(c.dft_energy) + " kcal/mol") +
      kv("1번 대비 RMSD", f2(c.rmsd_to_reference) + " Å") + "</div></div>" +
      '<button class="btn" style="width:100%;margin-bottom:7px" data-act="rank"' +
      (S.sel.size && !ranking() ? "" : " disabled") + ">선택 " + S.sel.size + "개 DFT 재순위" +
      (ranking() ? " (진행 중)" : "") + "</button>" +
      '<button class="btn primary" style="width:100%" data-act="tocalc"' + (S.sel.size ? "" : " disabled") +
      ">선택 " + S.sel.size + "개로 계산 →</button>";
  }
  function panelDft() {
    return '<div class="cf-sect"><h4>계산으로 보내기</h4><p class="small muted" style="margin:0 0 8px">' +
      '계산 조건(범함수·기저·용매·정확도)은 «계산» 화면에서 고릅니다. 여기서 고른 구조가 그대로 초기 구조가 되고, ' +
      'conformer 탐색은 다시 하지 않습니다.</p><div class="cf-kv">' +
      kv("기준 구조", refLabel()) + kv("세트", '<span class="mono small">' + h(S.doc.id) + "</span>") +
      kv("보낼 구조", "#" + [...S.sel].sort(function (a, b) { return a - b; }).join(", #")) +
      kv("만들 작업 수", S.sel.size + "건") + "</div>" +
      '<button class="btn primary" style="width:100%;margin-top:9px" data-act="tocalc"' +
      (S.sel.size ? "" : " disabled") + ">계산 화면으로 →</button></div>" +
      '<div class="cf-sect"><h4>DFT 재순위</h4><p class="small muted" style="margin:0 0 8px">' +
      '고른 구조만 단일점 DFT(빠름 프리셋 · 진공)로 다시 계산해 순위를 바로잡습니다. 본 계산과 별개로 돌며, ' +
      '구조 최적화는 하지 않습니다.</p>' + (S.doc.rank_status ? '<div class="cf-kv">' +
        kv("상태", h(rankText())) + (S.doc.rank_status.method ? kv("방법", h(S.doc.rank_status.method)) : "") +
        (S.doc.rank_status.error ? kv("오류", h(S.doc.rank_status.error)) : "") + "</div>" : "") +
      '<button class="btn" style="width:100%;margin-top:9px" data-act="rank"' +
      (S.sel.size && !ranking() ? "" : " disabled") + ">선택 " + S.sel.size + "개 재순위</button></div>" +
      '<div class="cf-sect"><h4>세트</h4><button class="btn ghost danger" style="width:100%" data-act="del">이 세트 지우기</button></div>';
  }
  function kv(k, v) { return "<b>" + h(k) + "</b><span>" + v + "</span>"; }
  function anyRanked() { return confs().some(function (c) { return c.dft_energy != null; }); }
  function ranking() { return !!(S.doc && S.doc.rank_status && S.doc.rank_status.state === "running"); }
  function rankText() {
    var st = S.doc && S.doc.rank_status;
    if (!st) return "안 함";
    if (st.state === "running") return "진행 중 " + st.done + "/" + st.total;
    return "완료 " + st.done + "/" + st.total;
  }
  function lowestFf() { var c = confs().slice().sort(function (a, b) { return a.ff_energy - b.ff_energy; })[0]; return c && c.index; }
  function lowestDft() {
    var r = confs().filter(function (c) { return c.dft_energy != null; })
      .sort(function (a, b) { return a.dft_energy - b.dft_energy; })[0];
    return r && r.dft_energy;
  }

  function render() {
    var el = root();
    if (!el) return;
    var f = S.form;
    // 저장된 세트는 «분자»로 묶어서 보여 준다 — 같은 분자의 세트가 흩어져 보이지 않게.
    // 라이브러리에 없는 세트는 맨 아래 따로 모으고, 고르면 «라이브러리에 등록»을 띄운다.
    var groups = {}, loose = [];
    S.sets.forEach(function (s) {
      if (s.library) (groups[s.library.name || s.library.id] = groups[s.library.name || s.library.id] || []).push(s);
      else loose.push(s);
    });
    var when = function (t) {
      return t ? new Date(t * 1000).toLocaleString("ko-KR",
        {month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false}) : "";
    };
    var rowOf = function (s) {
      var m = s.molecule || {}, st = (m.structure || "모노머");
      var ref = ((m.reference || (s.settings || {}).reference) === "all-trans") ? "all-trans"
        : ((m.reference || (s.settings || {}).reference) === "pattern" ? "비틀림 패턴" : "자동");
      var rank = s.n_ranked ? "DFT 재순위 " + s.n_ranked : (s.rank_status === "running" ? "재순위 중" : "역장 순위");
      return '<button type="button" class="cf-setrow' + (S.doc && S.doc.id === s.id ? " on" : "") +
        '" data-set="' + h(s.id) + '"><span class="t">' + h(st + " · " + ref) + "</span>" +
        '<span class="d">' + s.n_conformers + "개 · " + h(rank) + "</span>" +
        '<span class="d">' + h(when(s.createdAt)) + "</span></button>";
    };
    var setList = '<div class="cf-sethead">저장된 세트 <span class="chip">' + S.sets.length + "개</span></div>" +
      '<button type="button" class="cf-setrow new' + (S.doc ? "" : " on") + '" data-set="">＋ 새로 탐색</button>' +
      Object.keys(groups).sort().map(function (name) {
        return '<div class="cf-setgrp">' + h(name) + "</div>" + groups[name].map(rowOf).join("");
      }).join("") +
      (loose.length ? '<div class="cf-setgrp loose">라이브러리에 없는 분자</div>' + loose.map(function (s) {
        return '<button type="button" class="cf-setrow' + (S.doc && S.doc.id === s.id ? " on" : "") +
          '" data-set="' + h(s.id) + '"><span class="t">' + h((s.molecule || {}).name || s.id) + "</span>" +
          '<span class="d">' + h((s.molecule || {}).structure || "") + " · " + s.n_conformers + "개</span>" +
          '<span class="d">' + h(when(s.createdAt)) + "</span></button>";
      }).join("") : "") +
      (S.sets.length ? "" : '<p class="small muted" style="padding:8px">아직 저장된 세트가 없습니다.</p>');
    var head = '<h1>Conformer 탐색</h1>' +
      '<p class="rb-note">구조를 먼저 찾아 눈으로 확인하고, 고른 구조로만 DFT 계산을 돌립니다. 탐색은 역장 계산이라 ' +
      '수 초면 끝나고 계산 큐를 쓰지 않습니다. 여러 분자를 비교할 때는 기준 구조(all-trans 등)를 맞춰 두면 ' +
      '사슬 모양 차이가 값 차이에 섞이지 않습니다.</p>' +
      '<div class="cf-page"><aside class="card cf-setlist">' + setList + "</aside><div class='cf-main'>" +
      '<div class="card"><div class="card-head"><h2>분자와 탐색 설정</h2></div>' +
      '<div class="cf-fields">' +
      field("분자 이름", '<input class="input" id="cf-name" value="' + h(f.name) + '" placeholder="예: PVDF 3량체">') +
      field("SMILES", '<input class="input" id="cf-smiles" value="' + h(f.smiles) + '" placeholder="예: C=C(F)F" style="min-width:220px">') +
      field("&nbsp;", '<button class="btn" id="cf-lib" type="button">＋ 분자 라이브러리에서 고르기</button>') +
      field("구조", select("cf-structure", ["모노머", "2량체", "3량체"], f.structure)) +
      field("기준 구조", select("cf-reference", [["auto", "자동 (최저 에너지)"], ["all-trans", "all-trans"], ["pattern", "비틀림 패턴"]], f.reference)) +
      (f.reference === "pattern" ? field("패턴", '<input class="input" id="cf-pattern" value="' + h(f.pattern) + '" placeholder="T G T G\'" style="width:130px">') : "") +
      field("개수", '<input class="input" id="cf-n" type="number" value="' + f.nConformers + '" style="width:80px">') +
      field("중복 제거 RMSD", '<input class="input" id="cf-prune" type="number" step="0.1" value="' + f.pruneRms + '" style="width:80px">') +
      field("seed", '<input class="input" id="cf-seed" type="number" value="' + f.seed + '" style="width:80px">') +
      field("&nbsp;", '<button class="btn primary" id="cf-go" type="button"' + (S.busy ? " disabled" : "") + ">" +
        (S.busy ? "탐색 중…" : "탐색") + "</button>") +
      "</div>" +
      (S.libOpen ? '<div class="cf-libpick"><div class="toolbar" style="gap:8px;margin-bottom:6px">' +
        '<input class="input" id="cf-libq" placeholder="이름 · 화학식 · SMILES 로 찾기" value="' + h(S.libQuery) + '" style="max-width:260px">' +
        '<span class="small muted">' + ((S.lib || []).length) + '개 · 선택함에 담은 분자가 위에 옵니다</span>' +
        '<button class="btn ghost sm" type="button" id="cf-libclose" style="margin-left:auto">닫기</button></div>' +
        '<div class="cf-liblist">' + libRows() + "</div></div>" : "") +
      (S.error ? '<div class="form-error">' + h(S.error) + "</div>" : "") +
      linkBanner() + "</div>";

    if (!S.doc) {
      el.innerHTML = head + '<div class="card"><div class="empty small">분자를 넣고 «탐색»을 누르거나, ' +
        '왼쪽에서 저장된 세트를 고르세요.</div></div></div></div>';
      wire();
      return;
    }
    el.innerHTML = head +
      '<div class="card cf-work"><div class="cf-left">' +
      '<div class="cf-phead">구조 <span class="chip">' + confs().length + "개</span></div>" +
      '<div class="cf-list">' + confs().map(function (c) {
        return '<div class="cf-node ' + (S.cur === c.index ? "on" : "") + '" data-conf="' + c.index + '">' +
          '<input type="checkbox" data-chk="' + c.index + '"' + (S.sel.has(c.index) ? " checked" : "") + ">" +
          (c.is_reference ? '<span class="star">★</span>' : '<span class="star" style="opacity:.25">☆</span>') +
          "#" + c.index + '<span class="sp">' + f2(c.ff_energy) + "</span></div>";
      }).join("") + "</div>" +
      '<div class="cf-phead" style="margin-top:10px">기준</div><div class="small muted">' + h(refLabel()) +
      "<br>" + h((S.doc.settings.backbone || []).join("") || "주사슬 없음") + "</div></div>" +

      '<div class="cf-center"><div class="cf-chead"><b>3D 작업공간</b>' +
      '<span class="chip">기준 ' + h(refLabel()) + "</span>" +
      '<span class="sp"><button class="btn sm ' + (S.overlay ? "primary" : "") + '" data-act="overlay">겹쳐 보기</button></span></div>' +
      '<div id="cf-view"></div>' + playBarHtml() + '<div class="cf-strip" id="cf-strip"></div></div>' +

      '<div class="cf-right"><div class="cf-tabs">' +
      [["prep", "준비"], ["conf", "Conformer"], ["map", "지도"], ["dft", "계산"]].map(function (t) {
        return '<button data-tab="' + t[0] + '" class="' + (S.tab === t[0] ? "on" : "") + '">' + t[1] + "</button>";
      }).join("") + "</div><div class='cf-rbody'>" +
      (S.tab === "prep" ? panelPrep() : S.tab === "conf" ? panelConf()
        : S.tab === "map" ? panelMap() : panelDft()) + "</div></div></div></div></div>";
    wire();
    viewer();
    thumbs();
    updatePlayBar(S.play.pos, ordered());
    if (S.tab === "map") drawMap();
  }
  /** 이 세트의 분자를 라이브러리에 등록하고 세트를 그 분자 아래로 묶는다 */
  async function linkToLibrary() {
    if (!S.doc) return;
    try {
      var r = await api("/api/conformers/" + encodeURIComponent(S.doc.id) + "/library", {method: "POST"});
      await loadSets();
      if (window.rbReloadMaterials) window.rbReloadMaterials();
      if (window.rbToast) window.rbToast("분자 라이브러리의 «" + (r.library || {}).name + "» 아래로 묶었습니다");
      render();
    } catch (e) {
      S.error = e.message || "등록에 실패했습니다";
      render();
    }
  }

  /** 열린 세트가 라이브러리 분자와 묶여 있는지 알려 준다 — 안 묶였으면 등록 단추 */
  function linkBanner() {
    if (!S.doc) return "";
    var s = (S.sets || []).find(function (x) { return x.id === S.doc.id; });
    if (!s) return "";
    if (s.library) {
      return '<p class="small muted" style="margin:8px 0 0">분자 라이브러리의 «' + h(s.library.name) +
        '» 아래에 있습니다' + (s.linked_by === "smiles" ? " (SMILES 로 자동 연결)" : "") +
        ' — 그 분자의 «conformer 세트» 탭에서 다시 찾을 수 있습니다.</p>';
    }
    return '<div class="banner warn" style="margin:8px 0 0">이 세트는 분자 라이브러리에 없는 분자입니다 — ' +
      '등록해 두면 분자 아래에 모여 다음에 찾기 쉽습니다. ' +
      '<button class="btn sm" type="button" id="cf-link" style="margin-left:6px">라이브러리에 등록</button></div>';
  }

  function field(label, inner) {
    return '<div class="cf-field"><span>' + label + "</span>" + inner + "</div>";
  }
  function select(id, opts, cur) {
    return '<select class="input" id="' + id + '">' + opts.map(function (o) {
      var v = Array.isArray(o) ? o[0] : o, t = Array.isArray(o) ? o[1] : o;
      return '<option value="' + h(v) + '"' + (v === cur ? " selected" : "") + ">" + h(t) + "</option>";
    }).join("") + "</select>";
  }

  function wire() {
    var el = root();
    var bind = function (id, ev, fn) { var x = $(id); if (x) x.addEventListener(ev, fn); };
    bind("cf-name", "input", function (e) { S.form.name = e.target.value; });
    bind("cf-smiles", "input", function (e) { S.form.smiles = e.target.value; });
    bind("cf-pattern", "input", function (e) { S.form.pattern = e.target.value; });
    bind("cf-n", "input", function (e) { S.form.nConformers = e.target.value; });
    bind("cf-seed", "input", function (e) { S.form.seed = e.target.value; });
    bind("cf-prune", "input", function (e) { S.form.pruneRms = e.target.value; });
    bind("cf-structure", "change", function (e) { S.form.structure = e.target.value; });
    bind("cf-reference", "change", function (e) { S.form.reference = e.target.value; render(); });
    bind("cf-go", "click", search);
    bind("cf-lib", "click", openLib);
    bind("cf-link", "click", linkToLibrary);
    bind("cf-libclose", "click", function () { S.libOpen = false; render(); });
    bind("cf-libq", "input", function (e) {
      S.libQuery = e.target.value;
      var box = document.querySelector(".cf-liblist");
      if (box) { box.innerHTML = libRows(); wireLibRows(); }
    });
    wireLibRows();
    el.querySelectorAll("[data-set]").forEach(function (b) {
      b.addEventListener("click", function () {
        if (b.dataset.set) openSet(b.dataset.set);
        else { S.doc = null; S.play.pos = 0; render(); }
      });
    });
    el.querySelectorAll("[data-tab]").forEach(function (b) {
      b.addEventListener("click", function () { S.tab = b.dataset.tab; render(); });
    });
    el.querySelectorAll("[data-chk]").forEach(function (b) {
      b.addEventListener("click", function (ev) {
        ev.stopPropagation();
        var n = +b.dataset.chk;
        S.sel.has(n) ? S.sel.delete(n) : S.sel.add(n);
        render();
      });
    });
    el.querySelectorAll("[data-conf]").forEach(function (b) {
      b.addEventListener("click", function () { S.cur = +b.dataset.conf; S.overlay = false; render(); });
    });
    el.querySelectorAll("[data-act]").forEach(function (b) {
      b.addEventListener("click", function () {
        var a = b.dataset.act;
        if (a === "overlay") { S.overlay = !S.overlay; render(); }
        else if (a === "rank") rank();
        else if (a === "tocalc") toCalc();
        else if (a === "del") removeSet();
        else if (a === "play") { playToggle(); var p = $("cf-playbtn") || b; p.textContent = S.play.on ? "⏸ 멈춤" : "▶ 재생"; }
      });
    });
    el.querySelectorAll("[data-ord]").forEach(function (b) {
      b.addEventListener("click", function () {
        S.play.on = false; cancelAnimationFrame(S.play.raf);
        S.play.order = b.dataset.ord; S.play.pos = 0; S.play.t0 = 0;
        render();
      });
    });
  }

  function wireLibRows() {
    var el = root();
    if (!el) return;
    el.querySelectorAll("[data-mol]").forEach(function (b) {
      b.addEventListener("click", function () { pickMolecule(b.dataset.mol); });
    });
  }

  window.rbRenderConformers = function () {
    if (IS_SNAPSHOT) {
      var el = root();
      if (el) el.innerHTML = '<h1>Conformer 탐색</h1><div class="empty small">결과 사본에서는 구조 탐색을 할 수 없습니다 — 서버에서 열어 주세요.</div>';
      return;
    }
    if (!S.sets.length) loadSets().then(render);
    else render();
  };
  window.rbConformerOpen = function (id) { window.rbOpenMode("conf", "Conformer 탐색"); openSet(id); };
  // 라이브러리의 «계산에 쓰기» — 세트를 열고 기본 선택(기준 구조)으로 계산 화면에 넘긴다
  window.rbConformerUseInCalc = async function (id) {
    if (!S.sets.length) await loadSets();
    await openSet(id);
    toCalc();
  };
})();
