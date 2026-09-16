/* ------------------------------------------------------------------
   프로그램 안 사용 설명서
     A. «사용 설명서» 페이지(#rbv-manual) — 차례·검색·Word 내려받기·바로 가기
     B. 화면 곳곳의 «?» 도움말 버튼 → 오른쪽 패널에 해당 절만 표시
     C. 처음 접속 안내 배너 («10분 빠른 시작»)
     + 배치 편집: ? 버튼의 위치·연결 절·표시 여부와 배너 설정을 사용자마다
       브라우저(localStorage)에 저장. 물질 보관함과 같은 «브라우저별 저장» 원칙.
   본문 원본은 web/manual_content.js (window.RB_MANUAL) 하나뿐이다.
   ------------------------------------------------------------------ */
(function () {
  "use strict";
  var M = window.RB_MANUAL;
  if (!M || !M.chapters) return;

  var LS_KEY = "rb-help-layout";
  var SS_BANNER = "rb-help-banner-hidden";
  var IS_SNAPSHOT = !!window.__RB_SNAPSHOT__;

  /* ---------- 기본 도움말 배치 ----------
     sel: #rb-real 안에서 찾을 CSS 선택자, text: 해당 요소의 글머리(선택),
     section: 연결할 절(id) 또는 장(chN), pos: after(이름 바로 옆) | end(줄 오른쪽 끝) */
  var DEFAULTS = [
    // DFT 계산
    { id: "calc-title", sel: "#rbv-calc > h1", section: "ch6", pos: "after" },
    { id: "calc-material", sel: "#rbv-calc .card-head h2", text: "1. 소재", section: "s6-1", pos: "after" },
    { id: "calc-3d", sel: "#rbv-calc span.small.muted", text: "또는 3D 구조 파일", section: "s6-1", pos: "after" },
    { id: "calc-env", sel: "#rbv-calc .card-head h2", text: "2. 환경", section: "s6-2", pos: "after" },
    { id: "calc-explicit", sel: "#rbv-calc .option-title", text: "명시적 주변 분자", section: "s6-2", pos: "after" },
    { id: "calc-settings", sel: "#rbv-calc .card-head h2", text: "3. 계산 설정", section: "s6-2", pos: "after" },
    { id: "calc-accuracy", sel: "#rbv-calc .field:has(#accuracy) .field-label", section: "s6-3", pos: "after" },
    { id: "calc-purpose", sel: "#rbv-calc .field:has(#purpose) .field-label", section: "s6-4", pos: "after" },
    { id: "calc-expert", sel: "#rbv-calc details.expert > summary", section: "s6-5", pos: "after" },
    { id: "calc-confsens", sel: "#rbv-calc .field:has(#conf-sens) .field-label", section: "s7-6", pos: "after" },
    { id: "calc-li", sel: "#rbv-calc .field:has(#li-model) .field-label", section: "s7-7", pos: "after" },
    { id: "calc-cmpfunc", sel: "#rbv-calc .field:has(#cmp-functionals) .field-label", section: "s8-2", pos: "after" },
    // DFT 계산 결과
    { id: "res-title", sel: "#rbv-results > h1", section: "ch7", pos: "after" },
    { id: "res-load", sel: "#rbv-results .card-head h2", text: "결과 불러오기", section: "ch11", pos: "after" },
    { id: "res-detail", sel: "#result-title", section: "s7-1", pos: "after" },
    { id: "res-queue", sel: "#rbv-results .card-head h2", text: "작업 큐", section: "s6-6", pos: "after" },
    { id: "res-validation", sel: "#rbv-results h3", text: "계산 검증", section: "s7-4", pos: "after" },
    { id: "res-esw", sel: "#rbv-results h3", text: "전기화학 안정 창", section: "s7-2", pos: "after" },
    { id: "res-conf", sel: "#rbv-results h3", text: "Conformer Boltzmann", section: "s7-6", pos: "after" },
    { id: "res-confsens", sel: "#rbv-results h3", text: "전위 conformer 민감도", section: "s7-6", pos: "after" },
    { id: "res-li", sel: "#rbv-results h3", text: "Li⁺ 상호작용", section: "s7-7", pos: "after" },
    { id: "res-radar", sel: "#rbv-results h3", text: "물성 지문", section: "s7-1", pos: "after" },
    { id: "res-props", sel: "#rbv-results h3", text: "물성 전체 목록", section: "s7-1", pos: "after" },
    { id: "res-bde", sel: "#rbv-results h3", text: "결합별 해리에너지", section: "s7-1", pos: "after" },
    { id: "res-caution", sel: "#rbv-results h3", text: "주의사항", section: "s7-5", pos: "after" },
    // 화학물질 조회 · 물질 비교
    { id: "lookup-title", sel: "#rbv-lookup > h1", section: "s5-1", pos: "after" },
    { id: "cmp-title", sel: "#rbv-compare > h1", section: "ch8", pos: "after" },
    { id: "cmp-display", sel: "#rbv-compare .card-head h2", text: "표시 설정", section: "ch8", pos: "after" },
    { id: "cmp-esw", sel: "#rbv-compare h3", text: "왜 «", section: "s8-1", pos: "after" },
    // 배치 스크리닝
    { id: "scr-title", sel: "#rbv-screen > h1", section: "ch9", pos: "after" },
    { id: "scr-list", sel: "#rbv-screen .card-head h2", text: "캠페인", section: "s9-7", pos: "after" },
    { id: "scr-new", sel: "#rbv-screen .card-head h2", text: "새 캠페인", section: "ch9", pos: "after" },
    { id: "scr-step1", sel: "#rbv-screen .wiz-panel[data-step='1'] > h3", section: "s9-1", pos: "after" },
    { id: "scr-step2", sel: "#rbv-screen .wiz-panel[data-step='2'] > h3", section: "s9-2", pos: "after" },
    { id: "scr-step3", sel: "#rbv-screen .wiz-panel[data-step='3'] > h3", section: "s9-3", pos: "after" },
    { id: "scr-step4", sel: "#rbv-screen .wiz-panel[data-step='4'] > h3", section: "s9-4", pos: "after" },
    { id: "scr-step5", sel: "#rbv-screen .wiz-panel[data-step='5'] > h3", section: "s9-5", pos: "after" },
    { id: "scr-detail", sel: "#scr-detail-title", section: "s9-7", pos: "after" },
    { id: "scr-heat", sel: "#rbv-screen h3", text: "판정 히트맵", section: "s9-8", pos: "after" },
    { id: "scr-pareto", sel: "#rbv-screen h3", text: "Pareto 뷰", section: "s9-7", pos: "after" },
    // 계산 모니터
    { id: "mon-title", sel: "#rbv-monitor > h1", section: "ch10", pos: "after" },
    { id: "mon-jobs", sel: "#rbv-monitor .card-head h2", text: "작업", section: "s10-1", pos: "after" },
    { id: "mon-detail", sel: "#mon-detail-title", section: "s10-2", pos: "after" },
    { id: "mon-raw", sel: "#rbv-monitor h3", text: "PySCF 원본 로그", section: "s10-2", pos: "after" },
    // 벤치마크
    { id: "bench-title", sel: "#rbv-bench > h1", section: "s7-9", pos: "after" },
  ];
  var MODE_CHAPTER = { calc: "ch6", results: "ch7", lookup: "ch5", compare: "ch8", screen: "ch9", monitor: "ch10", manual: "ch4", bench: "ch7" };
  var HOST_SEL = "h1, h2, h3, label, summary, legend, .field-label, .option-title";

  /* ---------- 설명서 색인 ---------- */
  var SEC = {};      // id → {id, chapter, title, blocks, kind}
  var ORDER = [];    // 표시 순서
  M.chapters.forEach(function (ch) {
    var intro = [], cur = null;
    ch.blocks.forEach(function (b) {
      if (b.t === "h2") {
        cur = { id: b.id, chapter: ch, title: b.title, blocks: [], kind: "section" };
        SEC[b.id] = cur; ORDER.push(cur);
      } else if (cur) cur.blocks.push(b);
      else intro.push(b);
    });
    var c = { id: ch.id, chapter: ch, title: chapterTitle(ch), blocks: intro, kind: "chapter" };
    SEC[ch.id] = c;
    ORDER.splice(ORDER.length - ch.blocks.filter(function (b) { return b.t === "h2"; }).length, 0, c);
  });
  function chapterTitle(ch) {
    return (/^[A-Z]$/.test(ch.num) ? "부록 " + ch.num + ". " : ch.num + ". ") + ch.title;
  }

  /* ---------- 저장(사용자별) ---------- */
  var layout = loadLayout();
  function defaultLayout() { return { v: 1, anchors: {}, custom: [], banner: { on: true, pos: "top", dismissed: false } }; }
  function loadLayout() {
    var base = defaultLayout();
    try {
      var raw = JSON.parse(localStorage.getItem(LS_KEY) || "null");
      if (raw && typeof raw === "object") {
        if (raw.anchors && typeof raw.anchors === "object") base.anchors = raw.anchors;
        if (Array.isArray(raw.custom)) base.custom = raw.custom.filter(function (c) { return c && c.id && c.sel && c.section; });
        if (raw.banner && typeof raw.banner === "object") Object.assign(base.banner, raw.banner);
      }
    } catch (e) {}
    return base;
  }
  function saveLayout() {
    try { localStorage.setItem(LS_KEY, JSON.stringify(layout)); } catch (e) {}
  }
  function anchors() {
    var out = [];
    DEFAULTS.forEach(function (d) {
      var o = layout.anchors[d.id] || {};
      out.push({ id: d.id, sel: d.sel, text: d.text, section: o.section || d.section, pos: o.pos || d.pos,
        on: o.on !== false, builtin: true });
    });
    layout.custom.forEach(function (c) {
      out.push({ id: c.id, sel: c.sel, text: c.text, section: c.section, pos: c.pos || "after", on: c.on !== false, builtin: false });
    });
    return out;
  }
  function anchorById(id) { return anchors().filter(function (a) { return a.id === id; })[0]; }

  /* ---------- 공통 ---------- */
  function h(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function ownText(el) {
    var t = "";
    for (var i = 0; i < el.childNodes.length; i++) {
      var n = el.childNodes[i];
      if (n.nodeType === 3) t += n.textContent;
      else if (n.nodeType === 1 && !n.classList.contains("rb-help-btn") && /^(B|I|SPAN|CODE)$/.test(n.tagName) && !n.classList.contains("muted")) t += n.textContent;
    }
    return t.replace(/\s+/g, " ").trim();
  }
  function inline(text, q) {
    var s = h(text).replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
    if (!q) return s;
    var re = new RegExp("(" + q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig");
    return s.split(/(<[^>]+>)/).map(function (part) { return part.charAt(0) === "<" ? part : part.replace(re, "<mark>$1</mark>"); }).join("");
  }
  function renderBlock(b, q) {
    switch (b.t) {
      case "p": return "<p>" + inline(b.text, q) + "</p>";
      case "h2": return "<h2 class=\"rb-man-h2\" id=\"man-" + h(b.id) + "\">" + inline(b.title, q) + "</h2>";
      case "h3": return "<h3 class=\"rb-man-h3\">" + inline(b.title, q) + "</h3>";
      case "ul": return "<ul>" + b.items.map(function (t) { return "<li>" + inline(t, q) + "</li>"; }).join("") + "</ul>";
      case "ol": return "<ol class=\"rb-man-steps\">" + b.items.map(function (t) { return "<li>" + inline(t, q) + "</li>"; }).join("") + "</ol>";
      case "tip": return "<div class=\"rb-man-box tip\"><b>TIP</b> " + inline(b.text, q) + "</div>";
      case "warn": return "<div class=\"rb-man-box warn\"><b>주의</b> " + inline(b.text, q) + "</div>";
      case "code": return "<pre class=\"rb-man-code\">" + b.lines.map(function (l) { return h(l); }).join("\n") + "</pre>";
      case "table": {
        var total = b.widths.reduce(function (a, x) { return a + x; }, 0);
        var cg = "<colgroup>" + b.widths.map(function (w) { return "<col style=\"width:" + Math.round(w / total * 100) + "%\">"; }).join("") + "</colgroup>";
        var head = b.headers.some(Boolean) ? "<thead><tr>" + b.headers.map(function (x) { return "<th>" + inline(x, q) + "</th>"; }).join("") + "</tr></thead>" : "";
        var rows = b.rows.map(function (r) { return "<tr>" + r.map(function (c, i) { return "<td" + (i === 0 && !b.plain ? " class=\"first\"" : "") + ">" + inline(c, q) + "</td>"; }).join("") + "</tr>"; }).join("");
        return "<div class=\"scroll-x\"><table class=\"rb-man-tbl\">" + cg + head + "<tbody>" + rows + "</tbody></table></div>";
      }
      case "qa": return "<div class=\"rb-man-qa\"><div class=\"q\">Q. " + inline(b.q, q) + "</div><div class=\"a\">" + inline(b.a, q) + "</div></div>";
      default: return "";
    }
  }
  function blockText(b) {
    switch (b.t) {
      case "p": case "tip": case "warn": return b.text;
      case "h2": case "h3": return b.title;
      case "ul": case "ol": return b.items.join(" ");
      case "code": return b.lines.join(" ");
      case "table": return b.headers.join(" ") + " " + b.rows.map(function (r) { return r.join(" "); }).join(" ");
      case "qa": return b.q + " " + b.a;
      default: return "";
    }
  }
  function matches(sec, q) {
    if (!q) return true;
    var lq = q.toLowerCase();
    if (sec.title.toLowerCase().indexOf(lq) >= 0) return true;
    return sec.blocks.some(function (b) { return blockText(b).toLowerCase().indexOf(lq) >= 0; });
  }

  /* ---------- A. 사용 설명서 페이지 ---------- */
  var manualBuilt = false, manualQuery = "";
  function buildManualPage() {
    var root = document.getElementById("rbv-manual");
    if (!root || manualBuilt) return;
    manualBuilt = true;
    root.innerHTML =
      "<h1>사용 설명서 <span class=\"muted small\" style=\"font-weight:400\">v" + h(M.version) + " · " + h(M.date) + "</span></h1>" +
      "<p class=\"rb-note\">" + h(M.subtitle) + ". 왼쪽 차례를 누르거나 검색하세요. 각 화면의 <span class=\"rb-help-btn demo\">?</span> 버튼은 해당 절만 오른쪽에 보여 줍니다. " +
      "버튼 위치와 처음 안내 배너는 <b>배치 편집</b>으로 사용자마다 다르게 둘 수 있습니다(브라우저에 저장).</p>" +
      "<div class=\"toolbar\">" +
      (IS_SNAPSHOT ? "" : "<a class=\"btn\" href=\"/api/manual/docx\" download>⬇ Word 파일 내려받기</a>") +
      "<button class=\"btn\" type=\"button\" id=\"man-edit-btn\">✎ 배치 편집</button>" +
      "<button class=\"btn ghost\" type=\"button\" id=\"man-banner-btn\">처음 안내 배너 다시 보기</button>" +
      "<span class=\"small muted\" style=\"margin-left:auto\">차례 " + M.chapters.length + "장 · " + ORDER.filter(function (s) { return s.kind === "section"; }).length + "절</span>" +
      "</div>" +
      "<div class=\"rb-man-wrap\">" +
      "<aside class=\"rb-man-toc\"><input class=\"input\" id=\"man-search\" placeholder=\"검색 (예: 정확도, REVIEW, 비밀번호)\">" +
      "<div class=\"small muted\" id=\"man-count\"></div><nav id=\"man-nav\"></nav></aside>" +
      "<div class=\"rb-man-body\" id=\"man-body\"></div></div>";
    document.getElementById("man-edit-btn").addEventListener("click", function () { setEditing(true); });
    document.getElementById("man-banner-btn").addEventListener("click", function () {
      layout.banner.dismissed = false; layout.banner.on = true; saveLayout();
      try { sessionStorage.removeItem(SS_BANNER); } catch (e) {}
      renderBanner();
      var real = document.getElementById("rb-real"); if (real) real.scrollTop = 0;
    });
    var timer = null;
    document.getElementById("man-search").addEventListener("input", function (e) {
      clearTimeout(timer);
      var v = e.target.value.trim();
      timer = setTimeout(function () { manualQuery = v; renderManual(); }, 150);
    });
    renderManual();
  }
  function renderManual() {
    var nav = document.getElementById("man-nav"), body = document.getElementById("man-body"), cnt = document.getElementById("man-count");
    if (!nav || !body) return;
    var q = manualQuery, shownSec = 0, navHtml = "", bodyHtml = "";
    M.chapters.forEach(function (ch) {
      var intro = SEC[ch.id], secs = ORDER.filter(function (s) { return s.kind === "section" && s.chapter === ch; });
      var introOk = matches(intro, q), okSecs = secs.filter(function (s) { return matches(s, q); });
      if (!introOk && !okSecs.length) return;
      shownSec += okSecs.length;
      navHtml += "<div class=\"rb-man-nav-ch\"><a href=\"#\" data-goto=\"" + h(ch.id) + "\">" + inline(chapterTitle(ch), q) + "</a>" +
        (okSecs.length ? "<div class=\"rb-man-nav-secs\">" + okSecs.map(function (s) { return "<a href=\"#\" data-goto=\"" + h(s.id) + "\">" + inline(s.title, q) + "</a>"; }).join("") + "</div>" : "") + "</div>";
      bodyHtml += "<section class=\"rb-man-ch\" id=\"man-" + h(ch.id) + "\"><div class=\"rb-man-ch-head\"><h2>" + inline(chapterTitle(ch), q) + "</h2>" +
        (ch.goto && !IS_SNAPSHOT ? "<button class=\"btn ghost\" type=\"button\" data-mode=\"" + h(ch.goto.mode) + "\" data-label=\"" + h(ch.goto.label) + "\">→ 바로 가기: " + h(ch.goto.label) + "</button>" : "") + "</div>";
      if (introOk || !q) bodyHtml += intro.blocks.map(function (b) { return renderBlock(b, q); }).join("");
      (q ? okSecs : secs).forEach(function (s) {
        bodyHtml += "<div class=\"rb-man-sec\" id=\"man-" + h(s.id) + "\"><div class=\"rb-man-sec-head\"><h3 class=\"rb-man-h2\">" + inline(s.title, q) + "</h3>" +
          "<button class=\"rb-help-btn\" type=\"button\" data-sec=\"" + h(s.id) + "\" title=\"패널로 보기\">?</button></div>" +
          s.blocks.map(function (b) { return renderBlock(b, q); }).join("") + "</div>";
      });
      bodyHtml += "</section>";
    });
    nav.innerHTML = navHtml || "<div class=\"small muted\">일치하는 내용이 없습니다.</div>";
    body.innerHTML = bodyHtml || "<div class=\"empty\">«" + h(q) + "»에 해당하는 내용이 없습니다.</div>";
    if (cnt) cnt.textContent = q ? "«" + q + "» 일치 " + shownSec + "절" : "";
    nav.querySelectorAll("a[data-goto]").forEach(function (a) {
      a.addEventListener("click", function (e) { e.preventDefault(); scrollToManual(a.dataset.goto); });
    });
    body.querySelectorAll("button[data-mode]").forEach(function (b) {
      b.addEventListener("click", function () { if (window.rbOpenMode) window.rbOpenMode(b.dataset.mode, b.dataset.label); });
    });
    body.querySelectorAll(".rb-help-btn[data-sec]").forEach(function (b) {
      b.addEventListener("click", function (e) { e.preventDefault(); openDrawer(b.dataset.sec); });
    });
  }
  function scrollToManual(id) {
    var el = document.getElementById("man-" + id);
    if (!el) return;
    el.scrollIntoView({ block: "start", behavior: "smooth" });
    el.classList.add("flash");
    setTimeout(function () { el.classList.remove("flash"); }, 1600);
  }
  window.rbRenderManual = function () { buildManualPage(); };
  window.rbOpenManual = function (id) {
    if (window.rbOpenMode) window.rbOpenMode("manual", "사용 설명서");
    buildManualPage();
    if (id) setTimeout(function () { scrollToManual(id); }, 50);
  };

  /* ---------- B. 도움말 패널 ---------- */
  var drawer = null;
  function ensureDrawer() {
    if (drawer) return drawer;
    drawer = document.createElement("aside");
    drawer.id = "rb-help-drawer";
    drawer.innerHTML = "<div class=\"rb-hd-head\"><div class=\"rb-hd-crumb\" id=\"rb-hd-crumb\"></div>" +
      "<button class=\"btn ghost\" type=\"button\" id=\"rb-hd-close\" title=\"닫기 (Esc)\">✕</button></div>" +
      "<div class=\"rb-hd-body\" id=\"rb-hd-body\"></div>" +
      "<div class=\"rb-hd-foot\"><button class=\"btn ghost\" type=\"button\" id=\"rb-hd-prev\">‹ 이전 절</button>" +
      "<button class=\"btn\" type=\"button\" id=\"rb-hd-open\">설명서에서 열기</button>" +
      "<button class=\"btn ghost\" type=\"button\" id=\"rb-hd-next\">다음 절 ›</button></div>";
    document.body.appendChild(drawer);
    document.getElementById("rb-hd-close").addEventListener("click", closeDrawer);
    document.getElementById("rb-hd-open").addEventListener("click", function () { var id = drawer.dataset.sec; closeDrawer(); window.rbOpenManual(id); });
    document.getElementById("rb-hd-prev").addEventListener("click", function () { step(-1); });
    document.getElementById("rb-hd-next").addEventListener("click", function () { step(1); });
    return drawer;
  }
  function step(d) {
    var i = ORDER.indexOf(SEC[drawer.dataset.sec]);
    var n = ORDER[i + d];
    if (n) openDrawer(n.id);
  }
  function openDrawer(id) {
    var sec = SEC[id];
    if (!sec) return;
    ensureDrawer();
    drawer.dataset.sec = id;
    document.getElementById("rb-hd-crumb").innerHTML = "<div class=\"small muted\">" + h(chapterTitle(sec.chapter)) + "</div><div class=\"rb-hd-title\">" + inline(sec.title) + "</div>";
    var html = sec.blocks.map(function (b) { return renderBlock(b); }).join("");
    if (sec.kind === "chapter") {
      var subs = ORDER.filter(function (s) { return s.kind === "section" && s.chapter === sec.chapter; });
      if (subs.length) html += "<div class=\"rb-hd-subs\"><div class=\"small muted\">이 장의 절</div>" + subs.map(function (s) { return "<a href=\"#\" data-sec=\"" + h(s.id) + "\">" + inline(s.title) + "</a>"; }).join("") + "</div>";
    }
    if (!html) html = "<p class=\"muted\">본문이 없는 절입니다.</p>";
    var body = document.getElementById("rb-hd-body");
    body.innerHTML = html;
    body.scrollTop = 0;
    body.querySelectorAll("a[data-sec]").forEach(function (a) { a.addEventListener("click", function (e) { e.preventDefault(); openDrawer(a.dataset.sec); }); });
    var i = ORDER.indexOf(sec);
    document.getElementById("rb-hd-prev").disabled = i <= 0;
    document.getElementById("rb-hd-next").disabled = i >= ORDER.length - 1;
    drawer.classList.add("open");
  }
  function closeDrawer() { if (drawer) drawer.classList.remove("open"); }
  window.rbHelp = openDrawer;

  /* ---------- B. ? 버튼 배치 ---------- */
  function findHosts(a) {
    var real = document.getElementById("rb-real");
    if (!real) return [];
    var list;
    try { list = Array.prototype.slice.call(real.querySelectorAll(a.sel)); } catch (e) { return []; }
    if (a.text) {
      // 글머리가 정확히 같은 요소가 있으면 그것만, 없으면 그 글로 시작하는 요소
      var t = a.text.replace(/\s+/g, " ").trim().toLowerCase();
      var exact = list.filter(function (el) { return ownText(el).toLowerCase() === t; });
      list = exact.length ? exact : list.filter(function (el) { return ownText(el).toLowerCase().indexOf(t) === 0; });
    }
    return list.filter(function (el) { return !el.closest("#rbv-manual"); });
  }
  function placeButton(host, a) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "rb-help-btn";
    btn.dataset.help = a.id;
    btn.dataset.sec = a.section;
    btn.textContent = "?";
    btn.title = (SEC[a.section] ? SEC[a.section].title : a.section) + " — 도움말";
    if (a.pos === "end") {
      var parent = host.parentElement;
      var flex = parent && /flex/.test(getComputedStyle(parent).display);
      if (flex) { btn.classList.add("end-flex"); host.insertAdjacentElement("afterend", btn); }
      else { btn.classList.add("end-float"); host.appendChild(btn); }
    } else host.appendChild(btn);
    btn.dataset.pos = a.pos;
    host.dataset.rbHelp = a.id;
  }
  var applyTimer = null;
  function applyHelp() {
    var real = document.getElementById("rb-real");
    if (!real) return;
    var wanted = anchors().filter(function (a) { return a.on; });
    var wantedIds = {};
    wanted.forEach(function (a) { wantedIds[a.id] = a; });
    // 더 이상 필요 없는 버튼 제거(꺼졌거나 삭제됨, 설정이 바뀜)
    real.querySelectorAll(".rb-help-btn[data-help]").forEach(function (b) {
      var a = wantedIds[b.dataset.help];
      var host = b.closest("[data-rb-help='" + b.dataset.help + "']") || b.previousElementSibling;
      if (!a || b.dataset.sec !== a.section || b.dataset.pos !== a.pos) {
        if (host && host.dataset) delete host.dataset.rbHelp;
        b.remove();
      }
    });
    wanted.forEach(function (a) {
      findHosts(a).forEach(function (host) {
        if (host.dataset.rbHelp) return;
        placeButton(host, a);
      });
    });
  }
  function scheduleApply() {
    clearTimeout(applyTimer);
    applyTimer = setTimeout(applyHelp, 60);
  }
  function resetButtons() {
    var real = document.getElementById("rb-real");
    if (!real) return;
    real.querySelectorAll("[data-rb-help]").forEach(function (el) { delete el.dataset.rbHelp; });
    real.querySelectorAll(".rb-help-btn[data-help]").forEach(function (b) { b.remove(); });
    applyHelp();
  }

  /* ---------- C. 처음 안내 배너 ---------- */
  var banner = null;
  function renderBanner() {
    var real = document.getElementById("rb-real");
    if (!real) return;
    if (banner) { banner.remove(); banner = null; }
    var hiddenNow = false;
    try { hiddenNow = !!sessionStorage.getItem(SS_BANNER); } catch (e) {}
    if (!layout.banner.on || layout.banner.dismissed || hiddenNow || IS_SNAPSHOT) return;
    banner = document.createElement("div");
    banner.id = "rb-help-banner";
    banner.className = layout.banner.pos === "bottom" ? "bottom" : "top";
    banner.innerHTML = "<span class=\"rb-hb-icon\">👋</span><div class=\"rb-hb-text\"><b>처음이세요?</b> 분자 하나를 넣고 결과까지 보는 데 10분이면 됩니다. " +
      "화면의 <span class=\"rb-help-btn demo\">?</span> 버튼을 누르면 그 항목의 설명이 오른쪽에 나옵니다.</div>" +
      "<div class=\"rb-hb-actions\"><button class=\"btn primary\" type=\"button\" data-act=\"quick\">10분 빠른 시작 열기</button>" +
      "<button class=\"btn\" type=\"button\" data-act=\"manual\">사용 설명서</button>" +
      "<button class=\"btn ghost\" type=\"button\" data-act=\"never\">다시 보지 않기</button>" +
      "<button class=\"btn ghost\" type=\"button\" data-act=\"close\" title=\"이번만 닫기\">✕</button></div>";
    banner.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-act]");
      if (!b) return;
      var act = b.dataset.act;
      if (act === "quick") window.rbOpenManual("ch3");
      else if (act === "manual") window.rbOpenManual();
      else if (act === "never") { layout.banner.dismissed = true; saveLayout(); banner.remove(); banner = null; }
      else if (act === "close") { try { sessionStorage.setItem(SS_BANNER, "1"); } catch (err) {} banner.remove(); banner = null; }
    });
    if (banner.className === "bottom") document.body.appendChild(banner);
    else real.insertBefore(banner, real.firstChild);
  }

  /* ---------- 배치 편집 ---------- */
  var editing = false, editbar = null, popover = null;
  function setEditing(on) {
    editing = on;
    document.body.classList.toggle("rb-help-editing", on);
    closePopover();
    if (on) {
      ensureEditbar();
      editbar.classList.add("open");
      refreshEditbar();
      var real = document.getElementById("rb-real");
      if (real && real.classList.contains("mode-manual") && window.rbOpenMode) window.rbOpenMode("calc", "DFT 계산");
    } else if (editbar) editbar.classList.remove("open");
  }
  window.rbHelpEdit = setEditing;
  function ensureEditbar() {
    if (editbar) return editbar;
    editbar = document.createElement("div");
    editbar.id = "rb-help-editbar";
    editbar.innerHTML = "<div class=\"rb-eb-msg\"><b>배치 편집 중</b> — 화면의 제목이나 항목 이름을 누르면 <span class=\"rb-help-btn demo\">?</span>를 붙이고, 이미 있는 <span class=\"rb-help-btn demo\">?</span>를 누르면 연결 절·위치를 바꾸거나 숨깁니다. 다른 메뉴로 이동해도 편집이 이어집니다.</div>" +
      "<div class=\"rb-eb-actions\">" +
      "<span class=\"small muted\" id=\"rb-eb-stat\"></span>" +
      "<button class=\"btn\" type=\"button\" data-act=\"banner\">배너 설정</button>" +
      "<button class=\"btn\" type=\"button\" data-act=\"unhide\" id=\"rb-eb-unhide\">숨긴 항목 되살리기</button>" +
      "<button class=\"btn\" type=\"button\" data-act=\"export\">내보내기</button>" +
      "<button class=\"btn\" type=\"button\" data-act=\"import\">가져오기</button>" +
      "<button class=\"btn\" type=\"button\" data-act=\"reset\">기본값 복원</button>" +
      "<button class=\"btn primary\" type=\"button\" data-act=\"done\">완료</button></div>" +
      "<div class=\"rb-eb-panel\" id=\"rb-eb-banner\" hidden>" +
      "<label><input type=\"checkbox\" id=\"rb-eb-banner-on\"> 처음 안내 배너 표시</label>" +
      "<label>위치 <select class=\"input\" id=\"rb-eb-banner-pos\"><option value=\"top\">화면 위</option><option value=\"bottom\">화면 아래(고정)</option></select></label>" +
      "<button class=\"btn ghost\" type=\"button\" id=\"rb-eb-banner-show\">지금 다시 표시</button>" +
      "<span class=\"small muted\">«다시 보지 않기»를 눌렀던 상태도 «지금 다시 표시»로 되돌립니다.</span></div>" +
      "<input type=\"file\" id=\"rb-eb-file\" accept=\"application/json,.json\" hidden>";
    document.body.appendChild(editbar);
    editbar.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-act]");
      if (!b) return;
      var act = b.dataset.act;
      if (act === "done") setEditing(false);
      else if (act === "banner") { var p = document.getElementById("rb-eb-banner"); p.hidden = !p.hidden; }
      else if (act === "unhide") {
        Object.keys(layout.anchors).forEach(function (k) { if (layout.anchors[k] && layout.anchors[k].on === false) delete layout.anchors[k].on; });
        layout.custom.forEach(function (c) { delete c.on; });
        saveLayout(); resetButtons(); refreshEditbar();
      }
      else if (act === "export") exportLayout();
      else if (act === "import") document.getElementById("rb-eb-file").click();
      else if (act === "reset") {
        if (!confirm("도움말 배치와 배너 설정을 프로그램 기본값으로 되돌립니다. 계속할까요?")) return;
        layout = defaultLayout(); saveLayout(); resetButtons(); renderBanner(); refreshEditbar();
      }
    });
    document.getElementById("rb-eb-banner-on").addEventListener("change", function (e) { layout.banner.on = e.target.checked; saveLayout(); renderBanner(); });
    document.getElementById("rb-eb-banner-pos").addEventListener("change", function (e) { layout.banner.pos = e.target.value; saveLayout(); renderBanner(); });
    document.getElementById("rb-eb-banner-show").addEventListener("click", function () {
      layout.banner.on = true; layout.banner.dismissed = false; saveLayout();
      try { sessionStorage.removeItem(SS_BANNER); } catch (e) {}
      renderBanner(); refreshEditbar();
    });
    document.getElementById("rb-eb-file").addEventListener("change", function (e) {
      var f = e.target.files && e.target.files[0];
      if (!f) return;
      var r = new FileReader();
      r.onload = function () {
        try {
          var raw = JSON.parse(r.result);
          if (!raw || typeof raw !== "object" || (!raw.anchors && !raw.custom && !raw.banner)) throw new Error("형식");
          localStorage.setItem(LS_KEY, JSON.stringify(raw));
          layout = loadLayout(); saveLayout(); resetButtons(); renderBanner(); refreshEditbar();
          alert("도움말 배치를 가져왔습니다.");
        } catch (err) { alert("가져오기 실패: 도움말 배치 파일(JSON)이 아닙니다."); }
        e.target.value = "";
      };
      r.readAsText(f);
    });
    return editbar;
  }
  function refreshEditbar() {
    if (!editbar) return;
    var all = anchors(), hidden = all.filter(function (a) { return !a.on; }).length;
    var stat = document.getElementById("rb-eb-stat");
    stat.textContent = "도움말 " + all.length + "개 (기본 " + DEFAULTS.length + " · 추가 " + layout.custom.length + ")" + (hidden ? " · 숨김 " + hidden : "");
    var un = document.getElementById("rb-eb-unhide");
    un.hidden = !hidden;
    document.getElementById("rb-eb-banner-on").checked = !!layout.banner.on;
    document.getElementById("rb-eb-banner-pos").value = layout.banner.pos === "bottom" ? "bottom" : "top";
  }
  function exportLayout() {
    var blob = new Blob([JSON.stringify(layout, null, 2)], { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "rhobench-help-layout.json";
    document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  }
  function selectorFor(el) {
    var real = document.getElementById("rb-real");
    if (el.id) return { sel: "#" + CSS.escape(el.id) };
    var inner = el.querySelector("[id]");
    if (inner && (el.tagName === "LABEL" || el.classList.contains("field"))) return { sel: el.tagName.toLowerCase() + ":has(#" + CSS.escape(inner.id) + ")" };
    var text = ownText(el).slice(0, 40);
    var anc = el.parentElement;
    while (anc && anc !== real && !anc.id) anc = anc.parentElement;
    var scope = anc && anc.id ? "#" + CSS.escape(anc.id) + " " : "#rb-real ";
    if (text) {
      var cls = "";
      if (el.classList.contains("field-label")) cls = ".field-label";
      else if (el.classList.contains("option-title")) cls = ".option-title";
      return { sel: scope + el.tagName.toLowerCase() + cls, text: text };
    }
    var parts = [], node = el;
    while (node && node !== real && !node.id) {
      var s = node.tagName.toLowerCase(), p = node.parentElement;
      if (!p) break;
      var sib = Array.prototype.filter.call(p.children, function (c) { return c.tagName === node.tagName; });
      if (sib.length > 1) s += ":nth-of-type(" + (sib.indexOf(node) + 1) + ")";
      parts.unshift(s); node = p;
    }
    return { sel: (node && node.id ? "#" + CSS.escape(node.id) + " > " : "#rb-real > ") + parts.join(" > ") };
  }
  function sectionOptions(selected) {
    return M.chapters.map(function (ch) {
      var secs = ORDER.filter(function (s) { return s.kind === "section" && s.chapter === ch; });
      return "<optgroup label=\"" + h(chapterTitle(ch)) + "\"><option value=\"" + h(ch.id) + "\"" + (selected === ch.id ? " selected" : "") + ">" + h(chapterTitle(ch)) + " (장 전체)</option>" +
        secs.map(function (s) { return "<option value=\"" + h(s.id) + "\"" + (selected === s.id ? " selected" : "") + ">" + h(s.title) + "</option>"; }).join("") + "</optgroup>";
    }).join("");
  }
  function currentMode() {
    var real = document.getElementById("rb-real");
    if (!real) return null;
    var m = /mode-([a-z]+)/.exec(real.className);
    return m ? m[1] : null;
  }
  function openPopover(near, opts) {
    closePopover();
    popover = document.createElement("div");
    popover.id = "rb-help-popover";
    var a = opts.anchor;
    popover.innerHTML = "<div class=\"rb-pp-title\">" + (a ? "도움말 버튼 편집" : "여기에 ? 도움말 붙이기") + "</div>" +
      "<div class=\"small muted rb-pp-host\">" + h(opts.hostLabel || "") + "</div>" +
      "<label>연결할 절 <select class=\"input\" id=\"rb-pp-sec\">" + sectionOptions(a ? a.section : opts.guess) + "</select></label>" +
      "<label>위치 <select class=\"input\" id=\"rb-pp-pos\"><option value=\"after\"" + (!a || a.pos !== "end" ? " selected" : "") + ">이름 바로 옆</option><option value=\"end\"" + (a && a.pos === "end" ? " selected" : "") + ">줄 오른쪽 끝</option></select></label>" +
      "<div class=\"rb-pp-actions\"><button class=\"btn primary\" type=\"button\" data-act=\"save\">저장</button>" +
      (a ? "<button class=\"btn\" type=\"button\" data-act=\"hide\">" + (a.builtin ? "숨기기" : "삭제") + "</button>" : "") +
      "<button class=\"btn ghost\" type=\"button\" data-act=\"preview\">미리 보기</button>" +
      "<button class=\"btn ghost\" type=\"button\" data-act=\"cancel\">취소</button></div>";
    document.body.appendChild(popover);
    var r = near.getBoundingClientRect();
    var left = Math.min(Math.max(8, r.left), window.innerWidth - 340), top = r.bottom + 6;
    if (top + 230 > window.innerHeight) top = Math.max(8, r.top - 236);
    popover.style.left = left + "px"; popover.style.top = top + "px";
    popover.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-act]");
      if (!b) return;
      var act = b.dataset.act, sec = document.getElementById("rb-pp-sec").value, pos = document.getElementById("rb-pp-pos").value;
      if (act === "preview") { openDrawer(sec); return; }
      if (act === "save") opts.onSave(sec, pos);
      else if (act === "hide") opts.onHide();
      closePopover();
      saveLayout(); resetButtons(); refreshEditbar();
    });
  }
  function closePopover() { if (popover) { popover.remove(); popover = null; } }
  function editAnchor(btn) {
    var a = anchorById(btn.dataset.help);
    if (!a) return;
    var host = btn.closest("[data-rb-help]") || btn.previousElementSibling;
    openPopover(btn, {
      anchor: a, hostLabel: host ? "위치: " + ownText(host).slice(0, 50) : "",
      onSave: function (sec, pos) {
        if (a.builtin) { layout.anchors[a.id] = Object.assign(layout.anchors[a.id] || {}, { section: sec, pos: pos }); }
        else { var c = layout.custom.filter(function (x) { return x.id === a.id; })[0]; if (c) { c.section = sec; c.pos = pos; } }
      },
      onHide: function () {
        if (a.builtin) layout.anchors[a.id] = Object.assign(layout.anchors[a.id] || {}, { on: false });
        else layout.custom = layout.custom.filter(function (x) { return x.id !== a.id; });
      },
    });
  }
  function addAnchorAt(host) {
    var spec = selectorFor(host);
    var mode = currentMode();
    openPopover(host, {
      hostLabel: "위치: " + (ownText(host).slice(0, 50) || spec.sel), guess: MODE_CHAPTER[mode] || "ch4",
      onSave: function (sec, pos) {
        layout.custom.push({ id: "c" + Date.now().toString(36), sel: spec.sel, text: spec.text, section: sec, pos: pos, label: ownText(host).slice(0, 40) });
      },
    });
  }

  /* ---------- 이벤트 ---------- */
  document.addEventListener("click", function (e) {
    var t = e.target;
    if (!(t instanceof Element)) return;
    if (popover && popover.contains(t)) return;
    var btn = t.closest(".rb-help-btn[data-help]");
    if (btn) {
      e.preventDefault(); e.stopPropagation();
      if (editing) editAnchor(btn); else openDrawer(btn.dataset.sec);
      return;
    }
    if (editing) {
      if (editbar && editbar.contains(t)) return;
      if (drawer && drawer.contains(t)) { return; }
      closePopover();
      var real = document.getElementById("rb-real");
      var host = t.closest(HOST_SEL);
      if (host && real && real.contains(host) && !host.closest("#rbv-manual")) {
        e.preventDefault(); e.stopPropagation();
        if (host.dataset.rbHelp) { var b2 = host.querySelector(".rb-help-btn") || host.nextElementSibling; if (b2 && b2.dataset.help) { editAnchor(b2); return; } }
        addAnchorAt(host);
      }
    }
  }, true);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { closePopover(); if (drawer && drawer.classList.contains("open")) closeDrawer(); }
  });

  /* ---------- 스타일 ---------- */
  var css = "\
.rb-help-btn{display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:50%;border:1px solid color-mix(in srgb,var(--accent) 45%,transparent);background:color-mix(in srgb,var(--accent) 10%,transparent);color:var(--accent);font-size:11px;font-weight:700;line-height:1;cursor:pointer;margin-left:6px;vertical-align:middle;padding:0;font-family:inherit}\
.rb-help-btn:hover{background:var(--accent);color:#fff}\
.rb-help-btn.demo{cursor:default;pointer-events:none;margin:0 2px}\
.rb-help-btn.end-flex{margin-left:auto}.rb-help-btn.end-float{float:right;margin-top:2px}\
#rb-help-drawer{position:fixed;top:0;right:0;bottom:0;width:min(440px,92vw);background:var(--surface);border-left:1px solid var(--border);box-shadow:-8px 0 24px rgba(0,0,0,.08);z-index:910;display:flex;flex-direction:column;transform:translateX(105%);transition:transform .18s ease}\
#rb-help-drawer.open{transform:none}\
.rb-hd-head{display:flex;justify-content:space-between;align-items:flex-start;gap:8px;padding:14px 16px 10px;border-bottom:1px solid var(--grid)}\
.rb-hd-title{font-weight:700;font-size:15px}\
.rb-hd-body{flex:1;overflow-y:auto;padding:12px 18px;font-size:13.5px;line-height:1.6}\
.rb-hd-foot{display:flex;justify-content:space-between;align-items:center;gap:6px;padding:10px 12px;border-top:1px solid var(--grid)}\
.rb-hd-subs{margin-top:12px;display:flex;flex-direction:column;gap:4px}.rb-hd-subs a{color:var(--accent);text-decoration:none;font-size:13px}.rb-hd-subs a:hover{text-decoration:underline}\
.rb-hd-body p,.rb-man-body p{margin:0 0 10px}\
.rb-man-h2{font-size:15px;margin:0}.rb-man-h3{font-size:13.5px;margin:14px 0 6px;color:var(--text-2)}\
.rb-hd-body .rb-man-h3{margin-top:10px}\
.rb-man-box{border-left:4px solid var(--accent);background:color-mix(in srgb,var(--accent) 7%,transparent);border-radius:6px;padding:8px 12px;margin:8px 0 12px;font-size:13px}\
.rb-man-box b{margin-right:6px;color:var(--accent)}.rb-man-box.warn{border-color:var(--pin);background:color-mix(in srgb,var(--pin) 8%,transparent)}.rb-man-box.warn b{color:var(--pin)}\
.rb-man-code{background:var(--grid);border-radius:8px;padding:10px 12px;font-family:ui-monospace,Cascadia Code,Consolas,monospace;font-size:12px;line-height:1.5;overflow-x:auto;margin:6px 0 12px}\
.rb-man-tbl{width:100%;border-collapse:collapse;font-size:12.5px;margin:6px 0 14px;table-layout:fixed}\
.rb-man-tbl th,.rb-man-tbl td{border:1px solid var(--border);padding:6px 9px;vertical-align:top;text-align:left;word-break:keep-all;overflow-wrap:anywhere}\
.rb-man-tbl th{background:color-mix(in srgb,var(--accent) 9%,transparent);font-weight:700;color:var(--text-1);font-size:12px}\
.rb-man-tbl td.first{background:color-mix(in srgb,var(--grid) 55%,transparent);font-weight:600}\
.rb-man-steps{padding-left:22px;margin:0 0 12px}.rb-man-steps li{margin-bottom:6px}.rb-man-steps li::marker{color:var(--accent);font-weight:700}\
.rb-hd-body ul,.rb-man-body ul{padding-left:20px;margin:0 0 12px}.rb-hd-body li,.rb-man-body li{margin-bottom:5px}\
.rb-man-qa{margin:0 0 12px}.rb-man-qa .q{font-weight:700;margin-bottom:2px}.rb-man-qa .a{color:var(--text-2)}\
.rb-hd-body code,.rb-man-body code{background:var(--grid);border-radius:4px;padding:1px 5px;font-size:12px;font-family:ui-monospace,Cascadia Code,Consolas,monospace}\
.rb-hd-body mark,.rb-man-body mark,#man-nav mark{background:color-mix(in srgb,var(--pin) 35%,transparent);color:inherit;border-radius:2px;padding:0 1px}\
.rb-man-wrap{display:grid;grid-template-columns:250px minmax(0,1fr);gap:18px;align-items:start}\
@media (max-width:900px){.rb-man-wrap{grid-template-columns:1fr}.rb-man-toc{position:static!important;max-height:none!important}}\
.rb-man-toc{position:sticky;top:0;max-height:calc(100vh - 40px);overflow-y:auto;border:1px solid var(--border);border-radius:12px;padding:12px;background:var(--surface);display:flex;flex-direction:column;gap:8px}\
.rb-man-toc .input{width:100%}\
.rb-man-nav-ch{margin-bottom:6px}.rb-man-nav-ch>a{display:block;font-weight:700;font-size:13px;color:var(--text-1);text-decoration:none;padding:3px 6px;border-radius:6px}\
.rb-man-nav-ch>a:hover,.rb-man-nav-secs a:hover{background:color-mix(in srgb,var(--accent) 8%,transparent)}\
.rb-man-nav-secs a{display:block;font-size:12px;color:var(--text-2);text-decoration:none;padding:2px 6px 2px 16px;border-radius:6px}\
.rb-man-body{min-width:0}.rb-man-ch{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px 20px;margin-bottom:14px;font-size:13.5px;line-height:1.6}\
.rb-man-ch-head{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;border-bottom:2px solid color-mix(in srgb,var(--accent) 35%,transparent);padding-bottom:8px;margin-bottom:12px}\
.rb-man-ch-head h2{margin:0;font-size:17px;color:var(--accent)}\
.rb-man-sec{padding:6px 0 4px;border-top:1px dashed var(--grid);margin-top:10px}\
.rb-man-sec-head{display:flex;align-items:center;gap:4px;margin:6px 0 8px}\
.rb-man-ch.flash,.rb-man-sec.flash{animation:rbFlash 1.6s ease-out}\
@keyframes rbFlash{0%{background:color-mix(in srgb,var(--pin) 22%,transparent)}100%{background:transparent}}\
#rb-help-banner.top{display:flex;gap:14px;align-items:center;flex-wrap:wrap;border:1px solid color-mix(in srgb,var(--accent) 35%,transparent);background:color-mix(in srgb,var(--accent) 8%,transparent);border-radius:12px;padding:12px 16px;margin:0 0 16px}\
#rb-help-banner.bottom{position:fixed;left:50%;bottom:14px;transform:translateX(-50%);z-index:905;display:flex;gap:14px;align-items:center;flex-wrap:wrap;max-width:min(960px,96vw);border:1px solid color-mix(in srgb,var(--accent) 40%,transparent);background:var(--surface);box-shadow:0 8px 24px rgba(0,0,0,.12);border-radius:14px;padding:12px 16px}\
.rb-hb-icon{font-size:22px}.rb-hb-text{flex:1;min-width:220px;font-size:13px}.rb-hb-actions{display:flex;gap:6px;flex-wrap:wrap;align-items:center}\
#rb-help-editbar{position:fixed;top:10px;left:50%;transform:translateX(-50%);z-index:915;width:min(1000px,96vw);background:var(--surface);border:2px solid var(--pin);border-radius:14px;box-shadow:0 10px 30px rgba(0,0,0,.16);padding:10px 14px;display:none;flex-direction:column;gap:8px}\
#rb-help-editbar.open{display:flex}\
.rb-eb-msg{font-size:13px}.rb-eb-actions{display:flex;gap:6px;flex-wrap:wrap;align-items:center}\
.rb-eb-panel{display:flex;gap:14px;flex-wrap:wrap;align-items:center;border-top:1px solid var(--grid);padding-top:8px;font-size:13px}\
.rb-eb-panel label{display:inline-flex;gap:6px;align-items:center}\
body.rb-help-editing #rb-real{padding-top:118px}\
body.rb-help-editing #rb-real h1,body.rb-help-editing #rb-real h2,body.rb-help-editing #rb-real h3,body.rb-help-editing #rb-real label,body.rb-help-editing #rb-real summary,body.rb-help-editing #rb-real legend,body.rb-help-editing #rb-real .field-label,body.rb-help-editing #rb-real .option-title{outline:1px dashed transparent;outline-offset:3px;cursor:crosshair;border-radius:4px}\
body.rb-help-editing #rb-real h1:hover,body.rb-help-editing #rb-real h2:hover,body.rb-help-editing #rb-real h3:hover,body.rb-help-editing #rb-real label:hover,body.rb-help-editing #rb-real summary:hover,body.rb-help-editing #rb-real legend:hover,body.rb-help-editing #rb-real .field-label:hover,body.rb-help-editing #rb-real .option-title:hover{outline-color:var(--pin);background:color-mix(in srgb,var(--pin) 10%,transparent)}\
body.rb-help-editing #rbv-manual h1,body.rb-help-editing #rbv-manual h2,body.rb-help-editing #rbv-manual h3{cursor:default;outline:none!important;background:none!important}\
body.rb-help-editing .rb-help-btn[data-help]{box-shadow:0 0 0 3px color-mix(in srgb,var(--pin) 45%,transparent);cursor:pointer}\
#rb-help-popover{position:fixed;z-index:920;width:330px;background:var(--surface);border:1px solid var(--border);border-radius:12px;box-shadow:0 12px 32px rgba(0,0,0,.18);padding:12px 14px;display:flex;flex-direction:column;gap:8px;font-size:13px}\
#rb-help-popover label{display:flex;flex-direction:column;gap:3px;font-size:12px;color:var(--text-2)}#rb-help-popover .input{width:100%}\
.rb-pp-title{font-weight:700}.rb-pp-host{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.rb-pp-actions{display:flex;gap:6px;flex-wrap:wrap}";
  var style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  /* ---------- 시작 ---------- */
  function boot() {
    var real = document.getElementById("rb-real");
    if (!real) return;
    renderBanner();
    applyHelp();
    new MutationObserver(function (muts) {
      for (var i = 0; i < muts.length; i++) {
        var m = muts[i], skip = true;
        for (var j = 0; j < m.addedNodes.length; j++) { var n = m.addedNodes[j]; if (!(n.nodeType === 1 && n.classList && n.classList.contains("rb-help-btn"))) { skip = false; break; } }
        if (!skip || m.removedNodes.length) { scheduleApply(); return; }
      }
    }).observe(real, { childList: true, subtree: true });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
