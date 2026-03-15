import { getConfig, ensureDataDir } from "../src/config.mjs";
import { writeForumTopics } from "../src/storage.mjs";
import { callBotApi } from "../src/telegram-api.mjs";

const config = getConfig();
ensureDataDir();

async function main() {
  const result = {};

  await callBotApi(config.token, "editGeneralForumTopic", {
    chat_id: config.forumChatId,
    name: config.topicNames.general
  });

  result.general = {
    name: config.topicNames.general,
    message_thread_id: 1
  };

  for (const [key, name] of Object.entries({
    submissions: config.topicNames.submissions,
    hy: config.topicNames.hy,
    ru: config.topicNames.ru,
    en: config.topicNames.en
  })) {
    const topic = await callBotApi(config.token, "createForumTopic", {
      chat_id: config.forumChatId,
      name
    });

    result[key] = {
      name,
      message_thread_id: topic.message_thread_id
    };
  }

  if (result.submissions?.message_thread_id) {
    await callBotApi(config.token, "closeForumTopic", {
      chat_id: config.forumChatId,
      message_thread_id: result.submissions.message_thread_id
    });
  }

  writeForumTopics(config.paths.topicsFile, result);
  console.log(JSON.stringify(result, null, 2));
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
