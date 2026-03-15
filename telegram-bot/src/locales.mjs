export const copy = {
  en: {
    welcome:
      "Welcome to Thiezer Armenia. Send news tips to this bot privately and I will route them to the editorial intake. Use /language to switch your interface.",
    help:
      "Commands:\n/language hy|ru|en - switch interface\n/submit - send a private news tip\n/menu - show the topic layout",
    submitReady: "Send your text, photo, video, or document in this private chat and it will be routed to the submissions topic.",
    submitReceived: "Received. Your tip was routed to the editorial intake.",
    languageSet: "Language updated.",
    languagePrompt: "Use /language hy, /language ru, or /language en.",
    menu:
      "Thiezer Armenia forum layout:\n1. Community Chat\n2. User Submissions\n3. News HY\n4. News RU\n5. News EN",
    adminOnly: "This action is limited to editors.",
    tipHeader: "New user tip",
    tipMeta: "Source language",
    unknownLanguage: "unknown",
    commandDescriptions: [
      { command: "start", description: "Open the Thiezer Armenia bot" },
      { command: "submit", description: "Send a private news tip" },
      { command: "language", description: "Set your bot language" },
      { command: "menu", description: "Show forum sections" }
    ],
    description:
      "Thiezer Armenia intake bot for community tips, language-aware onboarding, and newsroom routing.",
    shortDescription: "Private news tips and language-aware forum routing."
  },
  ru: {
    welcome:
      "Добро пожаловать в Thiezer Armenia. Отправляйте новости в этот бот приватно, и я перенаправлю их в редакционный intake. Используйте /language для смены языка.",
    help:
      "Команды:\n/language hy|ru|en - сменить язык\n/submit - отправить новостную наводку\n/menu - показать структуру тем",
    submitReady: "Отправьте текст, фото, видео или документ в этот приватный чат, и материал уйдёт в intake-тему.",
    submitReceived: "Принято. Ваша наводка отправлена в редакционный intake.",
    languageSet: "Язык обновлён.",
    languagePrompt: "Используйте /language hy, /language ru или /language en.",
    menu:
      "Структура форума Thiezer Armenia:\n1. Community Chat\n2. User Submissions\n3. News HY\n4. News RU\n5. News EN",
    adminOnly: "Это действие доступно только редакторам.",
    tipHeader: "Новая пользовательская наводка",
    tipMeta: "Язык источника",
    unknownLanguage: "неизвестно",
    commandDescriptions: [
      { command: "start", description: "Открыть бот Thiezer Armenia" },
      { command: "submit", description: "Отправить приватную новость" },
      { command: "language", description: "Выбрать язык бота" },
      { command: "menu", description: "Показать разделы форума" }
    ],
    description:
      "Бот Thiezer Armenia для приватных новостных наводок, языковой настройки и маршрутизации в редакцию.",
    shortDescription: "Приватные новости и маршрутизация по языкам."
  },
  hy: {
    welcome:
      "Բարի գալուստ Thiezer Armenia։ Ուղարկեք նորությունների հուշումները այս բոթին անձնական չատում, և ես դրանք կուղարկեմ խմբագրական intake-ին։ Օգտագործեք /language՝ լեզուն փոխելու համար։",
    help:
      "Հրամաններ՝\n/language hy|ru|en - փոխել լեզուն\n/submit - ուղարկել նորության հուշում\n/menu - ցույց տալ թեմաների կառուցվածքը",
    submitReady:
      "Ուղարկեք տեքստ, լուսանկար, տեսանյութ կամ փաստաթուղթ այս անձնական չատում, և նյութը կուղարկվի intake թեմա։",
    submitReceived: "Ստացվեց։ Ձեր հուշումն ուղարկվեց խմբագրական intake-ին։",
    languageSet: "Լեզուն թարմացվեց։",
    languagePrompt: "Օգտագործեք /language hy, /language ru կամ /language en։",
    menu:
      "Thiezer Armenia ֆորումի կառուցվածքը՝\n1. Community Chat\n2. User Submissions\n3. News HY\n4. News RU\n5. News EN",
    adminOnly: "Այս գործողությունը հասանելի է միայն խմբագիրներին։",
    tipHeader: "Օգտատիրոջ նոր հուշում",
    tipMeta: "Աղբյուրի լեզու",
    unknownLanguage: "անհայտ",
    commandDescriptions: [
      { command: "start", description: "Բացել Thiezer Armenia բոթը" },
      { command: "submit", description: "Ուղարկել անձնական նորություն" },
      { command: "language", description: "Ընտրել բոթի լեզուն" },
      { command: "menu", description: "Ցույց տալ ֆորումի բաժինները" }
    ],
    description:
      "Thiezer Armenia բոթը նախատեսված է անձնական նորությունների հուշումների, լեզվային onboarding-ի և խմբագրական routing-ի համար։",
    shortDescription: "Անձնական նորություններ և լեզվային routing։"
  }
};

export function normalizeLanguage(input) {
  const base = (input ?? "").toLowerCase().slice(0, 2);
  if (base === "hy" || base === "ru" || base === "en") {
    return base;
  }
  return "en";
}
