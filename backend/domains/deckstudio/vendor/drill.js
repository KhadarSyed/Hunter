// Article click-through: a click on a chart element (deckcharts.js calls deckDrill.open) or on a table row opens a
// panel on the slide listing the articles behind it, newest first: publisher icon and domain, date, author or account,
// channel, picture, a short summary and the headline linking the original. The deck carries its articles once
// (#deck-articles, built by renderer._drill_data); the last-24h charts list the refresh's own articles (window.deckLive).
(function () {
  "use strict";
  var el = document.getElementById("deck-articles");
  var data = JSON.parse((el && el.textContent) || "{}");
  var fields = data.fields || [];
  var PAGE = 50;

  function node(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null && text !== "") e.textContent = text;
    return e;
  }
  function web(url) { return /^https?:\/\//i.test(url || "") ? url : ""; }
  function domain(url) { try { return new URL(url).hostname.replace(/^www\./, ""); } catch (e) { return ""; } }
  function day(date) {
    var d = new Date(date);
    return isNaN(d) ? "" : d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
  }

  function deckRecord(i) {
    var row = data.rows[i], r = {};
    fields.forEach(function (k, j) { r[k] = row[j]; });
    r.icon = r.f >= 0 ? data.icons[r.f] : "";
    return r;
  }
  function liveRecord(n) {
    var live = window.deckLive || {};
    var a = (live.articles || []).filter(function (x) { return x.n === n; })[0];
    if (!a) return null;
    return { t: a.title, u: a.url, d: domain(a.url), dt: a.date, a: "", c: "News", o: a.outlet, i: "",
             s: a.snippet, icon: (live.icons || {})[a.outlet] || "" };
  }

  function mark(r) {                     // the publisher's icon, or its initial on the deck colour
    if (r.icon && r.icon.indexOf("data:image/") === 0) {
      var img = node("img", "drill-icon");
      img.src = r.icon;
      img.alt = "";
      return img;
    }
    return node("span", "drill-icon drill-initial", ((r.o || r.d || "?").match(/[A-Za-z0-9]/) || ["?"])[0].toUpperCase());
  }

  function card(r) {
    var c = node("article", "drill-card");
    var thumb = node("div", "drill-thumb");
    thumb.appendChild(mark(r));
    // the article's own picture: linked from its site, or carried in the deck when its link expires (social posts)
    var picture = web(r.i) || (/^data:image\//.test(r.i || "") ? r.i : "");
    if (picture) {
      var pic = node("img", "drill-pic");
      pic.src = picture;
      pic.alt = "";
      pic.loading = "lazy";
      pic.referrerPolicy = "no-referrer";
      pic.onerror = function () { pic.remove(); };
      thumb.appendChild(pic);
    }
    c.appendChild(thumb);
    var body = node("div", "drill-body");
    var src = node("div", "drill-src");
    src.appendChild(mark(r));
    src.appendChild(node("span", null, [r.d || r.o, day(r.dt), r.c].filter(Boolean).join(" · ")));
    body.appendChild(src);
    var title = node(web(r.u) ? "a" : "span", "drill-title", r.t || r.u);
    if (web(r.u)) { title.href = r.u; title.target = "_blank"; title.rel = "noopener noreferrer"; }
    body.appendChild(title);
    if (r.a) body.appendChild(node("div", "drill-by", "By " + r.a));
    if (r.s) body.appendChild(node("p", "drill-sum", r.s));
    c.appendChild(body);
    return c;
  }

  function panelOf(section) {
    var p = section.querySelector(".drill-panel");
    if (p) return p;
    p = node("aside", "drill-panel");
    p.setAttribute("aria-label", "Articles");
    var head = node("div", "drill-head");
    head.appendChild(node("div", "drill-count"));
    var close = node("button", "drill-close", "×");
    close.type = "button";
    close.setAttribute("aria-label", "Close the article list");
    close.addEventListener("click", function () { p.hidden = true; });
    head.appendChild(close);
    p.appendChild(head);
    p.appendChild(node("div", "drill-list"));
    var more = node("button", "drill-more", "Show more");
    more.type = "button";
    p.appendChild(more);
    // the deck turns slides on the wheel and arrow keys: inside the list they scroll it instead
    p.addEventListener("wheel", function (e) { e.stopPropagation(); });
    p.addEventListener("keydown", function (e) { e.stopPropagation(); if (e.key === "Escape") p.hidden = true; });
    section.appendChild(p);
    return p;
  }

  function show(section, label, records) {
    records = records.filter(Boolean).sort(function (a, b) { return String(b.dt || "").localeCompare(String(a.dt || "")); });
    if (!records.length) return;
    var p = panelOf(section), list = p.querySelector(".drill-list"), more = p.querySelector(".drill-more");
    p.querySelector(".drill-count").textContent = records.length + (records.length === 1 ? " article" : " articles") + " · " + label;
    list.textContent = "";
    list.scrollTop = 0;
    var shown = 0;
    function page() {
      records.slice(shown, shown + PAGE).forEach(function (r) { list.appendChild(card(r)); });
      shown = Math.min(records.length, shown + PAGE);
      more.hidden = shown >= records.length;
      more.textContent = "Show more (" + (records.length - shown) + ")";
    }
    more.onclick = page;
    page();
    p.hidden = false;
  }

  window.deckDrill = {
    // cfg: the chart's config (its drill map: element key -> article ids); key: the clicked element's key
    open: function (section, cfg, key, label) {
      var ids = cfg && cfg.drill && cfg.drill[key];
      if (!section || !ids || !ids.length) return;
      show(section, label || key, ids.map(cfg.live ? liveRecord : deckRecord));
    }
  };

  document.addEventListener("click", function (e) {
    var row = e.target.closest && e.target.closest("tr.drill-row");
    if (!row || (e.target.closest("a"))) return;
    var section = row.closest("section.slide");
    var ids = ((data.tables || {})[section.getAttribute("data-id")] || {})[row.getAttribute("data-drill")];
    if (ids) show(section, row.getAttribute("data-drill"), ids.map(deckRecord));
  });
})();
