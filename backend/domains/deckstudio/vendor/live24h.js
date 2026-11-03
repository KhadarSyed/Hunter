// The deck's "last 24h" slides: draws their text (cited summary, top stories, "Last updated") from the stored refresh
// in each slide's .live-data, and -- when the deck is shown inside Hunter -- a Refresh button. The deck runs sandboxed
// with no network, so Hunter's page (its parent frame) runs the refresh and posts progress and the result back here;
// opened on its own (a file, or outside Hunter) the deck shows the stored refresh and no button.
(function () {
  "use strict";
  var exportMode = new URLSearchParams(location.search).has("export");
  var framed = window.parent !== window && !exportMode;
  var TOP_STORIES = 10, CITES = 3, MAX_BULLETS = 5;     // what fits the slide without clipping
  var DASHBOARD = "latest24h-dashboard";
  var textSlide = document.querySelector('section.slide[data-type="latest24h"]');
  var slides = [].slice.call(document.querySelectorAll('section.slide[data-type^="latest24h"]'));
  if (!textSlide) return;
  var dataEl = textSlide.querySelector(".live-data");
  var live = window.deckLive = JSON.parse((dataEl && dataEl.textContent) || "{}");   // the 24h charts' click-through reads it
  var btn = textSlide.querySelector(".live-btn");
  var box = textSlide.querySelector(".live-progress");

  function node(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function web(url) { return /^https?:\/\//i.test(url || "") ? url : ""; }
  function utc(date, opts) {
    var d = new Date(date);
    return isNaN(d) ? "" : d.toLocaleString("en-GB", Object.assign({ timeZone: "UTC" }, opts)) + " UTC";
  }
  function icon(outlet) {
    var src = (live.icons || {})[outlet];
    if (!src || src.indexOf("data:image/") !== 0) return null;      // only images carried in the deck itself
    var img = node("img", "live-icon");
    img.src = src;
    img.alt = "";
    return img;
  }
  function link(url, cls) {
    var a = node(web(url) ? "a" : "span", cls);
    if (web(url)) { a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer"; }
    return a;
  }

  function meta() {
    var text = live.finished_at
      ? "Last updated " + utc(live.finished_at * 1000, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) +
        " · " + live.fetched + " fetched, " + live.kept + " kept"
      : "Not refreshed yet";
    slides.forEach(function (s) { var m = s.querySelector(".live-meta"); if (m) m.textContent = text; });
  }

  function empty(where, text) {
    where.textContent = "";
    where.appendChild(node("div", "live-empty", text));
  }

  function text() {
    var bullets = textSlide.querySelector(".live-bullets");
    var list = textSlide.querySelector(".live-stories ol");
    list.textContent = "";
    if (!live.articles) {
      return empty(bullets, framed ? "Refresh to load the last 24h" : "No 24h refresh stored yet: open this deck in Hunter and press Refresh latest 24h");
    }
    if (!live.articles.length) return empty(bullets, "No new coverage in the last 24 hours");
    var byN = {};
    live.articles.forEach(function (a) { byN[a.n] = a; });
    bullets.textContent = "";
    (live.bullets || []).slice(0, MAX_BULLETS).forEach(function (b) {
      var item = node("div", "live-bullet build", b.text);
      var cites = node("div", "cites");
      (b.citations || []).slice(0, CITES).forEach(function (n) {
        var a = byN[n];
        if (!a) return;
        var c = link(a.url, "cite");
        var img = icon(a.outlet);
        if (img) c.appendChild(img);
        c.appendChild(document.createTextNode(a.outlet || "Source"));
        c.title = a.title || "";
        cites.appendChild(c);
      });
      if (cites.children.length) item.appendChild(cites);
      bullets.appendChild(item);
    });
    live.articles.slice(0, TOP_STORIES).forEach(function (a) {
      var li = node("li");
      var img = icon(a.outlet);
      if (img) li.appendChild(img);
      var body = node("div");
      var t = link(a.url);
      t.textContent = a.title || a.url;
      body.appendChild(t);
      var when = utc(a.date, { hour: "2-digit", minute: "2-digit" });
      body.appendChild(node("small", null, [a.outlet, when, (a.brands || []).join(", ")].filter(Boolean).join(" · ")));
      li.appendChild(body);
      list.appendChild(li);
    });
  }

  // the dashboard's charts rebuilt from a new refresh, styled as the deck drew them (fonts, colours, logos)
  function chartConfigs(charts) {
    var api = window.deckCharts;
    var old = (api && api.configs && api.configs[DASHBOARD]) || [];
    if (!old.length) return null;
    var marks = {};
    old.forEach(function (cfg) { (cfg && cfg.data || []).forEach(function (d) { if (d.logo) marks[d.category] = d; }); });
    function bars(tpl, chart, logos) {
      var pairs = (chart.categories || []).map(function (k, i) { return [k, chart.values[i]]; })
        .sort(function (a, b) { return b[1] - a[1]; });
      var top = Math.max.apply(null, pairs.map(function (p) { return p[1]; }).concat([1]));
      return Object.assign({}, tpl, { drill: chart.drill || {}, live: true, data: pairs.map(function (p) {
        var m = marks[p[0]] || {};
        return { category: p[0], value: p[1], color: tpl.accent, opacity: Math.round((0.45 + 0.55 * p[1] / top) * 100) / 100,
                 logo: logos[p[0]] || m.logo || "", chip: m.chip || "" };
      }) });
    }
    var t = charts.timeline || {};
    var peaks = t.peaks || [];
    var hours = {};                     // "02 Nov 14:00" -> "14:00", as the axis shows it
    Object.keys(t.drill || {}).forEach(function (k) { hours[String(k).slice(-5)] = t.drill[k]; });
    return [
      old[0] && bars(old[0], charts.share || {}, {}),
      old[1] && Object.assign({}, old[1], { drill: hours, live: true, data: (t.categories || []).map(function (k, i) {
        return { category: String(k).slice(-5), value: t.values[i], peak: peaks.indexOf(i) >= 0, color: old[1].accent };
      }) }),
      old[2] && bars(old[2], charts.outlets || {}, (charts.icons || {}))
    ];
  }

  function progress(state) {
    // running totals only: which source found what stays in the stored refresh, not on the slide
    box.hidden = false;
    box.textContent = "";
    var total = node("div", null, "");
    total.appendChild(node("b", null, String(state.total)));
    total.appendChild(document.createTextNode(" articles fetched"));
    box.appendChild(total);
    if (state.kept != null) box.appendChild(node("div", null, state.kept + " kept after dedupe and relevance checks · writing the summary…"));
  }

  function done(message) {
    btn.disabled = false;
    btn.textContent = "Refresh latest 24h";
    if (message) { box.hidden = false; box.textContent = message; } else box.hidden = true;
  }

  var state = null;
  function onHost(m) {
    if (m.event === "ready") { btn.hidden = false; return; }
    if (m.event === "progress" && state) {
      var p = m.data || {};
      if (p.phase === "filtered") { state.total = p.total; state.kept = p.kept; }
      else if (p.source) state.total = Math.max(state.total, p.total || 0);
      if (!p.phase || p.phase === "filtered") progress(state);
      return;
    }
    if (m.event === "result" && m.refresh) {
      var r = m.refresh, charts = r.charts || {};
      live = { refresh_id: r.id, finished_at: r.finished_at, fetched: r.fetched, kept: r.kept, counts: r.counts || {},
               bullets: (r.summary || {}).bullets || [], articles: r.articles || [], icons: charts.icons || {} };
      window.deckLive = live;
      state = null;
      meta();
      text();
      var cfgs = chartConfigs(charts);
      if (cfgs && window.deckCharts && window.deckCharts.redraw) window.deckCharts.redraw(DASHBOARD, cfgs);
      done();
      return;
    }
    if (m.event === "error") { state = null; done(m.message || "The refresh failed"); }
  }

  meta();
  text();
  if (!framed || !btn) return;
  window.addEventListener("message", function (e) {
    if (e.source !== window.parent || !e.data || e.data.type !== "hunter-deck-host") return;
    onHost(e.data);
  });
  btn.addEventListener("click", function () {
    state = { total: 0, kept: null };
    btn.disabled = true;
    btn.textContent = "Refreshing…";
    progress(state);
    window.parent.postMessage({ type: "hunter-deck", action: "latest24h-refresh" }, "*");
  });
  // Hunter answers "ready" when it can run a refresh: only then is the button shown
  window.parent.postMessage({ type: "hunter-deck", action: "hello" }, "*");
})();
