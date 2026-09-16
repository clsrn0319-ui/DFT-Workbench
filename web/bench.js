/* ------------------------------------------------------------------
   벤치마크 페이지 (#rbv-bench) — 문헌 참조값과 이 프로그램의 계산값 비교
     GET  /api/benchmarks                → 세트 목록 + 항목별 보고서
     POST /api/benchmarks/{set}/run      → 항목마다 좌표 고정 단일점 작업 제출
     GET  /api/benchmarks/{set}/report   → 보고서만 다시
   ------------------------------------------------------------------ */
(function () {
  "use strict";
  var IS_SNAPSHOT = !!window.__RB_SNAPSHOT__;
  var DATA = null, timer = null, busy = false;

  function h(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function f2(v) { return v == null || isNaN(v) ? "—" : (v > 0 ? "+" : "") + Number(v).toFixed(2); }
  function f3(v) { return v == null || isNaN(v) ? "—" : Number(v).toFixed(2); }
  function badge(v) {
    var cls = { PASS: "published", REVIEW: "review", FAIL: "failed", "계산 중": "running", "실패": "failed", "미실행": "queued", "부분 완료": "review", "판정 불가": "queued" }[v] || "queued";
    return "<span class=\"badge " + cls + "\">" + h(v) + "</span>";
  }
  function deltaCell(d, tol) {
    if (d == null) return "<td class=\"num muted\">—</td>";
    var a = Math.abs(d), color = a <= tol.pass ? "var(--ok)" : a <= tol.review ? "var(--pin)" : "var(--danger)";
    return "<td class=\"num\" style=\"color:" + color + ";font-weight:600\">" + f2(d) + "</td>";
  }

  function root() { return document.getElementById("rbv-bench"); }

  function render() {
    var el = root();
    if (!el) return;
    if (!DATA) { el.innerHTML = "<h1>벤치마크</h1><div class=\"empty\">불러오는 중…</div>"; return; }
    var html = "<h1>벤치마크</h1>" +
      "<p class=\"rb-note\">문헌이 공개한 <b>같은 좌표·같은 계산식</b>으로 이 프로그램이 참조값을 재현하는지 확인합니다. " +
      "«실행»을 누르면 항목마다 좌표를 고정한 단일점 작업이 만들어지고, 끝나면 참조값과의 차이(Δ)와 판정이 표에 채워집니다. " +
      "판정 기준: |Δ| ≤ 허용값이면 PASS, 검토값 이내면 REVIEW, 그 밖은 FAIL. 세트는 <span class=\"mono\">server/benchmarks/*.json</span> 파일로 추가합니다.</p>";
    if (!DATA.sets.length) html += "<div class=\"empty\">등록된 벤치마크 세트가 없습니다.</div>";
    DATA.sets.forEach(function (set) {
      var rep = set.report, tol = set.tolerance_ev, running = rep.rows.some(function (r) { return r.verdict === "계산 중"; });
      var q = set.quantities;
      html += "<div class=\"card\" data-set=\"" + h(set.id) + "\">" +
        "<div class=\"card-head\"><h2>" + h(set.title) + " " + badge(rep.overall) + "</h2>" +
        "<div class=\"toolbar\" style=\"margin:0\">" +
        (IS_SNAPSHOT ? "" : "<button class=\"btn primary\" type=\"button\" data-run=\"" + h(set.id) + "\"" + (busy ? " disabled" : "") + ">▶ 실행 (" + set.entries.length + "개 작업)</button>") +
        "<button class=\"btn ghost\" type=\"button\" data-refresh=\"1\">새로고침</button></div></div>" +
        "<p class=\"small\" style=\"margin:0 0 8px\">" + h(set.description) + "</p>" +
        "<div class=\"small muted\" style=\"margin-bottom:10px\">출처: " + h(set.source.citation) +
        (set.source.doi ? " · <a href=\"https://doi.org/" + h(set.source.doi) + "\" target=\"_blank\" rel=\"noopener\">doi:" + h(set.source.doi) + "</a>" : "") +
        " · " + h(set.source.figure) + " · " + h(set.source.data) + "<br>논문 방법: " + h(set.source.method) + "</div>" +
        "<div class=\"toolbar\" style=\"gap:6px\">" +
        "<span class=\"chip\">범함수 " + h(set.protocol.functional) + "</span><span class=\"chip\">기저 " + h(set.protocol.basis) + "</span>" +
        "<span class=\"chip\">" + h(set.protocol.envType) + "</span><span class=\"chip soft\">좌표 고정 · " + (set.protocol.optimizeGeometry ? "최적화" : "최적화 없음") + "</span>" +
        "<span class=\"chip soft\">허용 ±" + h(tol.pass) + " eV · 검토 ±" + h(tol.review) + " eV</span>" +
        (set.protocol.note ? "<span class=\"small muted\">" + h(set.protocol.note) + "</span>" : "") + "</div>" +
        "<div class=\"stat-row\">" +
        "<div class=\"stat-tile\"><div class=\"stat-label\">완료</div><div class=\"stat-value\">" + rep.n_done + "<span class=\"stat-unit\"> / " + rep.n_total + "</span></div><div class=\"stat-sub\">" + (running ? "계산 중 — 5초마다 갱신" : "항목") + "</div></div>" +
        q.map(function (qq) { return "<div class=\"stat-tile\"><div class=\"stat-label\">MAE " + h(qq[1]) + "</div><div class=\"stat-value\">" + (rep.mae[qq[0]] == null ? "—" : f3(rep.mae[qq[0]])) + "<span class=\"stat-unit\"> " + h(qq[2]) + "</span></div><div class=\"stat-sub\">평균 절대 오차</div></div>"; }).join("") +
        "<div class=\"stat-tile\"><div class=\"stat-label\">전체 판정</div><div class=\"stat-value\" style=\"font-size:20px\">" + badge(rep.overall) + "</div><div class=\"stat-sub\">완료된 항목 기준</div></div>" +
        "</div>" +
        "<div class=\"scroll-x\"><table class=\"table\"><thead><tr><th>모델</th><th>구조</th>" +
        q.map(function (qq) { return "<th class=\"num\" colspan=\"3\">" + h(qq[1]) + " (" + h(qq[2]) + ")</th>"; }).join("") +
        "<th>판정</th><th>작업</th></tr><tr><th></th><th></th>" +
        q.map(function () { return "<th class=\"num small\">참조</th><th class=\"num small\">계산</th><th class=\"num small\">Δ</th>"; }).join("") +
        "<th></th><th></th></tr></thead><tbody>";
      rep.rows.forEach(function (r) {
        html += "<tr><td><b>" + h(r.name) + "</b><div class=\"small muted mono\">" + h(r.formula) + " · " + r.n_atoms + "원자</div></td>" +
          "<td class=\"small\">" + h(r.model) + "</td>";
        q.forEach(function (qq) {
          var k = qq[0];
          html += "<td class=\"num\">" + f3(r.reference[k]) + "</td><td class=\"num\">" + (r.computed ? f3(r.computed[k]) : "—") + "</td>" +
            deltaCell(r.delta ? r.delta[k] : null, tol);
        });
        var jobCell = "";
        if (r.job) {
          jobCell = "<div class=\"small mono muted\">" + h(r.job) + "</div>" +
            (r.status === "RUNNING" || r.status === "QUEUED" ? "<div class=\"small\">" + h(r.stage || r.status) + (r.progress != null ? " · " + r.progress + "%" : "") + "</div>" : "") +
            (r.validation ? "<div class=\"small\">검증 " + badge(r.validation) + "</div>" : "") +
            (r.error ? "<div class=\"small\" style=\"color:var(--danger)\">" + h(r.error) + "</div>" : "") +
            "<div class=\"row-actions\">" +
            (r.status === "PUBLISHED" ? "<button class=\"btn ghost\" type=\"button\" data-result=\"" + h(r.job) + "\">결과</button>" : "") +
            (IS_SNAPSHOT ? "" : "<button class=\"btn ghost\" type=\"button\" data-monitor=\"" + h(r.job) + "\">모니터</button>" +
            "<button class=\"btn ghost\" type=\"button\" data-run=\"" + h(set.id) + "\" data-entry=\"" + h(r.entry) + "\"" + (busy ? " disabled" : "") + ">다시 실행</button>") + "</div>";
        } else {
          jobCell = "<span class=\"small muted\">아직 실행하지 않음</span>" +
            (IS_SNAPSHOT ? "" : " <button class=\"btn ghost\" type=\"button\" data-run=\"" + h(set.id) + "\" data-entry=\"" + h(r.entry) + "\"" + (busy ? " disabled" : "") + ">실행</button>");
        }
        html += "<td>" + badge(r.verdict) + "</td><td>" + jobCell + "</td></tr>";
        if (r.reproduced) {
          html += "<tr><td colspan=\"" + (4 + 3 * q.length) + "\" class=\"small muted\" style=\"padding-top:0;border-top:none\">↳ 재현 기록 " + h(r.reproduced.date) + ": " +
            q.map(function (qq) { return h(qq[1]) + " " + f3(r.reproduced[qq[0]]); }).join(" · ") + " — " + h(r.reproduced.note) + "</td></tr>";
        }
      });
      html += "</tbody></table></div></div>";
    });
    el.innerHTML = html;
    el.querySelectorAll("[data-run]").forEach(function (b) {
      b.addEventListener("click", function () { run(b.dataset.run, b.dataset.entry ? [b.dataset.entry] : []); });
    });
    el.querySelectorAll("[data-refresh]").forEach(function (b) { b.addEventListener("click", function () { load(); }); });
    el.querySelectorAll("[data-result]").forEach(function (b) {
      b.addEventListener("click", function () { if (window.rbShowResultJob) window.rbShowResultJob(b.dataset.result); });
    });
    el.querySelectorAll("[data-monitor]").forEach(function (b) {
      b.addEventListener("click", function () { if (window.rbOpenMonitor) window.rbOpenMonitor(b.dataset.monitor); });
    });
    schedule();
  }

  function schedule() {
    clearTimeout(timer);
    var real = document.getElementById("rb-real");
    var open = real && real.classList.contains("mode-bench");
    var running = DATA && DATA.sets.some(function (s) { return s.report.rows.some(function (r) { return r.verdict === "계산 중"; }); });
    if (open && running) timer = setTimeout(load, 5000);
  }

  async function load() {
    try {
      var res = await fetch("/api/benchmarks");
      if (res.status === 401) { location.reload(); return; }
      if (!res.ok) throw new Error("HTTP " + res.status);
      DATA = await res.json();
    } catch (e) {
      var el = root();
      if (el) el.innerHTML = "<h1>벤치마크</h1><div class=\"empty\">벤치마크 목록을 불러오지 못했습니다 — " + h(e.message) + "</div>";
      return;
    }
    render();
  }

  async function run(setId, entries) {
    if (busy) return;
    busy = true; render();
    try {
      var res = await fetch("/api/benchmarks/" + encodeURIComponent(setId) + "/run", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ entries: entries || [] }) });
      var body = await res.json().catch(function () { return {}; });
      if (!res.ok) { alert(body.detail || ("실행 실패 (HTTP " + res.status + ")")); }
    } catch (e) { alert("실행 실패: " + e.message); }
    busy = false;
    await load();
  }

  window.rbRenderBench = function () { render(); load(); };
})();
