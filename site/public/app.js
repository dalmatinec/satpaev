(function () {
  "use strict";

  var cfg = window.SITE || {};
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var finePointer = window.matchMedia("(hover: hover) and (pointer: fine)").matches;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  // ---------- ссылки на бота и бренд ----------
  var botBase = cfg.bot ? "https://t.me/" + cfg.bot : "#";
  function botLink(start) { return cfg.bot ? botBase + (start ? "?start=" + encodeURIComponent(start) : "") : "#"; }
  $$("[data-bot]").forEach(function (a) { a.href = botLink(); });
  $$("[data-bot-start]").forEach(function (a) { a.href = botLink(a.getAttribute("data-bot-start")); });
  if (cfg.brand) {
    $$("[data-brand]").forEach(function (el) { el.textContent = cfg.brand; });
    document.title = cfg.brand + ": звёзды, NFT подарки и юзернеймы Telegram";
  }
  var minOrder = $("[data-min-order]");
  if (minOrder && cfg.minOrder) minOrder.textContent = String(cfg.minOrder).replace(/\B(?=(\d{3})+(?!\d))/g, " ") + " ₸";
  var year = $("[data-year]");
  if (year) year.textContent = new Date().getFullYear();
  var channel = $("[data-channel]");
  if (channel && cfg.channel) { channel.href = cfg.channel; channel.hidden = false; }
  var manager = String(cfg.manager || "").replace(/^@/, "");
  if (manager) {
    $$("[data-manager]").forEach(function (a) { a.href = "https://t.me/" + manager; a.hidden = false; });
    $$("[data-manager-name]").forEach(function (el) { el.textContent = "@" + manager; });
  }

  var fmt = function (n) {
    var parts = String(Math.round(n * 100) / 100).split(".");
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, " ");
    return parts.join(",");
  };

  // ---------- звёздное небо ----------
  var canvas = $(".sky");
  if (canvas && canvas.getContext) {
    var ctx = canvas.getContext("2d");
    var stars = [], W = 0, H = 0, dpr = Math.min(window.devicePixelRatio || 1, 2);
    var px = 0, py = 0, tx = 0, ty = 0, shooting = null, last = 0;

    var resize = function () {
      W = window.innerWidth; H = window.innerHeight;
      canvas.width = W * dpr; canvas.height = H * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      var count = Math.min(220, Math.round((W * H) / 8000));
      stars = [];
      for (var i = 0; i < count; i++) {
        stars.push({
          x: Math.random() * W, y: Math.random() * H,
          r: Math.random() * 1.05 + .15, z: Math.random() * .8 + .2,
          tw: Math.random() * Math.PI * 2, sp: Math.random() * .02 + .005,
          gold: Math.random() < .06
        });
      }
    };

    var draw = function (t) {
      ctx.clearRect(0, 0, W, H);
      px += (tx - px) * .05; py += (ty - py) * .05;
      for (var i = 0; i < stars.length; i++) {
        var s = stars[i];
        s.tw += s.sp;
        var a = .25 + Math.sin(s.tw) * .3 + .2;
        var x = s.x + px * s.z * 18, y = s.y + py * s.z * 18;
        ctx.globalAlpha = Math.max(0, Math.min(1, a));
        ctx.fillStyle = s.gold ? "#d8bd84" : "#e9e9f2";
        ctx.beginPath(); ctx.arc(x, y, s.r * (s.gold ? 1.3 : 1), 0, 6.283); ctx.fill();
      }
      // падающая звезда раз в несколько секунд
      if (!shooting && t - last > 4200 + Math.random() * 6000) {
        last = t;
        shooting = { x: Math.random() * W * .7 + W * .2, y: Math.random() * H * .3, l: 0 };
      }
      if (shooting) {
        shooting.l += 14;
        var sx = shooting.x - shooting.l, sy = shooting.y + shooting.l * .45;
        var g = ctx.createLinearGradient(sx, sy, sx + 120, sy - 54);
        g.addColorStop(0, "rgba(241,223,180,.7)"); g.addColorStop(1, "rgba(241,223,180,0)");
        ctx.globalAlpha = 1; ctx.strokeStyle = g; ctx.lineWidth = 1.6;
        ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(sx + 120, sy - 54); ctx.stroke();
        if (shooting.l > W) shooting = null;
      }
      ctx.globalAlpha = 1;
      if (!reduce && !document.hidden) requestAnimationFrame(draw);
    };

    resize();
    window.addEventListener("resize", resize);
    document.addEventListener("visibilitychange", function () { if (!document.hidden && !reduce) requestAnimationFrame(draw); });
    window.addEventListener("pointermove", function (e) { tx = e.clientX / W - .5; ty = e.clientY / H - .5; }, { passive: true });
    requestAnimationFrame(draw);
  }

  // ---------- свечение за курсором ----------
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

  // ---------- полоса прокрутки ----------
  var bar = $(".progress");
  var onScroll = function () {
    var h = document.documentElement.scrollHeight - window.innerHeight;
    if (bar) bar.style.setProperty("--p", h > 0 ? window.scrollY / h : 0);
  };
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  // ---------- появление блоков ----------
  if ("IntersectionObserver" in window && !reduce) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
      });
    }, { threshold: .12, rootMargin: "0px 0px -40px 0px" });
    $$(".reveal").forEach(function (el, i) {
      el.style.transitionDelay = (i % 4) * 70 + "ms";
      io.observe(el);
    });
  } else {
    $$(".reveal").forEach(function (el) { el.classList.add("in"); });
  }

  // ---------- 3D наклон и подсветка стекла ----------
  if (finePointer && !reduce) {
    $$(".tilt").forEach(function (el) {
      el.addEventListener("pointermove", function (e) {
        var r = el.getBoundingClientRect();
        var x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
        el.style.transform = "perspective(1000px) rotateX(" + ((.5 - y) * 4) + "deg) rotateY(" + ((x - .5) * 5) + "deg)";
        el.style.setProperty("--sx", x * 100 + "%"); el.style.setProperty("--sy", y * 100 + "%");
      });
      el.addEventListener("pointerleave", function () { el.style.transform = ""; });
    });
    // магнитные кнопки
    $$(".magnetic").forEach(function (el) {
      el.addEventListener("pointermove", function (e) {
        var r = el.getBoundingClientRect();
        var x = e.clientX - r.left - r.width / 2, y = e.clientY - r.top - r.height / 2;
        el.style.transform = "translate(" + x * .1 + "px," + y * .18 + "px)";
      });
      el.addEventListener("pointerleave", function () { el.style.transform = ""; });
    });
  }

  // ---------- юзернеймы на главном экране ----------
  var lots = cfg.lots || [];
  var nameEl = $("[data-scramble]"), lotName = $("[data-lot-name]"), lotStatus = $("[data-lot-status]");
  var lotTon = $("[data-lot-ton]"), lotBar = $("[data-lot-bar]"), timerEl = $("[data-timer]");
  var deadline = Date.now() + 6.9 * 864e5;
  var glyphs = "abcdefghijklmnopqrstuvwxyz0123456789_";

  function scramble(el, to) {
    if (!el) return;
    if (reduce) { el.textContent = to; return; }
    var from = el.textContent, len = Math.max(from.length, to.length), frame = 0, total = 22;
    (function step() {
      var out = "";
      for (var i = 0; i < len; i++) {
        var reveal = frame / total * len;
        if (i < reveal) out += to[i] || "";
        else out += i < Math.max(to.length, 1) ? glyphs[Math.floor(Math.random() * glyphs.length)] : "";
      }
      el.textContent = out;
      if (++frame <= total) requestAnimationFrame(step); else el.textContent = to;
    })();
  }

  function showLot(lot) {
    scramble(nameEl, lot.name);
    if (lotName) lotName.textContent = lot.name;
    if (lotStatus) lotStatus.textContent = lot.status;
    if (lotTon) countTo(lotTon, lot.ton);
    deadline = Date.now() + (1 + Math.random() * 6) * 864e5;
    if (lotBar) lotBar.style.width = (20 + Math.random() * 70) + "%";
  }

  function countTo(el, value, suffix) {
    suffix = suffix || "";
    var start = parseFloat(String(el.textContent).replace(/\s/g, "").replace(",", ".")) || 0;
    if (el._raf) cancelAnimationFrame(el._raf);
    if (reduce) { el.textContent = fmt(value) + suffix; return; }
    var t0 = performance.now(), dur = 600;
    (function step(now) {
      var k = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - k, 3);
      el.textContent = fmt(Math.round(start + (value - start) * e)) + suffix;
      if (k < 1) el._raf = requestAnimationFrame(step);
    })(t0);
  }

  if (lots.length) {
    var li = 0;
    showLot(lots[0]);
    if (lots.length > 1) {
      setInterval(function () {
        if (document.hidden) return;
        li = (li + 1) % lots.length;
        showLot(lots[li]);
      }, 4200);
    }
  }
  if (timerEl) {
    setInterval(function () {
      var s = Math.max(0, Math.floor((deadline - Date.now()) / 1000));
      var d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60), sec = s % 60;
      var p = function (n) { return (n < 10 ? "0" : "") + n; };
      timerEl.textContent = d + "д " + p(h) + ":" + p(m) + ":" + p(sec);
    }, 1000);
  }

  // ---------- бегущая строка ----------
  var track = $("[data-ticker]");
  if (track) {
    var items = (cfg.ticker || []).map(function (t) { return "<span>" + t.replace(/[<>&]/g, "") + "</span>"; }).join("");
    track.innerHTML = items + items;
  }

  // ---------- калькулятор звёзд ----------
  var tiers = (cfg.stars || [[50, 9.5]]).slice().sort(function (a, b) { return a[0] - b[0]; });
  var MIN = tiers[0][0], MAX = 100000;
  var qtyInput = $("#qty"), range = $("[data-range]"), unitEl = $("[data-unit]"), sumEl = $("[data-sum]");
  var tiersEl = $("[data-tiers]"), chipsEl = $("[data-chips]"), buy = $("[data-buy-stars]");

  if (tiersEl) {
    tiersEl.innerHTML = tiers.map(function (t, i) {
      return '<li data-tier="' + i + '"><span>от ' + fmt(t[0]) + ' шт</span><b>' + fmt(t[1]) + " ₸</b></li>";
    }).join("");
  }
  if (chipsEl) {
    [100, 500, 1000, 2500, 5000, 10000].filter(function (v) { return v >= MIN; }).forEach(function (v) {
      var b = document.createElement("button");
      b.type = "button"; b.className = "chip"; b.textContent = fmt(v); b.dataset.v = v;
      chipsEl.appendChild(b);
    });
    chipsEl.addEventListener("click", function (e) {
      var v = e.target && e.target.dataset && e.target.dataset.v;
      if (v) setQty(+v, true);
    });
  }

  // логарифмическая шкала: удобно и для 50, и для 100 000
  var toRange = function (q) { return Math.round(Math.log(q / MIN) / Math.log(MAX / MIN) * 1000); };
  var fromRange = function (r) {
    var q = MIN * Math.pow(MAX / MIN, r / 1000);
    var step = q < 1000 ? 10 : q < 10000 ? 50 : 500;
    return Math.max(MIN, Math.round(q / step) * step);
  };
  var unitFor = function (q) {
    var u = tiers[0][1], idx = 0;
    tiers.forEach(function (t, i) { if (q >= t[0]) { u = t[1]; idx = i; } });
    return [u, idx];
  };

  function setQty(q, fromOutside) {
    q = Math.max(MIN, Math.min(MAX, Math.round(q) || MIN));
    var res = unitFor(q), unit = res[0];
    if (fromOutside && qtyInput) qtyInput.value = q;
    if (range) {
      if (fromOutside || document.activeElement !== range) range.value = toRange(q);
      range.style.setProperty("--fill", range.value / 10 + "%");
    }
    if (unitEl) unitEl.textContent = fmt(unit) + " ₸";
    if (sumEl) countTo(sumEl, Math.round(unit * q), " ₸");
    $$("[data-tier]").forEach(function (el) { el.classList.toggle("on", +el.dataset.tier === res[1]); });
    $$(".chip").forEach(function (c) { c.classList.toggle("on", +c.dataset.v === q); });
    if (buy) buy.href = botLink("stars_" + q);
  }

  if (qtyInput) {
    qtyInput.min = MIN;
    qtyInput.addEventListener("input", function () { if (qtyInput.value) setQty(+qtyInput.value, false); });
    qtyInput.addEventListener("blur", function () { setQty(+qtyInput.value || MIN, true); });
  }
  if (range) range.addEventListener("input", function () { setQty(fromRange(+range.value), false); if (qtyInput) qtyInput.value = fromRange(+range.value); });
  setQty(qtyInput ? +qtyInput.value : 500, true);

  // ---------- проверка юзернейма ----------
  var form = $("[data-check]"), hint = $("[data-check-hint]"), frag = $("[data-fragment]");
  var USER_RE = /^[a-zA-Z][a-zA-Z0-9_]{3,31}$/;
  if (form) {
    var input = form.querySelector("input");
    var validate = function () {
      var v = input.value.trim().replace(/^@/, "");
      input.value = v;
      form.classList.remove("ok", "bad");
      if (!v) { hint.textContent = "Латиница, цифры и «_», от 4 до 32 символов."; frag.href = "https://fragment.com/"; return null; }
      if (!USER_RE.test(v)) {
        form.classList.add("bad");
        hint.textContent = /^[0-9_]/.test(v) ? "Юзернейм должен начинаться с буквы." :
          v.length < 4 ? "Слишком коротко: нужно от 4 символов." : "Только латиница, цифры и «_».";
        return null;
      }
      form.classList.add("ok");
      hint.textContent = "Формат подходит. Бот проверит статус @" + v + " на Fragment.";
      frag.href = "https://fragment.com/username/" + v.toLowerCase();
      return v.toLowerCase();
    };
    input.addEventListener("input", validate);
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var v = validate();
      if (!v) { input.focus(); return; }
      if (cfg.bot) window.open(botLink("un_" + v), "_blank", "noopener");
    });
  }

  // ---------- терминал деплоя ----------
  var term = $("[data-term]");
  if (term) {
    var lines = [
      ["cmd", "$ git clone ваш-проект && cd ваш-проект"],
      ["", "Cloning into 'ваш-проект'... done."],
      ["cmd", "$ docker compose up -d --build"],
      ["ok", "✔ db       Started"],
      ["ok", "✔ redis    Started"],
      ["ok", "✔ bot      Started"],
      ["cmd", "$ certbot --nginx -d example.kz"],
      ["ok", "✔ SSL сертификат выпущен, автопродление включено"],
      ["cmd", "$ ./backup.sh"],
      ["ok", "✔ Бэкап базы сохранён"],
      ["", "Готово, проект в продакшене."]
    ];
    var played = false;
    var play = function () {
      if (played) return; played = true;
      if (reduce) {
        term.innerHTML = lines.map(function (l) { return '<span class="' + l[0] + '">' + l[1] + "</span>"; }).join("\n");
        return;
      }
      var li2 = 0, ci = 0, html = "";
      (function type() {
        if (li2 >= lines.length) { term.innerHTML = html + '<span class="caret"></span>'; return; }
        var l = lines[li2];
        if (l[0] !== "cmd") { html += '<span class="' + l[0] + '">' + l[1] + "</span>\n"; li2++; term.innerHTML = html; return setTimeout(type, 260); }
        ci++;
        term.innerHTML = html + '<span class="cmd">' + l[1].slice(0, ci) + '</span><span class="caret"></span>';
        if (ci >= l[1].length) { html += '<span class="cmd">' + l[1] + "</span>\n"; li2++; ci = 0; return setTimeout(type, 380); }
        setTimeout(type, 28 + Math.random() * 40);
      })();
    };
    if ("IntersectionObserver" in window) {
      var tio = new IntersectionObserver(function (en) { if (en[0].isIntersecting) { play(); tio.disconnect(); } }, { threshold: .4 });
      tio.observe(term);
    } else play();
  }
})();
