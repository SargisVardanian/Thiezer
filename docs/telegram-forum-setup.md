# Telegram Forum Setup

## Target structure

The intended Telegram layout for Thiezer Armenia is a single supergroup with five topics:

1. `Community Chat` (the general discussion area where the whole community can react to daily briefs). 
2. `User Submissions` (locked intake topic where the bot routes private provisions). 
3. `News HY` (Armenian-language briefing thread). 
4. `News RU` (Russian-language briefing thread). 
5. `News EN` (English-language briefing thread).

## Practical architecture

- Public discussion happens in the forum supergroup topics.
- User submissions come in via the bot's private chat.
- The bot forwards those submissions into `User Submissions`.
- Editors can then rewrite and repost into `News HY`, `News RU`, or `News EN`.
- A digest model also listens for every intake and posts a short, multilingual summary into `Community Chat` so that the wider group quickly sees what arrived and can react or expand it.

## Limitation

Telegram forum topics are not true private tabs inside one shared supergroup. If `User Submissions` must be invisible to normal members, use a separate private editorial group. The bot in `telegram-bot/` is structured so that only the routing target needs to change.

## Manual steps Telegram still requires

1. Create the supergroup with Topics enabled.
2. Add the bot as admin.
3. Run `telegram-bot/npm run bootstrap:forum`.
4. Pin the important topics in Telegram if desired.
5. Share only the public invite link publicly.
