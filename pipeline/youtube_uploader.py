"""
youtube_uploader.py — Stage 10: YouTube Upload

Uploads the finished video and thumbnail to YouTube using the
YouTube Data API v3 (OAuth 2.0).

SETUP (one-time):
    1. Go to https://console.cloud.google.com/
    2. Create a project → Enable "YouTube Data API v3"
    3. Create OAuth 2.0 credentials (Desktop App) → Download as client_secrets.json
    4. Place client_secrets.json in the project root
    5. Run this stage once — it opens a browser for Google login
    6. Token is saved to output/youtube_token.json for future runs (auto-refresh)

Usage:
    python pipeline/youtube_uploader.py timmys-big-ship-adventure
    python pipeline/youtube_uploader.py timmys-big-ship-adventure --privacy unlisted
    python pipeline/youtube_uploader.py timmys-big-ship-adventure --privacy public --shorts

Output:
    Video URL printed to console
    output/final/<slug>/upload_result.json  — video ID, URL, upload timestamp
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from pipeline.models import RefinedScript
from pipeline.scene_refiner import SceneRefiner

# ── Google API imports (installed via requirements.txt) ───────────────────────
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
except ImportError as exc:
    raise ImportError(
        "Google API libraries not found.\n"
        "Run: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
    ) from exc


# ─────────────────────────────────────────────────────────────────────────────
#  CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

TOKEN_PATH          = Path(config.OUTPUT_DIR) / "youtube_token.json"
CLIENT_SECRETS_PATH = Path(__file__).resolve().parent.parent / "client_secrets.json"

# YouTube video category IDs
CATEGORY_FILM_ANIMATION = "1"    # Film & Animation — best for kids animated content
CATEGORY_EDUCATION      = "27"   # Education

# Resumable upload chunk size — 10 MB
CHUNK_SIZE = 10 * 1024 * 1024

# Retry settings for upload
MAX_UPLOAD_RETRIES = 5
RETRY_WAIT_SEC     = 5

# YouTube Shorts: video must be ≤ 60 seconds and ≤ 1080x1920 (already the case)
SHORTS_TITLE_SUFFIX  = " #Shorts"
SHORTS_HASHTAG_LINE  = "\n\n#Shorts #KidsVideo #AnimatedStories"


# ─────────────────────────────────────────────────────────────────────────────
#  AUTHENTICATION
# ─────────────────────────────────────────────────────────────────────────────

def get_authenticated_service():
    """
    Authenticate with YouTube Data API v3 using OAuth 2.0.

    - First run: opens browser for Google login, saves token.
    - Subsequent runs: loads and auto-refreshes saved token.

    Returns a YouTube API service resource.
    """
    if not CLIENT_SECRETS_PATH.exists():
        raise FileNotFoundError(
            f"client_secrets.json not found at: {CLIENT_SECRETS_PATH}\n\n"
            "SETUP STEPS:\n"
            "  1. Go to https://console.cloud.google.com/\n"
            "  2. Create a project → APIs & Services → Enable 'YouTube Data API v3'\n"
            "  3. Credentials → Create → OAuth client ID → Desktop App\n"
            "  4. Download JSON → rename to client_secrets.json\n"
            "  5. Place it in the project root (same folder as config.py)\n"
        )

    creds = None
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Load saved token if it exists
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    # Refresh or re-authenticate if needed
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("  Refreshing YouTube access token...")
            creds.refresh(Request())
        else:
            print("  Opening browser for YouTube authentication...")
            print("  (This only happens once — token is saved for future runs)")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CLIENT_SECRETS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Save token for next run
        TOKEN_PATH.write_text(creds.to_json())
        print(f"  Token saved → {TOKEN_PATH}")

    return build("youtube", "v3", credentials=creds)


# ─────────────────────────────────────────────────────────────────────────────
#  METADATA BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def build_video_metadata(
    refined: RefinedScript,
    privacy: str = "private",
    is_shorts: bool = False,
) -> dict:
    """
    Build the YouTube video snippet and status metadata from the RefinedScript.

    Args:
        refined:   The RefinedScript with title, description, tags, etc.
        privacy:   "private" | "unlisted" | "public"
        is_shorts: If True, appends #Shorts to title and description.

    Returns a dict with "snippet" and "status" keys for the YouTube API.
    """
    title = refined.title
    description = refined.youtube_description
    tags = list(refined.youtube_tags)

    if is_shorts:
        # YouTube Shorts: title must be ≤ 100 chars with suffix
        title_with_suffix = title + SHORTS_TITLE_SUFFIX
        if len(title_with_suffix) <= 100:
            title = title_with_suffix
        description = description + SHORTS_HASHTAG_LINE
        if "Shorts" not in tags:
            tags = ["Shorts", "KidsShorts"] + tags

    # YouTube title limit: 100 chars
    title = title[:100]

    # YouTube description limit: 5000 chars
    description = description[:5000]

    # YouTube tags: each ≤ 500 chars, total ≤ 500 chars combined
    safe_tags = []
    total_len = 0
    for tag in tags:
        tag = tag[:500]
        if total_len + len(tag) + 1 <= 500:
            safe_tags.append(tag)
            total_len += len(tag) + 1

    return {
        "snippet": {
            "title":       title,
            "description": description,
            "tags":        safe_tags,
            "categoryId":  CATEGORY_FILM_ANIMATION,
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus":           privacy,
            "selfDeclaredMadeForKids": True,   # COPPA compliance — kids content
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
#  VIDEO UPLOAD
# ─────────────────────────────────────────────────────────────────────────────

def upload_video(
    youtube,
    video_path: Path,
    metadata: dict,
) -> str:
    """
    Upload the video file to YouTube using chunked resumable upload.

    Shows a real-time progress bar during upload.
    Retries on transient network errors.

    Args:
        youtube:    Authenticated YouTube API service.
        video_path: Path to the final MP4 file.
        metadata:   Dict with "snippet" and "status" keys.

    Returns the YouTube video ID (e.g. "dQw4w9WgXcQ").
    """
    file_size = video_path.stat().st_size
    file_size_mb = round(file_size / 1024 / 1024, 1)

    print(f"  Uploading: {video_path.name}  ({file_size_mb} MB)")

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        chunksize=CHUNK_SIZE,
        resumable=True,
    )

    request = youtube.videos().insert(
        part=",".join(metadata.keys()),
        body=metadata,
        media_body=media,
    )

    response = None
    retries  = 0
    start    = time.time()

    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                pct     = int(status.progress() * 100)
                elapsed = round(time.time() - start, 1)
                bar     = "█" * (pct // 5) + "░" * (20 - pct // 5)
                print(f"\r  [{bar}] {pct:3d}%  {elapsed}s", end="", flush=True)
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504) and retries < MAX_UPLOAD_RETRIES:
                retries += 1
                print(f"\n  ⚠️  Server error {e.resp.status} — retry {retries}/{MAX_UPLOAD_RETRIES}")
                time.sleep(RETRY_WAIT_SEC * retries)
            else:
                raise
        except Exception as e:
            if retries < MAX_UPLOAD_RETRIES:
                retries += 1
                print(f"\n  ⚠️  Upload error: {e} — retry {retries}/{MAX_UPLOAD_RETRIES}")
                time.sleep(RETRY_WAIT_SEC * retries)
            else:
                raise

    elapsed = round(time.time() - start, 1)
    print(f"\r  [{'█'*20}] 100%  {elapsed}s  ✅                    ")

    video_id = response.get("id")
    if not video_id:
        raise RuntimeError(f"Upload succeeded but no video ID returned: {response}")

    return video_id


# ─────────────────────────────────────────────────────────────────────────────
#  THUMBNAIL UPLOAD
# ─────────────────────────────────────────────────────────────────────────────

def upload_thumbnail(youtube, video_id: str, thumbnail_path: Path) -> bool:
    """
    Upload a custom thumbnail to a YouTube video.

    Requires the channel to have verified phone number
    (YouTube requirement for custom thumbnails).

    Args:
        youtube:        Authenticated YouTube API service.
        video_id:       YouTube video ID returned after video upload.
        thumbnail_path: Path to the 1280x720 PNG thumbnail.

    Returns True on success, False on failure.
    """
    if not thumbnail_path.exists():
        print(f"  ⚠️  Thumbnail not found: {thumbnail_path}")
        return False

    size_kb = thumbnail_path.stat().st_size // 1024
    print(f"  Uploading thumbnail: {thumbnail_path.name}  ({size_kb} KB)")

    try:
        media = MediaFileUpload(
            str(thumbnail_path),
            mimetype="image/png",
        )
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=media,
        ).execute()
        print("  ✅  Thumbnail uploaded")
        return True
    except HttpError as e:
        # Error 403 = channel not verified for custom thumbnails
        if e.resp.status == 403:
            print(
                "  ⚠️  Thumbnail upload failed — channel needs phone verification.\n"
                "      Go to https://www.youtube.com/verify to enable custom thumbnails."
            )
        else:
            print(f"  ⚠️  Thumbnail upload failed: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
#  SAVE UPLOAD RESULT
# ─────────────────────────────────────────────────────────────────────────────

def save_upload_result(
    slug: str,
    video_id: str,
    privacy: str,
    thumbnail_ok: bool,
    metadata: dict,
) -> Path:
    """Save upload details to output/final/<slug>/upload_result.json."""
    out_dir = Path(config.FINAL_DIR) / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "video_id":       video_id,
        "video_url":      f"https://www.youtube.com/watch?v={video_id}",
        "shorts_url":     f"https://www.youtube.com/shorts/{video_id}",
        "privacy":        privacy,
        "thumbnail_uploaded": thumbnail_ok,
        "title":          metadata["snippet"]["title"],
        "uploaded_at":    time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
    }

    result_path = out_dir / "upload_result.json"
    result_path.write_text(json.dumps(result, indent=2))
    return result_path


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN UPLOADER CLASS
# ─────────────────────────────────────────────────────────────────────────────

class YouTubeUploader:
    """
    Stage 10: Upload the finished video to YouTube.

    Reads the pre-built youtube_metadata.json from Stage 9 (YouTubeMetadataBuilder).
    Handles authentication, video upload, thumbnail upload, and saves upload_result.json.

    Example:
        from pipeline.scene_refiner import SceneRefiner
        from pipeline.youtube_uploader import YouTubeUploader

        refined = SceneRefiner.load_refined("timmys-big-ship-adventure")
        uploader = YouTubeUploader()
        result = uploader.upload(refined)
        print(result["video_url"])
    """

    def upload(
        self,
        refined: RefinedScript,
        privacy: str = "private",
        is_shorts: bool = True,
    ) -> dict:
        """
        Upload the video to YouTube using metadata built by Stage 9.

        Args:
            refined:   The RefinedScript for this video.
            privacy:   Fallback privacy if no youtube_metadata.json found.
            is_shorts: Fallback Shorts flag if no youtube_metadata.json found.

        Returns dict with video_id, video_url, shorts_url.
        """
        print(f"\n{'='*62}")
        print(f"  Stage 10: YouTube Upload — '{refined.title}'")
        print(f"{'='*62}")

        # ── Load metadata from Stage 9 (preferred) ────────────────────────────
        try:
            from pipeline.youtube_metadata import YouTubeMetadataBuilder
            meta = YouTubeMetadataBuilder.load(refined.slug)
            print("  Metadata : loaded from youtube_metadata.json ✓")
            # Override privacy if caller specified something explicit
            if privacy != "private":
                meta["privacyStatus"] = privacy
        except FileNotFoundError:
            print("  ⚠️  youtube_metadata.json not found — building basic metadata.")
            print("      Run Stage 9 (YouTubeMetadataBuilder) for full SEO metadata.")
            meta = build_video_metadata(refined, privacy=privacy, is_shorts=is_shorts)
            # Normalise to flat structure for consistency below
            meta = {
                "title":       meta["snippet"]["title"],
                "description": meta["snippet"]["description"],
                "tags":        meta["snippet"]["tags"],
                "categoryId":  meta["snippet"]["categoryId"],
                "defaultLanguage": meta["snippet"]["defaultLanguage"],
                "privacyStatus":   meta["status"]["privacyStatus"],
                "madeForKids":     meta["status"]["selfDeclaredMadeForKids"],
                "pinned_comment":  None,
                "is_shorts":       is_shorts,
            }

        print(f"  Privacy  : {meta['privacyStatus']}")
        print(f"  Shorts   : {'yes' if meta.get('is_shorts', is_shorts) else 'no'}")
        print()

        # ── Locate final video ────────────────────────────────────────────────
        video_path = Path(config.FINAL_DIR) / refined.slug / f"{refined.slug}_final.mp4"
        if not video_path.exists():
            raise FileNotFoundError(
                f"Final video not found: {video_path}\n"
                "Run Stage 6 (video render) first."
            )

        # ── Locate thumbnail ──────────────────────────────────────────────────
        thumb_dir  = Path(config.THUMBS_DIR) / refined.slug
        thumb_path = thumb_dir / "thumbnail_16x9_text.png"
        if not thumb_path.exists():
            thumb_path = thumb_dir / "thumbnail_16x9.png"
        if not thumb_path.exists():
            print("  ⚠️  No thumbnail found — skipping thumbnail upload.")
            print("      Run Stage 8 (thumbnail generation) to create one.")
            thumb_path = None

        # ── Authenticate ──────────────────────────────────────────────────────
        print("  Authenticating with YouTube...")
        youtube = get_authenticated_service()
        print("  ✅  Authenticated")
        print()

        # ── Build YouTube API body from flat meta dict ─────────────────────────
        api_body = {
            "snippet": {
                "title":           meta["title"],
                "description":     meta["description"],
                "tags":            meta["tags"],
                "categoryId":      meta.get("categoryId", CATEGORY_FILM_ANIMATION),
                "defaultLanguage": meta.get("defaultLanguage", "en"),
            },
            "status": {
                "privacyStatus":           meta["privacyStatus"],
                "selfDeclaredMadeForKids": meta.get("madeForKids", True),
            },
        }

        print(f"  Title    : {api_body['snippet']['title']}")
        print(f"  Tags     : {len(api_body['snippet']['tags'])} tags")
        print(f"  Desc.    : {len(api_body['snippet']['description'])} chars")
        if meta.get("chapters"):
            print(f"  Chapters : {len(meta['chapters'])} chapter timestamps")
        print("  Kids     : Yes (COPPA compliant)")
        print()

        # ── Upload video ──────────────────────────────────────────────────────
        video_id   = upload_video(youtube, video_path, api_body)
        video_url  = f"https://www.youtube.com/watch?v={video_id}"
        shorts_url = f"https://www.youtube.com/shorts/{video_id}"
        print(f"\n  Video ID : {video_id}")
        print(f"  URL      : {video_url}")
        print()

        # ── Upload thumbnail ──────────────────────────────────────────────────
        thumbnail_ok = False
        if thumb_path:
            thumbnail_ok = upload_thumbnail(youtube, video_id, thumb_path)

        # ── Post pinned comment ───────────────────────────────────────────────
        pinned_comment = meta.get("pinned_comment")
        if pinned_comment:
            self._post_pinned_comment(youtube, video_id, pinned_comment)

        # ── Save result ───────────────────────────────────────────────────────
        result_path = save_upload_result(
            refined.slug, video_id, meta["privacyStatus"], thumbnail_ok, api_body
        )

        result = {
            "video_id":           video_id,
            "video_url":          video_url,
            "shorts_url":         shorts_url,
            "privacy":            meta["privacyStatus"],
            "thumbnail_uploaded": thumbnail_ok,
        }

        print()
        print(f"{'─'*62}")
        print("  ✅  Upload complete!")
        print(f"{'─'*62}")
        print(f"  Video URL  : {video_url}")
        print(f"  Shorts URL : {shorts_url}")
        print(f"  Privacy    : {meta['privacyStatus']}")
        if meta["privacyStatus"] == "private":
            print()
            print("  💡 Video is PRIVATE — review in YouTube Studio, then publish:")
            print(f"     https://studio.youtube.com/video/{video_id}/edit")
        print(f"  Result     : {result_path}")
        print(f"{'─'*62}")

        return result

    def _post_pinned_comment(self, youtube, video_id: str, comment_text: str):
        """Post the engagement comment and pin it to the top of the video."""
        try:
            resp = youtube.commentThreads().insert(
                part="snippet",
                body={
                    "snippet": {
                        "videoId": video_id,
                        "topLevelComment": {
                            "snippet": {"textOriginal": comment_text}
                        },
                    }
                },
            ).execute()
            comment_id = resp["snippet"]["topLevelComment"]["id"]

            # Pin the comment
            youtube.comments().setModerationStatus(
                id=comment_id,
                moderationStatus="published",
            ).execute()

            print("  ✅  Pinned comment posted")
        except Exception as e:
            # Non-fatal — upload already succeeded
            print(f"  ⚠️  Pinned comment failed (non-fatal): {e}")


# ─────────────────────────────────────────────────────────────────────────────
#  CLI ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Stage 10 — Upload finished video to YouTube"
    )
    parser.add_argument(
        "slug",
        help="Video slug (e.g. timmys-big-ship-adventure)",
    )
    parser.add_argument(
        "--privacy",
        choices=["private", "unlisted", "public"],
        default="private",
        help="YouTube privacy setting (default: private)",
    )
    parser.add_argument(
        "--shorts",
        action="store_true",
        default=True,
        help="Add #Shorts tag and suffix (default: True for 9:16 videos)",
    )
    parser.add_argument(
        "--no-shorts",
        dest="shorts",
        action="store_false",
        help="Disable Shorts tagging",
    )
    args = parser.parse_args()

    refined  = SceneRefiner.load_refined(args.slug)
    uploader = YouTubeUploader()
    result   = uploader.upload(refined, privacy=args.privacy, is_shorts=args.shorts)
    print(f"\n  Done: {result['video_url']}")


if __name__ == "__main__":
    main()
