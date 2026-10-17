(function () {
  var cfg = window.SITE || {};
  var bot = cfg.bot ? "https://t.me/" + cfg.bot : "#";

  document.querySelectorAll("[data-bot]").forEach(function (a) { a.href = bot; });
  document.querySelectorAll("[data-brand]").forEach(function (el) { if (cfg.brand) el.textContent = cfg.brand; });
  var year = document.querySelector("[data-year]");
  if (year) year.textContent = new Date().getFullYear();
  if (cfg.brand) document.title = cfg.brand + ": звёзды, NFT подарки и юзернеймы Telegram";

  var channel = document.querySelector("[data-channel]");
  if (channel && cfg.channel) { channel.href = cfg.channel; channel.hidden = false; }

  // сетка цен звёзд
  var body = document.querySelector("[data-tiers]");
  if (body && cfg.stars) {
    var fmt = function (n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, " ").replace(".", ","); };
    body.innerHTML = cfg.stars.map(function (row) {
      return "<tr><td>от " + fmt(row[0]) + " шт</td><td>" + fmt(row[1]) + " ₸</td></tr>";
    }).join("");
  }

  // смена юзернеймов на главном экране
  var list = cfg.usernames || [];
  var handle = document.querySelector("[data-handle]");
  var title = document.querySelector(".handle");
  var status = document.querySelector("[data-status]");
  var ton = document.querySelector("[data-ton]");
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!handle || list.length < 2 || reduce) return;

  var i = 0;
  setInterval(function () {
    if (document.hidden) return;
    i = (i + 1) % list.length;
    var lot = list[i];
    title.classList.remove("swap");
    void title.offsetWidth;
    handle.textContent = lot.name;
    status.textContent = lot.status;
    ton.textContent = lot.ton;
    title.classList.add("swap");
  }, 3200);
})();
