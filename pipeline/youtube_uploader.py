"""
youtube_uploader.py — Stage 11: YouTube Auto-Upload

Uploads the final video to YouTube using the YouTube Data API v3:
  1. Authenticate with OAuth2 (token.json cached after first login)
  2. Upload the video file with full metadata from Stage 10
  3. Set the custom thumbnail (thumbnail_16x9_text.png)
  4. Upload the SRT subtitle file
  5. Return the live YouTube URL

FIRST-TIME SETUP (one time only):
  1. Go to console.cloud.google.com → New Project
  2. Enable YouTube Data API v3
  3. Create OAuth 2.0 credentials → Desktop App
  4. Download credentials.json → save to D:\\AI-Animation\\credentials.json
  5. pip install google-api-python-client google-auth-oauthlib
  6. Run Stage 11 — browser opens for Google login → saves token.json

QUOTA:
  YouTube Data API gives 10,000 units/day free.
  One full upload (video + thumbnail + subtitles) costs ~1,700 units.
  = ~5-6 free uploads per day on default quota.
  Apply for quota increase at console.cloud.google.com if you need more.

Cost: $0.00 (YouTube API is free)
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from pipeline.models import RefinedScript

# Optional import — only needed at runtime
try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
#  CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

CREDENTIALS_FILE = "credentials.json"   # Download from Google Cloud Console
TOKEN_FILE       = "token.json"          # Auto-created after first login

YOUTUBE_CATEGORY_KIDS = "27"            # Education (best for kids content)
YOUTUBE_CATEGORY_ENTERTAINMENT = "24"  # Entertainment


# ─────────────────────────────────────────────────────────────────────────────
#  YOUTUBE UPLOADER
# ─────────────────────────────────────────────────────────────────────────────

class YouTubeUploader:
    """
    Uploads a completed video to YouTube with full metadata, thumbnail, and subtitles.

    Example:
        from pipeline.scene_refiner import SceneRefiner
        from pipeline.metadata_optimizer import MetadataOptimizer
        from pipeline.youtube_uploader import YouTubeUploader

        refined = SceneRefiner.load_refined("timmys-big-ship-adventure")
        meta    = MetadataOptimizer.load_metadata("timmys-big-ship-adventure")

        uploader = YouTubeUploader()
        url = uploader.upload(refined, meta)
        print(url)  # https://youtube.com/shorts/VIDEO_ID
    """

    def __init__(self):
        if not GOOGLE_AVAILABLE:
            raise ImportError(
                "Google API libraries not installed.\n"
                "Run: pip install google-api-python-client google-auth-oauthlib"
            )
        self.youtube = self._authenticate()

    def _authenticate(self):
        """
        Authenticate with YouTube via OAuth2.
        First run: opens browser for Google login → saves token.json
        Subsequent runs: loads token.json silently (no browser needed)
        """
        creds = None
        token_path = Path(TOKEN_FILE)
        creds_path = Path(CREDENTIALS_FILE)

        if not creds_path.exists():
            raise FileNotFoundError(
                f"credentials.json not found at {creds_path.absolute()}\n"
                "Steps:\n"
                "  1. Go to console.cloud.google.com → New Project\n"
                "  2. Enable YouTube Data API v3\n"
                "  3. Create OAuth 2.0 credentials → Desktop App\n"
                "  4. Download credentials.json to your project root"
            )

        # Load cached token if it exists
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

        # If credentials are missing or expired, re-authenticate
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                print("  Auth    : refreshing expired token...")
                creds.refresh(Request())
            else:
                print("  Auth    : opening browser for Google login...")
                flow = InstalledAppFlow.from_client_secrets_file(
                    CREDENTIALS_FILE, SCOPES
                )
                creds = flow.run_local_server(port=0)
                print("  Auth    : login successful")

            # Save token for future runs
            token_path.write_text(creds.to_json())
            print(f"  Auth    : token saved to {token_path}")

        return build("youtube", "v3", credentials=creds)

    def _get_video_path(self, slug: str) -> Path:
        path = Path(config.FINAL_DIR) / slug / f"{slug}_final.mp4"
        if not path.exists():
            raise FileNotFoundError(
                f"Final video not found: {path}\n"
                "Run Stage 8 first to render the video."
            )
        return path

    def _get_thumbnail_path(self, slug: str) -> Path:
        # Try _text version first (with title overlay), fall back to plain
        for name in ["thumbnail_16x9_text.png", "thumbnail_16x9.png"]:
            path = Path(config.OUTPUT_DIR) / "thumbnails" / slug / name
            if path.exists():
                return path
        raise FileNotFoundError(
            f"Thumbnail not found for slug: {slug}\n"
            "Run Stage 9 first to generate thumbnails."
        )

    def _get_srt_path(self, slug: str) -> Path:
        path = Path(config.SUBTITLES_DIR) / slug / f"{slug}.srt"
        if not path.exists():
            raise FileNotFoundError(
                f"SRT file not found: {path}\n"
                "Run Stage 7 first to generate subtitles."
            )
        return path

    def _build_video_body(
        self,
        refined: RefinedScript,
        meta: dict,
        privacy: str = "public",
    ) -> dict:
        """Build the video resource body for the YouTube API."""

        title = meta.get("title_primary", refined.title)
        description = meta.get("description_full", refined.youtube_description)
        tags = meta.get("tags", refined.youtube_tags)

        # Ensure Music credit is in description
        if "Bensound" not in description:
            description += "\n\nMusic by Bensound.com"

        return {
            "snippet": {
                "title": title[:100],           # YouTube max 100 chars
                "description": description[:5000],  # YouTube max 5000 chars
                "tags": tags[:500],             # YouTube max 500 chars total
                "categoryId": meta.get("category_id", YOUTUBE_CATEGORY_KIDS),
                "defaultLanguage": meta.get("language", "en"),
                "defaultAudioLanguage": "en",
            },
            "status": {
                "privacyStatus": privacy,
                "madeForKids": meta.get("made_for_kids", True),
                "selfDeclaredMadeForKids": meta.get("made_for_kids", True),
            },
        }

    def _upload_video(self, video_path: Path, body: dict) -> str:
        """Upload the video file. Returns the YouTube video ID."""
        size_mb = video_path.stat().st_size / 1_000_000
        print(f"  Video    : uploading {video_path.name} ({size_mb:.1f}MB)...", end="", flush=True)

        media = MediaFileUpload(
            str(video_path),
            mimetype="video/mp4",
            resumable=True,        # Resumable upload — safe for large files
            chunksize=5 * 1024 * 1024,  # 5MB chunks
        )

        request = self.youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = None
        t = time.time()
        while response is None:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                print(f"\r  Video    : uploading... {pct}%", end="", flush=True)

        elapsed = time.time() - t
        video_id = response["id"]
        print(f"\r  Video    : uploaded ✓ ({elapsed:.0f}s) → id: {video_id}")
        return video_id

    def _set_thumbnail(self, video_id: str, thumb_path: Path) -> bool:
        """Set the custom thumbnail for the video."""
        print(f"  Thumbnail: uploading {thumb_path.name}...", end="", flush=True)
        try:
            self.youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(thumb_path), mimetype="image/png"),
            ).execute()
            print(" ✓")
            return True
        except Exception as e:
            print(f" failed: {e}")
            return False

    def _upload_subtitles(self, video_id: str, srt_path: Path) -> bool:
        """Upload the SRT subtitle file."""
        print(f"  Subtitles: uploading {srt_path.name}...", end="", flush=True)
        try:
            self.youtube.captions().insert(
                part="snippet",
                body={
                    "snippet": {
                        "videoId": video_id,
                        "language": "en",
                        "name": "English",
                        "isDraft": False,
                    }
                },
                media_body=MediaFileUpload(str(srt_path), mimetype="application/octet-stream"),
            ).execute()
            print(" ✓")
            return True
        except Exception as e:
            print(f" failed: {e}")
            return False

    def _save_result(self, slug: str, video_id: str, url: str, meta: dict) -> Path:
        """Save the upload result for reference."""
        result = {
            "slug":     slug,
            "video_id": video_id,
            "url":      url,
            "title":    meta.get("title_primary", ""),
            "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        out_dir = Path(config.OUTPUT_DIR) / "metadata" / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        result_path = out_dir / "upload_result.json"
        result_path.write_text(json.dumps(result, indent=2))
        return result_path

    def upload(
        self,
        refined: RefinedScript,
        meta: dict,
        privacy: str = "public",
        upload_thumbnail: bool = True,
        upload_subtitles: bool = True,
    ) -> str:
        """
        Upload everything to YouTube.

        Args:
            refined:           RefinedScript from Stage 2
            meta:              Metadata dict from Stage 10
            privacy:           "public", "unlisted", or "private"
            upload_thumbnail:  Upload custom thumbnail (True recommended)
            upload_subtitles:  Upload SRT captions (True recommended for SEO)

        Returns:
            YouTube video URL string
        """
        slug = refined.slug

        print(f"\n{'='*60}")
        print(f"  Stage 11: YouTube Upload — '{refined.title}'")
        print(f"{'='*60}")
        print(f"  Privacy  : {privacy}")
        print(f"  Title    : {meta.get('title_primary', refined.title)}")
        print()

        # Locate files
        video_path = self._get_video_path(slug)
        thumb_path = self._get_thumbnail_path(slug) if upload_thumbnail else None
        srt_path   = self._get_srt_path(slug) if upload_subtitles else None

        # Build metadata body
        body = self._build_video_body(refined, meta, privacy)

        # Upload video
        video_id = self._upload_video(video_path, body)
        url = f"https://www.youtube.com/watch?v={video_id}"
        shorts_url = f"https://youtube.com/shorts/{video_id}"

        # Set thumbnail
        if thumb_path:
            self._set_thumbnail(video_id, thumb_path)

        # Upload subtitles
        if srt_path:
            self._upload_subtitles(video_id, srt_path)

        # Save result
        result_path = self._save_result(slug, video_id, url, meta)

        print()
        print(f"{'─'*60}")
        print(f"  ✅  VIDEO LIVE!")
        print(f"  Standard : {url}")
        print(f"  Shorts   : {shorts_url}")
        print(f"  Result   : {result_path}")
        print(f"{'─'*60}")
        print()
        print(f"  NEXT STEPS:")
        print(f"  1. Add to playlist: {meta.get('playlist_suggestion', 'Kids Stories')}")
        print(f"  2. Best next upload: {meta.get('best_upload_time', {}).get('day', 'Saturday')} "
              f"at {meta.get('best_upload_time', {}).get('time_utc', '07:00')} UTC")
        print(f"  3. A/B test thumbnail text options from Stage 10 metadata")
        print(f"{'─'*60}")

        return url