# Thought After 2AM — automated YouTube Shorts

The pipeline creates vertical psychology, brain-fact, and science Shorts, then uploads them publicly to YouTube.

## Publishing schedule

GitHub Actions runs at these Bangladesh times (UTC cron):

| Slot | Cron (UTC) | Bangladesh time |
|---|---:|---:|
| Morning | 01:00 | 07:00 |
| Evening | 15:00 | 21:00 |

The workflow uploads videos as **Public immediately**. It does not schedule them privately for a later publish time. GitHub cron can start a few minutes late.

## How it works

1. `generate_script.py` selects the next unused, vetted topic from `topics_bank.json`.
2. The generator creates short narration scenes and validates the script.
3. `main.py` creates the vertical video with English narration, animated visuals, and subtitles.
4. `youtube_upload.py` uploads the finished video with Public visibility.
5. The workflow commits `content_history.json` so published topics are not reused.

The generator uses the local topic bank; it does not require an Anthropic API key.

## Required GitHub Actions secrets

- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `YOUTUBE_REFRESH_TOKEN`

Never put these values in repository files or share them in chat.

## Manual test

Open **Actions → Thought After 2AM - Scheduled Shorts → Run workflow**.

- Choose `morning` or `evening`.
- Turn **Dry run ON** to generate and render without uploading.
- Turn **Dry run OFF** only when you intend to publish publicly.

A dry run saves the rendered MP4 as a workflow artifact. Review it before using a real upload.

## Main files

- `generate_script.py` — topic selection, narration splitting, and script validation
- `topics_bank.json` — vetted topics, facts, sources, and cautions
- `main.py` — narration, animation, rendering, and upload orchestration
- `youtube_upload.py` — YouTube API upload and public-visibility verification
- `history.py` — duplicate prevention and history storage
- `content_history.json` — record of published videos
- `.github/workflows/main.yml` — daily schedule and automation steps

## Reliability notes

- Unit tests run before each script is generated.
- Long fact sentences are split into caption-sized chunks rather than failing the whole run.
- If the vetted topic bank is exhausted, the generator stops safely rather than inventing research claims.
- If a video uploads but the history write fails, check YouTube Studio before manually retrying to avoid publishing a duplicate.
