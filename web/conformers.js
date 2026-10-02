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
    form: {smiles: "", name: "", libraryId: null, structure: "모노머", reference: "all-trans",
           pattern: "T G T G'", nConformers: 20, seed: 42, pruneRms: 0.5},
  };
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
  function fromBasket() {
    var L = window.RBLIB;
    var id = L && L.sel && L.sel[0];
    var m = id && L.by && L.by[id];
    if (!m) { S.error = "«분자 검색 및 선택»에서 분자를 먼저 고르세요."; render(); return; }
    S.form.smiles = m.smiles; S.form.name = m.name; S.form.libraryId = m.id;
    S.error = ""; render();
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
    var sets = S.sets.map(function (s) {
      return '<option value="' + h(s.id) + '"' + (S.doc && S.doc.id === s.id ? " selected" : "") + ">" +
        h(s.id + " · " + ((s.molecule || {}).name || "") + " · " + s.n_conformers + "개") + "</option>";
    }).join("");
    var head = '<h1>Conformer 탐색</h1>' +
      '<p class="rb-note">구조를 먼저 찾아 눈으로 확인하고, 고른 구조로만 DFT 계산을 돌립니다. 탐색은 역장 계산이라 ' +
      '수 초면 끝나고 계산 큐를 쓰지 않습니다. 여러 분자를 비교할 때는 기준 구조(all-trans 등)를 맞춰 두면 ' +
      '사슬 모양 차이가 값 차이에 섞이지 않습니다.</p>' +
      '<div class="card"><div class="card-head"><h2>분자와 탐색 설정</h2>' +
      '<div class="toolbar"><label class="small">저장된 세트 <select class="input" id="cf-set">' +
      '<option value="">(새로 탐색)</option>' + sets + "</select></label></div></div>" +
      '<div class="cf-fields">' +
      field("분자 이름", '<input class="input" id="cf-name" value="' + h(f.name) + '" placeholder="예: PVDF 3량체">') +
      field("SMILES", '<input class="input" id="cf-smiles" value="' + h(f.smiles) + '" placeholder="예: C=C(F)F" style="min-width:220px">') +
      field("&nbsp;", '<button class="btn" id="cf-basket" type="button">선택함에서 가져오기</button>') +
      field("구조", select("cf-structure", ["모노머", "2량체", "3량체"], f.structure)) +
      field("기준 구조", select("cf-reference", [["auto", "자동 (최저 에너지)"], ["all-trans", "all-trans"], ["pattern", "비틀림 패턴"]], f.reference)) +
      (f.reference === "pattern" ? field("패턴", '<input class="input" id="cf-pattern" value="' + h(f.pattern) + '" placeholder="T G T G\'" style="width:130px">') : "") +
      field("개수", '<input class="input" id="cf-n" type="number" value="' + f.nConformers + '" style="width:80px">') +
      field("중복 제거 RMSD", '<input class="input" id="cf-prune" type="number" step="0.1" value="' + f.pruneRms + '" style="width:80px">') +
      field("seed", '<input class="input" id="cf-seed" type="number" value="' + f.seed + '" style="width:80px">') +
      field("&nbsp;", '<button class="btn primary" id="cf-go" type="button"' + (S.busy ? " disabled" : "") + ">" +
        (S.busy ? "탐색 중…" : "탐색") + "</button>") +
      "</div>" + (S.error ? '<div class="form-error">' + h(S.error) + "</div>" : "") + "</div>";

    if (!S.doc) {
      el.innerHTML = head + '<div class="card"><div class="empty small">분자를 넣고 «탐색»을 누르거나, 저장된 세트를 고르세요.</div></div>';
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
      '<div id="cf-view"></div><div class="cf-strip" id="cf-strip"></div></div>' +

      '<div class="cf-right"><div class="cf-tabs">' +
      [["prep", "준비"], ["conf", "Conformer"], ["dft", "계산"]].map(function (t) {
        return '<button data-tab="' + t[0] + '" class="' + (S.tab === t[0] ? "on" : "") + '">' + t[1] + "</button>";
      }).join("") + "</div><div class='cf-rbody'>" +
      (S.tab === "prep" ? panelPrep() : S.tab === "conf" ? panelConf() : panelDft()) + "</div></div></div>";
    wire();
    viewer();
    thumbs();
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
    bind("cf-basket", "click", fromBasket);
    bind("cf-set", "change", function (e) { if (e.target.value) openSet(e.target.value); else { S.doc = null; render(); } });
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
      });
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
})();
