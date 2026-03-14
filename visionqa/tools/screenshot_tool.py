"""
Screenshot Tool for VisionQA
Captures screenshots from the browser and stores them locally or in Cloud Storage.
"""

import base64
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("visionqa.tools.screenshot")


class ScreenshotTool:
    """
    Captures and manages screenshots from the Playwright browser.
    Supports local storage and Google Cloud Storage upload.
    """

    def __init__(self, screenshot_dir: str = "screenshots", gcs_bucket: str = ""):
        self._screenshot_dir = Path(screenshot_dir)
        self._screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._gcs_bucket = gcs_bucket
        self._gcs_client = None

        if gcs_bucket:
            try:
                from google.cloud import storage
                self._gcs_client = storage.Client()
                logger.info(f"Cloud Storage initialized for bucket: {gcs_bucket}")
            except Exception as e:
                logger.warning(f"Cloud Storage not available: {e}")

    async def take_screenshot(
        self,
        page,
        name: str = "",
        full_page: bool = False,
    ) -> dict[str, Any]:
        """
        Take a screenshot of the current page.

        Args:
            page: Playwright page object.
            name: Optional name for the screenshot.
            full_page: Whether to capture the full page or just the viewport.

        Returns:
            dict with file path, base64 data, and optional GCS URL.
        """
        try:
            if not name:
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                name = f"screenshot_{timestamp}_{uuid.uuid4().hex[:8]}"

            file_path = self._screenshot_dir / f"{name}.png"

            # Capture screenshot
            screenshot_bytes = await page.screenshot(
                path=str(file_path),
                full_page=full_page,
                type="png",
            )

            # Encode to base64 for API/WebSocket transmission
            b64_data = base64.b64encode(screenshot_bytes).decode("utf-8")

            result = {
                "status": "success",
                "file_path": str(file_path),
                "base64": b64_data,
                "name": name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            # Upload to Cloud Storage if available
            if self._gcs_client and self._gcs_bucket:
                gcs_url = await self._upload_to_gcs(file_path, name)
                if gcs_url:
                    result["gcs_url"] = gcs_url

            logger.info(f"Screenshot captured: {file_path}")
            return result

        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return {"status": "error", "error": str(e)}

    async def take_screenshot_base64(self, page) -> str:
        """
        Take a screenshot and return only the base64 encoded data.
        Used primarily for sending to Gemini for analysis.

        Args:
            page: Playwright page object.

        Returns:
            Base64 encoded screenshot string.
        """
        try:
            screenshot_bytes = await page.screenshot(type="png")
            return base64.b64encode(screenshot_bytes).decode("utf-8")
        except Exception as e:
            logger.error(f"Screenshot base64 failed: {e}")
            return ""

    async def _upload_to_gcs(self, file_path: Path, name: str) -> str | None:
        """Upload screenshot to Google Cloud Storage."""
        try:
            bucket = self._gcs_client.bucket(self._gcs_bucket)
            blob_name = f"screenshots/{name}.png"
            blob = bucket.blob(blob_name)
            blob.upload_from_filename(str(file_path), content_type="image/png")
            blob.make_public()
            logger.info(f"Uploaded screenshot to GCS: {blob.public_url}")
            return blob.public_url
        except Exception as e:
            logger.warning(f"GCS upload failed: {e}")
            return None

    def get_screenshot_path(self, name: str) -> Path | None:
        """Get the local path of a screenshot by name."""
        file_path = self._screenshot_dir / f"{name}.png"
        return file_path if file_path.exists() else None

    def list_screenshots(self) -> list[dict]:
        """List all local screenshots."""
        screenshots = []
        for f in sorted(self._screenshot_dir.glob("*.png"), reverse=True):
            screenshots.append({
                "name": f.stem,
                "path": str(f),
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(
                    f.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
            })
        return screenshots


# Global instance
_screenshot_tool: ScreenshotTool | None = None


def get_screenshot_tool() -> ScreenshotTool:
    """Get or create the global screenshot tool."""
    global _screenshot_tool
    if _screenshot_tool is None:
        from visionqa.backend.config import get_settings
        settings = get_settings()
        _screenshot_tool = ScreenshotTool(
            screenshot_dir=settings.screenshot_dir,
            gcs_bucket=settings.gcs_bucket,
        )
    return _screenshot_tool
