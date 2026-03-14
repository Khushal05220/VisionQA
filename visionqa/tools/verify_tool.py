"""
Verification Tool for VisionQA
Visual verification of UI states using Gemini vision.
Wraps Gemini tool with test-specific verification logic.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from visionqa.tools.gemini_tool import get_gemini_tool
from visionqa.tools.screenshot_tool import get_screenshot_tool

logger = logging.getLogger("visionqa.tools.verify")


class VerifyTool:
    """
    Provides test verification capabilities using visual AI.
    Compares actual screen state against expected outcomes.
    """

    def __init__(self):
        self._gemini = get_gemini_tool()
        self._screenshot = get_screenshot_tool()

    async def verify_screen(
        self, page, expected_state: str
    ) -> dict[str, Any]:
        """
        Verify the current screen matches an expected state.

        Args:
            page: Playwright page object.
            expected_state: Description of what the screen should show.

        Returns:
            Verification result with pass/fail and details.
        """
        # Take screenshot for verification
        screenshot_b64 = await self._screenshot.take_screenshot_base64(page)
        if not screenshot_b64:
            return {
                "status": "error",
                "passed": False,
                "error": "Failed to capture screenshot for verification",
            }

        # Use Gemini to verify
        result = await self._gemini.verify_screen(screenshot_b64, expected_state)

        verification_result = {
            "status": "success",
            "passed": result.get("matches", False),
            "confidence": result.get("confidence", 0.0),
            "expected": expected_state,
            "actual": result.get("actual_state", ""),
            "explanation": result.get("explanation", ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            f"Verification: {'PASS' if verification_result['passed'] else 'FAIL'} "
            f"(confidence: {verification_result['confidence']:.2f}) - {expected_state}"
        )

        return verification_result

    async def verify_element_exists(
        self, page, element_description: str
    ) -> dict[str, Any]:
        """
        Verify that a specific UI element exists on the page.

        Args:
            page: Playwright page object.
            element_description: Description of the element to find.

        Returns:
            Verification result with element location if found.
        """
        screenshot_b64 = await self._screenshot.take_screenshot_base64(page)
        if not screenshot_b64:
            return {
                "status": "error",
                "found": False,
                "error": "Failed to capture screenshot",
            }

        result = await self._gemini.find_element(screenshot_b64, element_description)

        return {
            "status": "success",
            "found": result.get("found", False),
            "x": result.get("x", 0),
            "y": result.get("y", 0),
            "description": result.get("description", ""),
            "element_searched": element_description,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def verify_page_loaded(self, page, expected_title: str = "") -> dict[str, Any]:
        """
        Verify that a page has loaded correctly.

        Args:
            page: Playwright page object.
            expected_title: Expected page title (optional).

        Returns:
            Verification result.
        """
        try:
            title = await page.title()
            url = page.url

            if expected_title:
                title_match = expected_title.lower() in title.lower()
            else:
                title_match = bool(title)

            # Visual verification
            screenshot_b64 = await self._screenshot.take_screenshot_base64(page)
            visual_check = await self._gemini.verify_screen(
                screenshot_b64,
                "The page has loaded completely and shows content (not a blank page or error page)"
            )

            return {
                "status": "success",
                "passed": title_match and visual_check.get("matches", False),
                "title": title,
                "url": url,
                "title_match": title_match,
                "visual_check": visual_check.get("matches", False),
                "explanation": visual_check.get("explanation", ""),
            }

        except Exception as e:
            return {"status": "error", "passed": False, "error": str(e)}

    async def compare_states(
        self, page, before_b64: str, expected_change: str
    ) -> dict[str, Any]:
        """
        Compare a before screenshot with the current state.

        Args:
            page: Playwright page object.
            before_b64: Base64 of the screenshot before an action.
            expected_change: Description of the expected change.

        Returns:
            Comparison result.
        """
        after_b64 = await self._screenshot.take_screenshot_base64(page)
        if not after_b64:
            return {"status": "error", "error": "Failed to capture current screenshot"}

        result = await self._gemini.verify_screen(
            after_b64,
            f"After an interaction, the page should show: {expected_change}"
        )

        return {
            "status": "success",
            "change_detected": result.get("matches", False),
            "expected_change": expected_change,
            "actual_state": result.get("actual_state", ""),
            "explanation": result.get("explanation", ""),
        }


# Global instance
_verify_tool: VerifyTool | None = None


def get_verify_tool() -> VerifyTool:
    """Get or create the global verify tool."""
    global _verify_tool
    if _verify_tool is None:
        _verify_tool = VerifyTool()
    return _verify_tool
