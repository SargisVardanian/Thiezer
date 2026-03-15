import { getConfig, ensureDataDir } from "./config.mjs";
import { copy, normalizeLanguage } from "./locales.mjs";
import { readForumTopics, readUserPrefs, writeUserPrefs } from "./storage.mjs";
import { callBotApi, sleep } from "./telegram-api.mjs";

const config = getConfig();
ensureDataDir();

const userPrefs = readUserPrefs(config.paths.prefsFile);
const forumTopics = readForumTopics(config.paths.topicsFile);

const languageDisplayNames = {
  hy: "Հայերեն",
  ru: "Русский",
  en: "English"
};

function languageForUser(user) {
  const saved = userPrefs[String(user.id)];
  if (saved) {
    return saved;
  }
  return normalizeLanguage(user.language_code);
}

function setUserLanguage(userId, language) {
  userPrefs[String(userId)] = language;
  writeUserPrefs(config.paths.prefsFile, userPrefs);
}

function html(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function formatUserLabel(user) {
  if (!user) {
    return "Unknown";
  }
  if (user.username) {
    return `@${user.username}`;
  }
  const parts = [user.first_name, user.last_name].filter(Boolean);
  if (parts.length > 0) {
    return parts.join(" ");
  }
  return String(user.id);
}

function simpleSummary(text) {
  if (!text) {
    return "";
  }
  const collapsed = text.replace(/\s+/g, " ").trim();
  if (!collapsed) {
    return "";
  }
  if (collapsed.length <= 180) {
    return collapsed;
  }
  const truncated = collapsed.slice(0, 180);
  const boundary = truncated.lastIndexOf(" ");
  const safeSlice = boundary > 0 ? truncated.slice(0, boundary) : truncated;
  return `${safeSlice}…`;
}

function describeAttachments(message) {
  const attachments = [];
  if (message.photo) {
    attachments.push("photo");
  }
  if (message.document) {
    const docName = message.document.file_name ? message.document.file_name : "document";
    attachments.push(docName);
  }
  if (message.video) {
    attachments.push("video");
  }
  if (message.animation) {
    attachments.push("animation");
  }
  if (message.audio) {
    attachments.push("audio");
  }
  if (message.voice) {
    attachments.push("voice note");
  }
  if (message.sticker) {
    attachments.push("sticker");
  }
  if (message.video_note) {
    attachments.push("video note");
  }
  return attachments.join(", ");
}

function buildDigestText(message, language, senderLabel) {
  const summaryPieces = [];
  const textSnippet = simpleSummary(message.text ?? message.caption ?? "");
  if (textSnippet) {
    summaryPieces.push(textSnippet);
  }
  const attachments = describeAttachments(message);
  if (attachments) {
    summaryPieces.push(`Attachments: ${attachments}`);
  }

  if (summaryPieces.length === 0) {
    return "";
  }

  const langLabel = languageDisplayNames[language] ?? language.toUpperCase();
  const intro = `<b>Thiezer Model Digest</b> • ${html(langLabel)}`;
  const meta = `<b>User:</b> ${html(senderLabel)} <b>ID:</b> <code>${html(String(message.from.id))}</code>`;
  const summaryLine = `<b>Summary:</b> ${html(summaryPieces.join(" • "))}`;
  const footer = `<i>Posted to the Community Chat for quick editorial review.</i>`;

  return [intro, meta, summaryLine, footer].join("\n");
}

async function publishDigestToGeneral(message, language) {
  const topicId = forumTopics.general?.message_thread_id;
  if (!topicId) {
    console.warn("[bot|digest] Community Chat topic is not configured. Run npm run bootstrap:forum.");
    return;
  }
  const digestText = buildDigestText(message, language, formatUserLabel(message.from));
  if (!digestText) {
    return;
  }

  try {
    await callBotApi(config.token, "sendMessage", {
      chat_id: config.forumChatId,
      message_thread_id: topicId,
      text: digestText,
      parse_mode: "HTML",
      disable_notification: true
    });
  } catch (error) {
    console.error(`[bot|digest] ${error.message}`);
  }
}

async function sendPrivateMessage(chatId, text) {
  await callBotApi(config.token, "sendMessage", {
    chat_id: chatId,
    text
  });
}

async function routeSubmission(message, language) {
  const submissionsTopicId = forumTopics.submissions?.message_thread_id;
  if (!submissionsTopicId) {
    throw new Error("Missing submissions topic. Run npm run bootstrap:forum in telegram-bot first.");
  }

  const user = message.from;
  const senderLabel = formatUserLabel(user);
  const header = [
    `<b>${html(copy[language].tipHeader)}</b>`,
    `<b>${html(copy[language].tipMeta)}:</b> ${html(language ?? copy[language].unknownLanguage)}`,
    `<b>User:</b> ${html(senderLabel)}`,
    `<b>User ID:</b> <code>${html(String(user.id))}</code>`
  ].join("\n");

  await callBotApi(config.token, "sendMessage", {
    chat_id: config.forumChatId,
    message_thread_id: submissionsTopicId,
    text: header,
    parse_mode: "HTML",
    disable_notification: true
  });

  if (message.text && !message.text.startsWith("/")) {
    await callBotApi(config.token, "sendMessage", {
      chat_id: config.forumChatId,
      message_thread_id: submissionsTopicId,
      text: message.text,
      disable_notification: true
    });
    return;
  }

  await callBotApi(config.token, "copyMessage", {
    chat_id: config.forumChatId,
    message_thread_id: submissionsTopicId,
    from_chat_id: message.chat.id,
    message_id: message.message_id,
    disable_notification: true,
    protect_content: true
  });
}

async function handleCommand(message) {
  const user = message.from;
  const language = languageForUser(user);
  const text = message.text ?? "";
  const [rawCommand, ...args] = text.trim().split(/\s+/);
  const command = rawCommand.split("@")[0];

  if (command === "/start") {
    await sendPrivateMessage(message.chat.id, `${copy[language].welcome}\n\n${copy[language].help}`);
    return;
  }

  if (command === "/submit") {
    await sendPrivateMessage(message.chat.id, copy[language].submitReady);
    return;
  }

  if (command === "/menu") {
    await sendPrivateMessage(message.chat.id, copy[language].menu);
    return;
  }

  if (command === "/language") {
    const requested = normalizeLanguage(args[0]);
    if (!args[0]) {
      await sendPrivateMessage(message.chat.id, copy[language].languagePrompt);
      return;
    }
    setUserLanguage(user.id, requested);
    await sendPrivateMessage(message.chat.id, copy[requested].languageSet);
  }
}

async function handlePrivateMessage(message) {
  const user = message.from;
  const language = languageForUser(user);

  if (message.text?.startsWith("/")) {
    await handleCommand(message);
    return;
  }

  await routeSubmission(message, language);
  await publishDigestToGeneral(message, language);
  await sendPrivateMessage(message.chat.id, copy[language].submitReceived);
}

async function handleUpdate(update) {
  const message = update.message ?? update.edited_message;
  if (!message?.chat || !message.from) {
    return;
  }

  if (message.chat.type === "private") {
    await handlePrivateMessage(message);
  }
}

async function main() {
  let offset = 0;

  while (true) {
    try {
      const updates = await callBotApi(config.token, "getUpdates", {
        offset,
        timeout: 30,
        allowed_updates: ["message", "edited_message"]
      });

      for (const update of updates) {
        offset = update.update_id + 1;
        await handleUpdate(update);
      }
    } catch (error) {
      console.error(`[bot] ${error.message}`);
      await sleep(3000);
    }
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
