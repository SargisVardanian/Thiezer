import fs from "node:fs";
import path from "node:path";

const inputDate = process.argv[2] ?? new Date().toISOString().slice(0, 10);
const rootDir = process.cwd();
const outputDir = path.join(rootDir, "content", "drafts");
const outputFile = path.join(outputDir, `${inputDate}.json`);

if (!fs.existsSync(outputDir)) {
  fs.mkdirSync(outputDir, { recursive: true });
}

if (fs.existsSync(outputFile)) {
  console.error(`Draft already exists: ${outputFile}`);
  process.exit(1);
}

const template = {
  date: inputDate,
  topic: "",
  sourceLinks: [],
  stories: {
    hy: {
      headline: "",
      summary: "",
      socialCaption: ""
    },
    ru: {
      headline: "",
      summary: "",
      socialCaption: ""
    },
    en: {
      headline: "",
      summary: "",
      socialCaption: ""
    }
  }
};

fs.writeFileSync(outputFile, `${JSON.stringify(template, null, 2)}\n`);
console.log(`Created ${outputFile}`);
