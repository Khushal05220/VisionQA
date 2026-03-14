"""
VisionQA Configuration Management
Centralized configuration using Pydantic settings for type safety and validation.
"""

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

# Find .env file relative to visionqa package root
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PACKAGE_ROOT / ".env"

# Pre-load .env so keys are available even before pydantic reads them
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE, override=True)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # --- Google Cloud ---
    google_api_key: str = Field(default="", description="Google API key for Gemini")
    google_cloud_project: str = Field(default="", description="GCP project ID")
    google_cloud_location: str = Field(default="us-central1", description="GCP region")

    # --- Gemini Model ---
    gemini_model: str = Field(
        default="gemini-2.0-flash",
        description="Gemini model to use for multimodal analysis",
    )
    gemini_vision_model: str = Field(
        default="gemini-2.0-flash",
        description="Gemini model for vision/screenshot analysis",
    )

    # --- Firestore ---
    firestore_database: str = Field(
        default="(default)", description="Firestore database name"
    )
    test_cases_collection: str = Field(
        default="test_cases", description="Firestore collection for test cases"
    )
    test_results_collection: str = Field(
        default="test_results", description="Firestore collection for test results"
    )
    test_plans_collection: str = Field(
        default="test_plans", description="Firestore collection for test plans"
    )

    # --- Cloud Storage ---
    gcs_bucket: str = Field(
        default="visionqa-screenshots", description="GCS bucket for screenshots"
    )
    gcs_screenshot_prefix: str = Field(
        default="screenshots/", description="Prefix path for screenshots in GCS"
    )

    # --- Playwright ---
    browser_headless: bool = Field(
        default=False, description="Run browser in headless mode"
    )
    browser_slow_mo: int = Field(
        default=100, description="Slow motion delay for browser actions (ms)"
    )
    browser_viewport_width: int = Field(
        default=1280, description="Browser viewport width"
    )
    browser_viewport_height: int = Field(
        default=720, description="Browser viewport height"
    )
    screenshot_dir: str = Field(
        default=str(_PACKAGE_ROOT / "screenshots"), description="Local absolute directory for screenshots"
    )

    # --- Server ---
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, description="Server port")
    debug: bool = Field(default=True, description="Debug mode")
    cors_origins: list[str] = Field(
        default=["*"], description="Allowed CORS origins"
    )

    # --- WebSocket ---
    ws_heartbeat_interval: int = Field(
        default=30, description="WebSocket heartbeat interval in seconds"
    )

    # --- Speech ---
    speech_language: str = Field(
        default="en-US", description="Default speech recognition language"
    )

    model_config = {
        "env_file": str(_ENV_FILE),
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()


# Ensure screenshot directory exists
def ensure_dirs():
    """Create required directories if they don't exist."""
    settings = get_settings()
    Path(settings.screenshot_dir).mkdir(parents=True, exist_ok=True)
