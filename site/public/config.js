// Общие настройки сайта (в git). Свои данные: бот, менеджер, канал, лежат в config.local.js
// на сервере, его создаёт deploy.sh, и обновления из git его не затирают.
window.SITE = {
  brand: "Satpaev",
  bot: "",                  // юзернейм бота без @ (задаётся в config.local.js)
  manager: "",              // аккаунт менеджера без @ (задаётся в config.local.js)
  channel: "",              // ссылка на канал, например https://t.me/your_channel

  // юзернеймы, которые крутятся на главном экране
  lots: [
    { name: "satpaev", status: "Передан клиенту", ton: 120 },
    { name: "steppe", status: "Идёт аукцион", ton: 340 },
    { name: "tenge", status: "В наличии", ton: 95 },
    { name: "nomad", status: "Передан клиенту", ton: 560 },
    { name: "altyn", status: "Идёт аукцион", ton: 410 },
  ],

  // бегущая строка
  ticker: ["@altyn", "@steppe", "@tenge", "@nomad", "@qazaq", "@sky", "@bek", "@aru", "@orda", "@tulpar"],

  // сетка цен на звёзды: от скольки штук и цена одной звезды в тенге (как в боте)
  stars: [
    [500, 12],
    [1000, 11.5],
    [5000, 11],
  ],
};
