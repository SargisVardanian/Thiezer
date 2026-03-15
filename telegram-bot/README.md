# Thiezer Armenia Telegram Bot

This bot layer is designed for a forum-style Telegram supergroup with five sections:

1. `Community Chat`
2. `User Submissions`
3. `News HY`
4. `News RU`
5. `News EN`

## Important constraint

Telegram bots can create and manage forum topics, and they can route messages into a specific topic using `message_thread_id`. However, Telegram does not provide true per-topic secrecy inside one shared supergroup. This implementation closes the `User Submissions` topic and routes private user messages into it through the bot, but editors should still treat it as an editorial intake topic, not as a cryptographically hidden vault.

## Setup

1. Create a Telegram bot via `@BotFather`.
2. Create a supergroup and enable `Topics`.
3. Add the bot as an admin with `can_manage_topics` and `can_post_messages`.
4. Copy `.env.example` to `.env` and fill in the real values.
5. Run:

```bash
npm run setup:bot
npm run bootstrap:forum
npm start
```

## What the bot does

- Accepts private user tips in DM.
- Routes them to the `User Submissions` topic.
- Localizes user-facing copy to Armenian, Russian, and English.
- Sets localized command lists in Telegram.

## Data files

- `data/forum-topics.json`: created after forum bootstrap.
- `data/user-preferences.json`: lightweight user language overrides.

## Notes

- If you want truly hidden intake, use a second private editorial supergroup for `User Submissions`.
- The public site should link to the public discussion/forum, not to the private intake.
