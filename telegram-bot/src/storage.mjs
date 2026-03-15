import fs from "node:fs";

function readJson(filePath, fallback) {
  if (!fs.existsSync(filePath)) {
    return fallback;
  }

  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return fallback;
  }
}

function writeJson(filePath, value) {
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`);
}

export function readUserPrefs(filePath) {
  return readJson(filePath, {});
}

export function writeUserPrefs(filePath, prefs) {
  writeJson(filePath, prefs);
}

export function readForumTopics(filePath) {
  return readJson(filePath, {});
}

export function writeForumTopics(filePath, topics) {
  writeJson(filePath, topics);
}
