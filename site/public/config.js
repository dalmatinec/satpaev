// Настройки сайта. Меняете здесь, страница подхватывает сама.
window.SITE = {
  brand: "Satpaev",
  bot: "your_bot",          // юзернейм бота без @
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
    [50, 9.5],
    [250, 9.2],
    [1000, 8.9],
    [5000, 8.6],
  ],
};
