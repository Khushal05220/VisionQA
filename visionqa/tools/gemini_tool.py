"""
Gemini Vision Tool for VisionQA
Uses Gemini multimodal capabilities to analyze screenshots,
identify UI elements, and determine coordinates for interaction.
"""

import base64
import json
import logging
import os
from typing import Any

from google import genai
from google.genai import types

logger = logging.getLogger("visionqa.tools.gemini")


class GeminiTool:
    """
    Multimodal Gemini client for UI analysis.
    Uses vision capabilities to understand screenshots and provide
    coordinate-based interaction instructions.
    """

    def __init__(self, api_key: str = "", model: str = "gemini-2.0-flash"):
        self._api_key = api_key or os.getenv("GOOGLE_API_KEY", "")
        self._model = model
        self._client = genai.Client(api_key=self._api_key)
        logger.info(f"Gemini tool initialized with model: {model}")

    async def analyze_ui(self, screenshot_b64: str, instruction: str = "") -> dict[str, Any]:
        """
        Analyze a screenshot using Gemini vision.

        Args:
            screenshot_b64: Base64 encoded screenshot image.
            instruction: Specific instruction for analysis.

        Returns:
            dict with analysis results including identified UI elements.
        """
        try:
            prompt = instruction or (
                "Analyze this webpage screenshot. Identify all interactive UI elements "
                "(buttons, links, input fields, dropdowns, etc.) with their approximate "
                "x, y coordinates and descriptions. Return the results as a JSON array of objects "
                "with keys: 'element', 'type', 'x', 'y', 'description'."
            )

            image_part = types.Part.from_bytes(
                data=base64.b64decode(screenshot_b64),
                mime_type="image/png",
            )

            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=[
                    types.Content(
                        parts=[
                            image_part,
                            types.Part.from_text(text=prompt),
                        ]
                    )
                ],
            )

            result_text = response.text
            logger.info(f"UI analysis complete. Response length: {len(result_text)}")

            return {
                "status": "success",
                "analysis": result_text,
                "model": self._model,
            }

        except Exception as e:
            logger.error(f"UI analysis failed: {e}")
            return {"status": "error", "error": str(e)}

    async def find_element(
        self, screenshot_b64: str, element_description: str
    ) -> dict[str, Any]:
        """
        Find the coordinates of a specific UI element in a screenshot.

        Args:
            screenshot_b64: Base64 encoded screenshot.
            element_description: Description of the element to find.

        Returns:
            dict with x, y coordinates of the element.
        """
        try:
            prompt = (
                f"Look at this webpage screenshot. Find the UI element that matches "
                f"this description: '{element_description}'. "
                f"Return ONLY a JSON object with keys 'x', 'y', 'found' (boolean), "
                f"and 'description'. The x, y values MUST be a single clickable point "
                f"located STRICTLY INSIDE the interactable area of the element (e.g., inside the white space "
                f"of the text box, or precisely on the button), normalized to a 0-1000 scale. "
                f"DO NOT return the center of a group (like a label + input); specifically target the interactable component. "
                f"Where (0,0) is top-left and (1000,1000) is bottom-right. "
                f"If not found, set found=false."
            )

            image_part = types.Part.from_bytes(
                data=base64.b64decode(screenshot_b64),
                mime_type="image/png",
            )

            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=[
                    types.Content(
                        parts=[
                            image_part,
                            types.Part.from_text(text=prompt),
                        ]
                    )
                ],
            )

            result_text = response.text.strip()
            # Try to parse JSON from response
            try:
                # Handle markdown-wrapped JSON
                if "```json" in result_text:
                    result_text = result_text.split("```json")[1].split("```")[0].strip()
                elif "```" in result_text:
                    result_text = result_text.split("```")[1].split("```")[0].strip()
                coords = json.loads(result_text)
                # Gemini returns 0-1000 spatial coordinates, convert back to viewport limits
                from visionqa.backend.config import get_settings
                settings = get_settings()
                
                norm_x = coords.get("x", 0)
                norm_y = coords.get("y", 0)
                actual_x = int((norm_x / 1000.0) * settings.browser_viewport_width) if norm_x else 0
                actual_y = int((norm_y / 1000.0) * settings.browser_viewport_height) if norm_y else 0

                return {
                    "status": "success",
                    "x": actual_x,
                    "y": actual_y,
                    "found": coords.get("found", False),
                    "description": coords.get("description", ""),
                }
            except json.JSONDecodeError:
                return {
                    "status": "success",
                    "raw_response": result_text,
                    "found": False,
                }

        except Exception as e:
            logger.error(f"Find element failed: {e}")
            return {"status": "error", "error": str(e)}

    async def generate_text(self, prompt: str) -> str:
        """
        Generate text using Gemini (non-vision).

        Args:
            prompt: Text prompt for generation.

        Returns:
            Generated text response.
        """
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model, contents=prompt
            )
            return response.text
        except Exception as e:
            logger.error(f"Text generation failed: {e}")
            return f"Error: {str(e)}"

    async def verify_screen(
        self, screenshot_b64: str, expected_state: str
    ) -> dict[str, Any]:
        """
        Verify if the screen matches an expected state.

        Args:
            screenshot_b64: Base64 encoded screenshot.
            expected_state: Description of the expected screen state.

        Returns:
            dict with verification result (pass/fail) and explanation.
        """
        try:
            prompt = (
                f"Look at this webpage screenshot and determine if it matches "
                f"this expected state: '{expected_state}'.\n\n"
                f"Return ONLY a JSON object with keys:\n"
                f"- 'matches': boolean (true if the screen matches the expected state)\n"
                f"- 'confidence': float (0.0 to 1.0)\n"
                f"- 'explanation': string (brief explanation of your assessment)\n"
                f"- 'actual_state': string (description of what the screen actually shows)"
            )

            image_part = types.Part.from_bytes(
                data=base64.b64decode(screenshot_b64),
                mime_type="image/png",
            )

            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=[
                    types.Content(
                        parts=[
                            image_part,
                            types.Part.from_text(text=prompt),
                        ]
                    )
                ],
            )

            result_text = response.text.strip()
            try:
                if "```json" in result_text:
                    result_text = result_text.split("```json")[1].split("```")[0].strip()
                elif "```" in result_text:
                    result_text = result_text.split("```")[1].split("```")[0].strip()
                result = json.loads(result_text)
                return {
                    "status": "success",
                    "matches": result.get("matches", False),
                    "confidence": result.get("confidence", 0.0),
                    "explanation": result.get("explanation", ""),
                    "actual_state": result.get("actual_state", ""),
                }
            except json.JSONDecodeError:
                return {
                    "status": "success",
                    "raw_response": result_text,
                    "matches": "yes" in result_text.lower() or "true" in result_text.lower(),
                }

        except Exception as e:
            logger.error(f"Screen verification failed: {e}")
            return {"status": "error", "error": str(e)}


# Global instance
_gemini_tool: GeminiTool | None = None


def get_gemini_tool() -> GeminiTool:
    """Get or create the global Gemini tool."""
    global _gemini_tool
    if _gemini_tool is None:
        from visionqa.backend.config import get_settings
        settings = get_settings()
        _gemini_tool = GeminiTool(
            api_key=settings.google_api_key,
            model=settings.gemini_model,
        )
    return _gemini_tool
