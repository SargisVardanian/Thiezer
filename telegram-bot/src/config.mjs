import fs from "node:fs";
import path from "node:path";
import { loadEnvFile, getProjectRoot } from "./env.mjs";

loadEnvFile();

const rootDir = getProjectRoot();
const dataDir = path.join(rootDir, "data");
const prefsFile = path.join(dataDir, "user-preferences.json");
const topicsFile = path.join(dataDir, "forum-topics.json");

export const supportedLanguages = ["hy", "ru", "en"];

function requireEnv(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

export function getConfig() {
  return {
    token: requireEnv("TELEGRAM_BOT_TOKEN"),
    forumChatId: requireEnv("TELEGRAM_FORUM_CHAT_ID"),
    forumInviteLink: process.env.TELEGRAM_FORUM_INVITE_LINK ?? "",
    siteUrl: process.env.THIEZER_SITE_URL ?? "https://thiezer-armenia.pages.dev",
    contactEmail: process.env.THIEZER_CONTACT_EMAIL ?? "ThiezerArmenia1991@gmail.com",
    adminUserIds: (process.env.ADMIN_USER_IDS ?? "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean),
    topicNames: {
      general: process.env.TOPIC_GENERAL_NAME ?? "Community Chat",
      submissions: process.env.TOPIC_SUBMISSIONS_NAME ?? "User Submissions",
      hy: process.env.TOPIC_HY_NAME ?? "News HY",
      ru: process.env.TOPIC_RU_NAME ?? "News RU",
      en: process.env.TOPIC_EN_NAME ?? "News EN"
    },
    paths: {
      dataDir,
      prefsFile,
      topicsFile
    }
  };
}

export function ensureDataDir() {
  fs.mkdirSync(dataDir, { recursive: true });
}
