"""
Browser Tool for VisionQA
Playwright-based browser automation for visual UI testing.
Provides tools for opening pages, clicking, typing, and navigating.
"""

import asyncio
import logging
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

logger = logging.getLogger("visionqa.tools.browser")


class BrowserTool:
    """
    Manages Playwright browser lifecycle and provides automation actions.
    Designed to be used as a singleton across agent tool invocations.
    """

    def __init__(
        self,
        headless: bool = False,
        slow_mo: int = 100,
        viewport_width: int = 1280,
        viewport_height: int = 720,
    ):
        self._headless = headless
        self._slow_mo = slow_mo
        self._viewport_width = viewport_width
        self._viewport_height = viewport_height
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._is_initialized = False

    async def initialize(self):
        """Launch browser and create a new page."""
        if self._is_initialized:
            try:
                # If browser is still open and running
                if self._browser and self._browser.is_connected():
                    # If only the tab was closed, just open a new tab
                    if self._page and not self._page.is_closed():
                        return
                    else:
                        self._page = await self._context.new_page()
                        return
            except Exception:
                pass
            
            # If we reach here, the entire browser window was manually closed by the user
            # We must wipe the old dead references so we can spawn a brand new browser!
            logger.warning("Browser was closed. Re-initializing a new instance...")
            self._is_initialized = False
            self._browser = None
            self._context = None
            self._page = None

        if self._playwright is None:
            self._playwright = await async_playwright().start()
            
        self._browser = await self._playwright.chromium.launch(
            headless=self._headless,
            slow_mo=self._slow_mo,
            args=[
                "--mute-audio",
                "--disable-features=AudioServiceOutOfProcess",
                "--no-first-run",
                "--disable-popup-blocking",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
            ],
        )
        self._context = await self._browser.new_context(
            viewport={"width": self._viewport_width, "height": self._viewport_height},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        self._page = await self._context.new_page()
        self._is_initialized = True
        logger.info("Browser initialized successfully")

    async def close_browser(self) -> dict[str, Any]:
        """Close the browser instance completely."""
        try:
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
            self._is_initialized = False
            self._browser = None
            self._context = None
            self._page = None
            logger.info("Browser closed successfully")
            return {"status": "success", "message": "Browser closed."}
        except Exception as e:
            logger.error(f"Failed to close browser: {e}")
            return {"status": "error", "error": str(e)}

    async def close(self):
        """Close browser and cleanup resources."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._is_initialized = False
        logger.info("Browser closed")

    @property
    def page(self) -> Page | None:
        return self._page

    async def open_page(self, url: str) -> dict[str, Any]:
        """
        Navigate to a URL.

        Args:
            url: The URL to navigate to.

        Returns:
            dict with status, title, and url of the loaded page.
        """
        await self.initialize()
        if not url.startswith(("http://", "https://", "file://")):
            url = f"https://{url}"
        try:
            response = await self._page.goto(url, wait_until="load", timeout=30000)
            title = await self._page.title()
            logger.info(f"Opened page: {url} (title: {title})")
            return {
                "status": "success",
                "title": title,
                "url": self._page.url,
                "http_status": response.status if response else None,
            }
        except Exception as e:
            logger.error(f"Failed to open page {url}: {e}")
            return {"status": "error", "error": str(e)}

    async def click_at_coordinates(self, x: int, y: int) -> dict[str, Any]:
        """
        Click at specific x, y coordinates on the page.

        Args:
            x: X coordinate to click.
            y: Y coordinate to click.

        Returns:
            dict with status of the click action.
        """
        await self.initialize()
        try:
            await self._page.mouse.click(x, y)
            await self._page.wait_for_timeout(500)
            logger.info(f"Clicked at coordinates ({x}, {y})")
            return {"status": "success", "x": x, "y": y}
        except Exception as e:
            logger.error(f"Click failed at ({x}, {y}): {e}")
            return {"status": "error", "error": str(e)}

    async def type_text(self, text: str, x: int = 0, y: int = 0) -> dict[str, Any]:
        """
        Type text, optionally at specific coordinates.

        Args:
            text: The text to type.
            x: X coordinate to click before typing (0 = type at current focus).
            y: Y coordinate to click before typing (0 = type at current focus).

        Returns:
            dict with status of the typing action.
        """
        await self.initialize()
        try:
            if x > 0 and y > 0:
                await self._page.mouse.click(x, y)
                await self._page.wait_for_timeout(200)

            await self._page.keyboard.type(text, delay=50)
            logger.info(f"Typed text: '{text[:50]}...' at ({x}, {y})")
            return {"status": "success", "text": text, "x": x, "y": y}
        except Exception as e:
            logger.error(f"Type failed: {e}")
            return {"status": "error", "error": str(e)}

    async def press_key(self, key: str) -> dict[str, Any]:
        """
        Press a keyboard key.

        Args:
            key: Key to press (e.g., 'Enter', 'Tab', 'Escape').

        Returns:
            dict with status of the key press.
        """
        await self.initialize()
        try:
            await self._page.keyboard.press(key)
            await self._page.wait_for_timeout(300)
            logger.info(f"Pressed key: {key}")
            return {"status": "success", "key": key}
        except Exception as e:
            logger.error(f"Key press failed: {e}")
            return {"status": "error", "error": str(e)}

    async def scroll(self, direction: str = "down", amount: int = 300) -> dict[str, Any]:
        """
        Scroll the page.

        Args:
            direction: Direction to scroll ('up' or 'down').
            amount: Number of pixels to scroll.

        Returns:
            dict with status of the scroll action.
        """
        await self.initialize()
        try:
            delta = amount if direction == "down" else -amount
            await self._page.mouse.wheel(0, delta)
            await self._page.wait_for_timeout(300)
            logger.info(f"Scrolled {direction} by {amount}px")
            return {"status": "success", "direction": direction, "amount": amount}
        except Exception as e:
            logger.error(f"Scroll failed: {e}")
            return {"status": "error", "error": str(e)}

    async def wait_for_page_load(self, timeout: int = 10000) -> dict[str, Any]:
        """
        Wait for the page to finish loading.

        Args:
            timeout: Maximum time to wait in milliseconds.

        Returns:
            dict with status and current page info.
        """
        await self.initialize()
        try:
            await self._page.wait_for_load_state("load", timeout=timeout)
            title = await self._page.title()
            return {"status": "success", "title": title, "url": self._page.url}
        except Exception as e:
            return {"status": "timeout", "error": str(e)}

    async def get_page_info(self) -> dict[str, Any]:
        """Get current page information."""
        await self.initialize()
        try:
            title = await self._page.title()
            url = self._page.url
            return {"title": title, "url": url, "status": "success"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def go_back(self) -> dict[str, Any]:
        """Navigate back in browser history."""
        await self.initialize()
        try:
            await self._page.go_back(wait_until="load")
            title = await self._page.title()
            return {"status": "success", "title": title, "url": self._page.url}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def go_forward(self) -> dict[str, Any]:
        """Navigate forward in browser history."""
        await self.initialize()
        try:
            await self._page.go_forward(wait_until="load")
            title = await self._page.title()
            return {"status": "success", "title": title, "url": self._page.url}
        except Exception as e:
            return {"status": "error", "error": str(e)}


# Global browser tool instance
_browser_tool: BrowserTool | None = None


def get_browser_tool() -> BrowserTool:
    """Get or create the global browser tool."""
    global _browser_tool
    if _browser_tool is None:
        from visionqa.backend.config import get_settings
        settings = get_settings()
        _browser_tool = BrowserTool(
            headless=settings.browser_headless,
            slow_mo=settings.browser_slow_mo,
            viewport_width=settings.browser_viewport_width,
            viewport_height=settings.browser_viewport_height,
        )
    return _browser_tool
