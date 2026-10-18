(function () {
  "use strict";

  var cfg = window.SITE || {};
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var finePointer = window.matchMedia("(hover: hover) and (pointer: fine)").matches;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var USER_RE = /^[a-zA-Z][a-zA-Z0-9_]{3,31}$/;

  // данные: из config.js, потом свежие из бота через /api/site
  var data = {
    bot: cfg.bot || "", brand: cfg.brand || "SatBox", min_order: cfg.minOrder || 10000,
    rates: [], ton_kzt: 0, stars: { tiers: cfg.stars || [[500, 20]], min_qty: 500 }, texts: {}
  };

  var fmt = function (n, digits) {
    var d = digits === undefined ? (Number(n) % 1 ? 2 : 0) : digits;
    var parts = Number(n).toFixed(d).split(".");
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, " ");
    return parts.join(",").replace(/(,\d*?)0+$/, "$1").replace(/,$/, "");
  };
  var tenge = function (n) { return fmt(Math.round(n), 0) + " ₸"; };
  function botLink(start) {
    if (!data.bot) return "#";
    return "https://t.me/" + data.bot + (start ? "?start=" + encodeURIComponent(start) : "");
  }

  // ---------- подстановка данных (только textContent, без HTML: защита от XSS) ----------
  function applyLinks() {
    $$("[data-bot]").forEach(function (a) { a.href = botLink(); });
    $$("[data-bot-start]").forEach(function (a) { a.href = botLink(a.getAttribute("data-bot-start")); });
    var manager = String(cfg.manager || "").replace(/^@/, "");
    if (manager) {
      $$("[data-manager]").forEach(function (a) { a.href = "https://t.me/" + manager; a.hidden = false; });
      $$("[data-manager-name]").forEach(function (el) { el.textContent = "@" + manager; });
    }
    var channel = $("[data-channel]");
    if (channel && cfg.channel) { channel.href = cfg.channel; channel.hidden = false; }
  }

  function applyTexts() {
    $$("[data-t]").forEach(function (el) {
      var v = data.texts[el.getAttribute("data-t")];
      if (typeof v === "string" && v.trim()) el.textContent = v;
    });
    // последнее слово главного заголовка подсвечиваем, как на макете
    var title = $(".hero-title");
    if (title) {
      var words = title.textContent.trim().split(/\s+/);
      if (words.length > 1) {
        var last = words.pop();
        title.textContent = words.join(" ") + " ";
        var hl = document.createElement("span");
        hl.className = "hl"; hl.textContent = last;
        title.appendChild(hl);
      }
    }
    if (data.brand) {
      $$("[data-brand]").forEach(function (el) { el.textContent = data.brand; });
      document.title = data.brand + ": криптообмен, звёзды, NFT подарки и юзернеймы Telegram";
    }
    $$("[data-min-order]").forEach(function (el) { el.textContent = tenge(data.min_order); });
    var year = $("[data-year]");
    if (year) year.textContent = new Date().getFullYear();
  }

  function loadSite() {
    var ctrl = window.AbortController ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctrl) ctrl.abort(); }, 6000);
    return fetch("/api/site", { signal: ctrl ? ctrl.signal : undefined, credentials: "omit" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (j) {
        clearTimeout(timer);
        data.bot = j.bot || data.bot;
        data.brand = j.brand || data.brand;
        data.min_order = j.min_order || data.min_order;
        data.rates = Array.isArray(j.rates) ? j.rates : [];
        data.ton_kzt = j.ton_kzt || 0;
        if (j.stars && Array.isArray(j.stars.tiers) && j.stars.tiers.length) data.stars = j.stars;
        data.texts = j.texts || {};
        return true;
      })
      .catch(function () { clearTimeout(timer); return false; });
  }

  // ---------- фон: мелкие звёзды ----------
  var canvas = $(".sky");
  if (canvas && canvas.getContext) {
    var ctx = canvas.getContext("2d"), stars = [], W = 0, H = 0, dpr = Math.min(window.devicePixelRatio || 1, 2);
    var resize = function () {
      W = window.innerWidth; H = window.innerHeight;
      canvas.width = W * dpr; canvas.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      stars = [];
      for (var i = 0, n = Math.min(160, Math.round(W * H / 9000)); i < n; i++) {
        stars.push({ x: Math.random() * W, y: Math.random() * H, r: Math.random() * 1.1 + .2, t: Math.random() * 6.3, s: Math.random() * .02 + .004,
          c: Math.random() < .2 ? "#f0abfc" : "#e9e3ff" });
      }
    };
    var draw = function () {
      ctx.clearRect(0, 0, W, H);
      for (var i = 0; i < stars.length; i++) {
        var s = stars[i]; s.t += s.s;
        ctx.globalAlpha = .25 + Math.sin(s.t) * .25 + .2;
        ctx.fillStyle = s.c; ctx.beginPath(); ctx.arc(s.x, s.y, s.r, 0, 6.283); ctx.fill();
      }
      if (!reduce && !document.hidden) requestAnimationFrame(draw);
    };
    resize(); window.addEventListener("resize", resize);
    document.addEventListener("visibilitychange", function () { if (!document.hidden && !reduce) requestAnimationFrame(draw); });
    requestAnimationFrame(draw);
  }

  var glow = $(".cursor-glow");
  if (glow && finePointer && !reduce) {
    var gx = -999, gy = -999, cx = -999, cy = -999;
    window.addEventListener("pointermove", function (e) { gx = e.clientX; gy = e.clientY; }, { passive: true });
    (function loop() {
      cx += (gx - cx) * .12; cy += (gy - cy) * .12;
      glow.style.setProperty("--mx", cx + "px"); glow.style.setProperty("--my", cy + "px");
      requestAnimationFrame(loop);
    })();
  }

  var bar = $(".progress");
  var onScroll = function () {
    var h = document.documentElement.scrollHeight - window.innerHeight;
    if (bar) bar.style.setProperty("--p", h > 0 ? window.scrollY / h : 0);
  };
  window.addEventListener("scroll", onScroll, { passive: true }); onScroll();

  if ("IntersectionObserver" in window && !reduce) {
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } });
    }, { threshold: .1, rootMargin: "0px 0px -30px 0px" });
    $$(".reveal").forEach(function (el, i) { el.style.transitionDelay = (i % 4) * 70 + "ms"; io.observe(el); });
  } else {
    $$(".reveal").forEach(function (el) { el.classList.add("in"); });
  }

  // лёгкий 3D наклон куба за курсором
  var cube = $(".cube");
  if (cube && finePointer && !reduce) {
    window.addEventListener("pointermove", function (e) {
      var x = e.clientX / window.innerWidth - .5, y = e.clientY / window.innerHeight - .5;
      cube.style.transform = "perspective(800px) rotateY(" + x * 14 + "deg) rotateX(" + (-y * 10) + "deg)";
    }, { passive: true });
  }

  // ---------- обмен ----------
  var ex = { code: "", dir: "buy", unit: "coin" };
  var ratesBox = $("[data-rates]"), codesBox = $("[data-ex-codes]"), amountEl = $("[data-ex-amount]");
  var unitBtn = $("[data-ex-unit]"), outEl = $("[data-ex-out]"), rateEl = $("[data-ex-rate]"), warnEl = $("[data-ex-warn]");
  var exGo = $("[data-ex-go]"), exLabel = $("[data-ex-label]"), exOutLabel = $("[data-ex-out-label]");

  function rateOf(code) { return data.rates.filter(function (r) { return r.code === code; })[0]; }

  function renderRates() {
    if (!ratesBox) return;
    ratesBox.textContent = "";
    if (!data.rates.length) {
      var p = document.createElement("p"); p.className = "muted pad"; p.textContent = "Курс уточняйте в боте: нажмите «Обменять в боте».";
      ratesBox.appendChild(p);
    }
    data.rates.forEach(function (r) {
      var row = document.createElement("div");
      row.className = "rate-row" + (r.code === ex.code ? " on" : "");
      [r.code, r.buy ? fmt(r.buy) + " ₸" : "нет", r.sell ? fmt(r.sell) + " ₸" : "нет"].forEach(function (v, i) {
        var el = document.createElement(i ? "span" : "b"); el.textContent = v; row.appendChild(el);
      });
      row.addEventListener("click", function () { ex.code = r.code; renderRates(); renderCodes(); calcEx(); });
      ratesBox.appendChild(row);
    });
  }

  function renderCodes() {
    if (!codesBox) return;
    codesBox.textContent = "";
    data.rates.forEach(function (r) {
      var b = document.createElement("button");
      b.type = "button"; b.className = "chip" + (r.code === ex.code ? " on" : ""); b.textContent = r.code;
      b.addEventListener("click", function () { ex.code = r.code; renderRates(); renderCodes(); calcEx(); });
      codesBox.appendChild(b);
    });
  }

  function calcEx() {
    if (!data.rates.length) {
      if (exGo) exGo.href = botLink("ex");
      return;
    }
    if (!rateOf(ex.code)) ex.code = data.rates[0].code;
    var r = rateOf(ex.code);
    var rate = ex.dir === "buy" ? r.sell : r.buy;
    var amount = parseFloat(String(amountEl.value).replace(",", ".")) || 0;
    unitBtn.textContent = ex.unit === "coin" ? r.code : "₸";
    exLabel.textContent = (ex.dir === "buy" ? "Сколько купить" : "Сколько продать") + (ex.unit === "coin" ? "" : ", в тенге");
    warnEl.hidden = true;
    if (!rate) {
      outEl.textContent = "нет"; rateEl.textContent = "нет";
      warnEl.textContent = ex.dir === "buy" ? "Покупка " + r.code + " сейчас недоступна" : "Продажа " + r.code + " сейчас недоступна";
      warnEl.hidden = false;
    } else {
      var kzt = ex.unit === "coin" ? amount * rate : amount;
      var coins = ex.unit === "coin" ? amount : amount / rate;
      rateEl.textContent = fmt(rate) + " ₸";
      if (ex.unit === "coin") {
        exOutLabel.textContent = ex.dir === "buy" ? "Вы платите" : "Вы получаете";
        outEl.textContent = tenge(kzt);
      } else {
        exOutLabel.textContent = ex.dir === "buy" ? "Вы получите" : "Нужно продать";
        outEl.textContent = fmt(coins, 2) + " " + r.code;
      }
      if (amount > 0 && kzt < data.min_order) {
        warnEl.textContent = "Минимальный заказ " + tenge(data.min_order); warnEl.hidden = false;
      } else if (r.min && coins < r.min && amount > 0) {
        warnEl.textContent = "Минимум " + fmt(r.min) + " " + r.code; warnEl.hidden = false;
      }
    }
    exGo.href = botLink("ex_" + r.code);
  }

  $$("[data-ex-dir] button").forEach(function (b) {
    b.addEventListener("click", function () {
      ex.dir = b.getAttribute("data-dir");
      $$("[data-ex-dir] button").forEach(function (x) { x.classList.toggle("on", x === b); });
      calcEx();
    });
  });
  if (unitBtn) unitBtn.addEventListener("click", function () { ex.unit = ex.unit === "coin" ? "kzt" : "coin"; amountEl.value = ex.unit === "coin" ? 100 : 50000; calcEx(); });
  if (amountEl) amountEl.addEventListener("input", calcEx);

  // ---------- звёзды ----------
  var qtyInput = $("#qty"), range = $("[data-range]"), unitEl = $("[data-unit]"), sumEl = $("[data-sum]");
  var tiersEl = $("[data-tiers]"), chipsEl = $("[data-chips]"), buyStars = $("[data-buy-stars]");
  var MAX = 100000;
  function minQty() { return Math.max(data.stars.min_qty || 0, data.stars.tiers[0][0]); }
  function unitFor(q) {
    var u = data.stars.tiers[0][1], idx = 0;
    data.stars.tiers.forEach(function (t, i) { if (q >= t[0]) { u = t[1]; idx = i; } });
    return [u, idx];
  }
  var toRange = function (q) { return Math.round(Math.log(q / minQty()) / Math.log(MAX / minQty()) * 1000); };
  var fromRange = function (v) {
    var q = minQty() * Math.pow(MAX / minQty(), v / 1000), step = q < 1000 ? 10 : q < 10000 ? 50 : 500;
    return Math.max(minQty(), Math.round(q / step) * step);
  };
  function renderTiers() {
    if (tiersEl) {
      tiersEl.textContent = "";
      data.stars.tiers.forEach(function (t, i) {
        var li = document.createElement("li"); li.setAttribute("data-tier", i);
        var a = document.createElement("span"); a.textContent = "от " + fmt(t[0], 0) + " шт";
        var b = document.createElement("b"); b.textContent = fmt(t[1]) + " ₸";
        li.appendChild(a); li.appendChild(b); tiersEl.appendChild(li);
      });
    }
    if (chipsEl) {
      chipsEl.textContent = "";
      [500, 1000, 2500, 5000, 10000, 25000].filter(function (v) { return v >= minQty(); }).forEach(function (v) {
        var b = document.createElement("button"); b.type = "button"; b.className = "chip"; b.textContent = fmt(v, 0); b.dataset.v = v;
        b.addEventListener("click", function () { setQty(v, true); });
        chipsEl.appendChild(b);
      });
    }
  }
  function setQty(q, outside) {
    q = Math.max(minQty(), Math.min(MAX, Math.round(q) || minQty()));
    var res = unitFor(q);
    if (outside && qtyInput) qtyInput.value = q;
    if (range) { if (outside || document.activeElement !== range) range.value = toRange(q); range.style.setProperty("--fill", range.value / 10 + "%"); }
    if (unitEl) unitEl.textContent = fmt(res[0]) + " ₸";
    if (sumEl) sumEl.textContent = tenge(res[0] * q);
    $$("[data-tier]").forEach(function (el) { el.classList.toggle("on", +el.getAttribute("data-tier") === res[1]); });
    $$("[data-chips] .chip").forEach(function (c) { c.classList.toggle("on", +c.dataset.v === q); });
    if (buyStars) buyStars.href = botLink("stars_" + q);
  }
  if (qtyInput) {
    qtyInput.addEventListener("input", function () { if (qtyInput.value) setQty(+qtyInput.value, false); });
    qtyInput.addEventListener("blur", function () { setQty(+qtyInput.value || minQty(), true); });
  }
  if (range) range.addEventListener("input", function () { var q = fromRange(+range.value); if (qtyInput) qtyInput.value = q; setQty(q, false); });

  // ---------- поиск юзернейма в реальном времени ----------
  var form = $("[data-check]"), hint = $("[data-check-hint]"), result = $("[data-result]");
  var STATUS = {
    sale: ["Продаётся", "sale"], auction: ["Аукцион", "auction"], sold: ["Продан", "sold"], taken: ["Занят", "taken"],
    free: ["Свободен или недоступен", "free"], notfound: ["Нет на Fragment", "notfound"], other: ["Fragment", "free"], unknown: ["Нет данных", ""]
  };
  var live = { name: "", timer: null, ends: 0, checked: 0 };

  function showResult(j) {
    var st = STATUS[j.status] || STATUS.unknown;
    $("[data-r-name]").textContent = "@" + j.username;
    var badge = $("[data-r-badge]"); badge.textContent = st[0]; badge.className = "badge " + st[1];
    var price = "нет данных";
    if (j.price_ton) price = fmt(j.price_ton) + " TON" + (data.ton_kzt ? " ≈ " + tenge(j.price_ton * data.ton_kzt) : "");
    $("[data-r-price]").textContent = price;
    live.ends = j.ends_at ? Date.parse(j.ends_at) || 0 : 0;
    live.checked = Date.now();
    $("[data-r-order]").href = botLink("un_" + j.username);
    $("[data-r-fragment]").href = "https://fragment.com/username/" + encodeURIComponent(j.username);
    result.hidden = false;
    tick();
  }
  function tick() {
    var t = $("[data-r-timer]");
    if (live.ends) {
      var s = Math.max(0, Math.floor((live.ends - Date.now()) / 1000));
      var d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60), sec = s % 60;
      var p = function (n) { return (n < 10 ? "0" : "") + n; };
      t.textContent = (d ? d + "д " : "") + p(h) + ":" + p(m) + ":" + p(sec);
    } else {
      t.textContent = "нет";
    }
    if (live.checked) {
      var ago = Math.round((Date.now() - live.checked) / 1000);
      $("[data-r-updated]").textContent = "Обновляется в реальном времени · проверено " + (ago < 5 ? "только что" : ago + " с назад");
    }
  }
  function check(name) {
    return fetch("/api/username?u=" + encodeURIComponent(name), { credentials: "omit" })
      .then(function (r) { return r.json().then(function (j) { return [r.status, j]; }); })
      .then(function (res) {
        if (res[0] === 429) { hint.textContent = "Слишком много запросов, подождите минуту."; return; }
        if (res[0] !== 200) { hint.textContent = "Проверить не удалось, попробуйте позже или спросите в боте."; return; }
        if (live.name === res[1].username) showResult(res[1]);
      })
      .catch(function () { hint.textContent = "Проверка работает на сайте с сервером. Откройте бота, он проверит юзер."; });
  }
  if (form) {
    var input = form.querySelector("input");
    var validate = function () {
      var v = input.value.trim().replace(/^@/, ""); input.value = v;
      form.classList.remove("bad");
      if (!v) { hint.textContent = "Латиница, цифры и «_», от 4 до 32 символов."; return null; }
      if (!USER_RE.test(v)) {
        form.classList.add("bad");
        hint.textContent = /^[0-9_]/.test(v) ? "Юзернейм должен начинаться с буквы." : v.length < 4 ? "Нужно от 4 символов." : "Только латиница, цифры и «_».";
        return null;
      }
      hint.textContent = "Ищу @" + v + " на Fragment...";
      return v.toLowerCase();
    };
    input.addEventListener("input", function () { validate(); });
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var v = validate();
      if (!v) { input.focus(); return; }
      live.name = v;
      clearInterval(live.timer);
      check(v).then(function () { if (live.name === v) hint.textContent = "Слежу за @" + v + ": обновление каждые 30 секунд."; });
      live.timer = setInterval(function () { if (!document.hidden && live.name) check(live.name); }, 30000);
    });
    setInterval(function () { if (!result.hidden) tick(); }, 1000);
  }

  // ---------- терминал ----------
  var term = $("[data-term]");
  if (term) {
    var lines = [
      ["cmd", "$ git clone ваш-проект && cd ваш-проект"], ["", "Cloning into 'ваш-проект'... done."],
      ["cmd", "$ docker compose up -d --build"], ["ok", "✔ db       Started"], ["ok", "✔ redis    Started"], ["ok", "✔ bot      Started"],
      ["cmd", "$ certbot --nginx -d example.kz"], ["ok", "✔ SSL сертификат выпущен, автопродление включено"],
      ["cmd", "$ ./backup.sh"], ["ok", "✔ Бэкап базы сохранён"], ["", "Готово, проект в продакшене."]
    ];
    var add = function (cls, text) { var s = document.createElement("span"); if (cls) s.className = cls; s.textContent = text; term.appendChild(s); };
    var played = false;
    var play = function () {
      if (played) return; played = true;
      if (reduce) { lines.forEach(function (l) { add(l[0], l[1] + "\n"); }); return; }
      var li = 0;
      (function next() {
        if (li >= lines.length) { add("caret", ""); return; }
        var l = lines[li++];
        if (l[0] !== "cmd") { add(l[0], l[1] + "\n"); return setTimeout(next, 260); }
        var span = document.createElement("span"); span.className = "cmd"; term.appendChild(span);
        var ci = 0;
        (function type() {
          span.textContent = l[1].slice(0, ++ci);
          if (ci < l[1].length) return setTimeout(type, 26 + Math.random() * 40);
          span.textContent += "\n"; setTimeout(next, 380);
        })();
      })();
    };
    if ("IntersectionObserver" in window) {
      var tio = new IntersectionObserver(function (en) { if (en[0].isIntersecting) { play(); tio.disconnect(); } }, { threshold: .4 });
      tio.observe(term);
    } else play();
  }

  // ---------- старт ----------
  function render() {
    applyLinks(); applyTexts(); renderRates(); renderCodes(); calcEx(); renderTiers();
    setQty(qtyInput ? +qtyInput.value : 1000, true);
  }
  render();
  loadSite().then(function (ok) { if (ok) render(); });
  // курсы и тексты подтягиваются раз в минуту, пока вкладка открыта
  setInterval(function () { if (!document.hidden) loadSite().then(function (ok) { if (ok) { renderRates(); renderCodes(); calcEx(); } }); }, 60000);
})();
