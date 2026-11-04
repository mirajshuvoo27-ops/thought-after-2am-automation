# Thought After 2AM - automated Shorts

Two Shorts a day, fully automatic: Claude writes the script, the engine renders it (animated, no characters,
English narration, centered subtitles), and YouTube publishes it at the scheduled time.

| Slot    | Workflow starts (UTC) | Starts (Bangladesh) | Publishes (UTC) | Publishes (Bangladesh) |
|---------|-----------------------|---------------------|-----------------|------------------------|
| Morning | 00:00                 | 06:00               | 01:00           | **07:00**              |
| Evening | 14:00                 | 20:00               | 15:00           | **21:00**              |

## How it works
1. `generate_script.py` calls the Anthropic API and writes `video_morning.json` or `video_evening.json`.
   It uses the vetted topics in `topics_bank.json` first, then lets Claude choose new topics under strict accuracy rules.
2. `main.py` renders the video and uploads it **private** with `status.publishAt`; YouTube makes it public at that time.
3. `content_history.json` records every published title/topic/script, so nothing is ever reused.
   The workflow commits this file after each successful upload.

## GitHub Secrets (Settings > Secrets and variables > Actions)
| Secret | Status |
|---|---|
| `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` | already set - unchanged |
| `ANTHROPIC_API_KEY` | **new - required** |
Optional repository *variable* (not secret): `ANTHROPIC_MODEL` to override the default model.

## First run
Actions > "Thought After 2AM - Scheduled Shorts" > Run workflow > pick a slot and tick **Dry run**.
That generates a script and renders the video (download it from the run's artifacts) without uploading anything.
Then run once without Dry run and confirm the video appears in YouTube Studio as *Scheduled*.

## Files
`main.py` render + orchestration | `generate_script.py` Anthropic script writer | `youtube_upload.py` scheduled upload |
`scheduling.py` publish-time logic | `history.py` repeat protection | `topics_bank.json` vetted topics |
`content_history.json` published log | `requirements.txt` | `.github/workflows/main.yml`

## Notes
- Late runs: GitHub cron can start minutes late. If the slot has already passed when the upload begins, the video is scheduled
  5 minutes later instead of 24 hours later (logged as a warning).
- Already published a topic by hand? Add `{"title": "...", "topic": "<id from topics_bank.json>"}` to `content_history.json`.
- Subtitle placement: set `CENTER_SUBTITLE_IN_CARD = False` in `main.py` to restore the previous text position.
- If `main` is a protected branch, allow `github-actions[bot]` to push, or the history commit will only warn.
