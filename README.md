# Thiezer Armenia

Multilingual Armenia news starter project for a website plus Telegram, Facebook, and Instagram rollout.
This repository is also structured as a base template for future country-specific `Thiezer` editions.

## What is included

- A working landing page for `Thiezer Armenia` with Armenian, Russian, and English switching.
- Seed editorial content that shows the daily-briefing structure.
- A draft generator for daily news entries in `/content/drafts`.
- Launch and workflow documents for website and social channels.
- A Telegram bot scaffold for multilingual forum topics and hidden intake routing in `/telegram-bot`.

## Local run

```bash
npm install
npm run dev
```

Production build:

```bash
npm run build
```

Cloudflare Pages deploy after one-time auth:

```bash
npx wrangler login
npm run build
npx wrangler pages deploy ./dist --project-name=thiezer-armenia
```

Create a draft file for a new daily brief:

```bash
npm run create:brief -- 2026-03-16
```

## What still needs your input

- Official logo, colors, and any brand assets for `Thiezer Armenia`.
- Account access for Telegram, Facebook, and Instagram.
- Source policy: which Armenian outlets, institutions, and newsletters should be monitored daily.
- Hosting target for the site.

## Project structure

- `index.html`: homepage shell.
- `src/main.js`: language switching and rendering.
- `src/content/site-data.js`: initial localized copy and channel definitions.
- `src/styles.css`: responsive visual system.
- `scripts/create-daily-brief.mjs`: draft generator.
- `docs/social-launch.md`: launch checklist and channel strategy.
- `docs/editorial-workflow.md`: daily editorial pipeline.
- `docs/telegram-forum-setup.md`: Telegram forum layout and bot workflow.
- `telegram-bot/`: bot bootstrap, localized commands, and private intake routing.
