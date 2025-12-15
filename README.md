# Odyssey Reddit Comment Scraper (r/churningmarketplace → Supabase)

Purpose: **data collection only**. This project collects all historical + ongoing comments from `r/churningmarketplace`, stores **raw comment JSON** in Supabase, and preserves **edit history** and **deletion status**. No dashboards, no analysis, no visualization.

## What this does

- **Initial scrape (manual, one-time)**:
  - Fetches **all threads/posts** in the subreddit (no hardcoded post IDs)
  - Fully expands each thread’s comment tree (all depths)
  - Inserts new comments and creates their first version

- **Scheduled scrape (twice/day via cron)**:
  - Re-fetches all threads
  - Inserts brand-new comments
  - For existing comments, compares current `body` vs latest stored version:
    - If changed: inserts a new version and marks old version as not-latest
    - If unchanged: does nothing
  - Marks comments as deleted when Reddit indicates deletion (never deletes rows)

## Supabase schema

Run the SQL in:

- `supabase/migrations/001_odyssey_schema.sql`

## Environment variables

Create `.env` (or set in Porter). If you want a template, copy `env.example` to `.env`:

- **Reddit**
  - `REDDIT_CLIENT_ID`
  - `REDDIT_CLIENT_SECRET`
  - `REDDIT_USER_AGENT` (recommended, e.g. `odyssey-scraper/1.0 by u/yourname`)

- **Supabase**
  - `SUPABASE_URL`
  - `SUPABASE_SERVICE_ROLE_KEY` (service role recommended for inserts/updates)

- **Config**
  - `SUBREDDIT=churningmarketplace` (default)

## Install & run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp env.example .env
python -m odyssey_scraper --run-type initial
python -m odyssey_scraper --run-type scheduled
```

## Porter / Cron

This repo includes a `Dockerfile`. Deploy it to Porter and configure two cron schedules that run:

- `python -m odyssey_scraper --run-type scheduled`

## Notes / Guarantees

- **Never deletes** from `odyssey_comments` or `odyssey_comment_versions`
- **Preserves version history** on edits
- **Preserves deletion status** without erasing last known body
- **Stops the run** after a second failed API attempt (single retry policy)


