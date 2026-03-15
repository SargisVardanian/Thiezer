import { getConfig } from "../src/config.mjs";
import { copy } from "../src/locales.mjs";
import { callBotApi } from "../src/telegram-api.mjs";

const config = getConfig();

async function setupLanguage(language) {
  const locale = copy[language];
  await callBotApi(config.token, "setMyCommands", {
    language_code: language,
    commands: locale.commandDescriptions
  });

  await callBotApi(config.token, "setMyDescription", {
    language_code: language,
    description: locale.description
  });

  await callBotApi(config.token, "setMyShortDescription", {
    language_code: language,
    short_description: locale.shortDescription
  });
}

async function main() {
  for (const language of ["en", "ru", "hy"]) {
    await setupLanguage(language);
  }

  console.log("Bot profile and localized commands configured.");
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
