"""Upload a video to YouTube as PRIVATE for manual scheduling in YouTube Studio.

Uses the same three OAuth secrets as before: YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN.
"""
import json
import os
import random
import time

import httplib2

RETRIABLE_STATUS = {500, 502, 503, 504}
MAX_RETRIES = 6
CHUNK_SIZE = 4 * 1024 * 1024  # must be a multiple of 256 KiB


def log(msg):
    print(f"[upload] {msg}", flush=True)


def _credentials():
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    missing = [k for k in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN") if not os.environ.get(k, "").strip()]
    if missing:
        raise RuntimeError("Missing GitHub Secret(s): " + ", ".join(missing))
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"].strip(),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YOUTUBE_CLIENT_ID"].strip(),
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"].strip(),
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    try:
        creds.refresh(Request())
    except RefreshError as e:
        raise RuntimeError(
            "Google refused the YouTube refresh token. It may be expired or revoked. If your OAuth consent screen is in 'Testing' "
            "status, Google expires refresh tokens after 7 days; publish the app or create a new token, then update YOUTUBE_REFRESH_TOKEN. "
            f"Details: {e}") from e
    log("OAuth token refreshed")
    return creds


def build_body(data, publish_at=None):
    """The videos.insert request body. Video remains private until manually scheduled."""
    return {
        "snippet": {
            "title": str(data["title"])[:100],
            "description": data.get("description", ""),
            "tags": data.get("tags", []),
            "categoryId": "27",  # Education
        },
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": False,
        },
    }


def upload_private(path, data):
    """Upload `path` as private. Returns the YouTube video id."""
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    creds = _credentials()
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    body = build_body(data)
    size_mb = os.path.getsize(path) / 1e6
    log(f"uploading {path} ({size_mb:.1f} MB) as PRIVATE for manual scheduling")
    media = MediaFileUpload(str(path), mimetype="video/mp4", chunksize=CHUNK_SIZE, resumable=True)
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)

    response, retries, last_pct = None, 0, -1
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                if pct != last_pct:
                    log(f"upload progress {pct}%")
                    last_pct = pct
        except HttpError as e:
            code = getattr(e.resp, "status", None)
            if code in RETRIABLE_STATUS and retries < MAX_RETRIES:
                retries += 1
                _backoff(retries, f"HTTP {code}")
                continue
            raise RuntimeError(_explain_http_error(e)) from e
        except (httplib2.HttpLib2Error, ConnectionError, TimeoutError, OSError) as e:
            if retries < MAX_RETRIES:
                retries += 1
                _backoff(retries, f"{type(e).__name__}: {e}")
                continue
            raise RuntimeError(f"Network error during upload after {MAX_RETRIES} retries: {e}") from e

    video_id = response.get("id")
    if not video_id:
        raise RuntimeError(f"YouTube returned no video id: {json.dumps(response)[:300]}")
    _verify(response)
    return video_id


def _backoff(attempt, reason):
    delay = min(60, 2 ** attempt) + random.random()
    log(f"retryable error ({reason}); retry {attempt}/{MAX_RETRIES} in {delay:.0f}s")
    time.sleep(delay)


def _explain_http_error(e):
    text = ""
    try:
        text = e.content.decode("utf-8", "replace") if getattr(e, "content", None) else ""
    except Exception:  # noqa: BLE001
        pass
    code = getattr(e.resp, "status", "?")
    hint = ""
    if "quotaExceeded" in text or "uploadLimitExceeded" in text:
        hint = " The daily YouTube API quota or upload limit is used up. Quota resets at midnight Pacific time."
    elif code == 401:
        hint = " The OAuth token was rejected; check the three YOUTUBE_* secrets."
    elif code == 403:
        hint = " The account may lack permission, the YouTube Data API may be disabled in your Google Cloud project, or the quota is exhausted."
    elif "invalidPublishAt" in text:
        hint = " YouTube rejected publishAt; it must be a future time and the video must be private."
    return f"YouTube API error HTTP {code}.{hint} Response: {text[:500]}"


def _verify(response):
    """Confirm the uploaded video is private."""
    status = response.get("status", {}) or {}
    privacy = status.get("privacyStatus")
    log(f"YouTube reports privacyStatus={privacy}")
    if privacy != "private":
        raise RuntimeError("YouTube did not confirm private visibility. Check the video in YouTube Studio.")
    log("private upload confirmed; schedule manually in YouTube Studio")
