"""
Executor Sub-Agent for VisionQA
Executes test steps using browser automation and visual AI.
"""

import logging
import time
from typing import Any

from visionqa.backend.websocket import MessageType, ws_manager
from visionqa.services.test_manager import (
    TestCase,
    TestResult,
    TestStep,
    get_test_manager,
)
from visionqa.tools.browser_tool import get_browser_tool
from visionqa.tools.gemini_tool import get_gemini_tool
from visionqa.tools.screenshot_tool import get_screenshot_tool
from visionqa.tools.verify_tool import get_verify_tool

logger = logging.getLogger("visionqa.agent.executor")


class ExecutorAgent:
    """
    Sub-agent responsible for executing test steps.
    Uses visual AI to find elements and browser automation to interact with them.
    """

    def __init__(self):
        self._browser = get_browser_tool()
        self._screenshot = get_screenshot_tool()
        self._gemini = get_gemini_tool()
        self._verify = get_verify_tool()
        self._test_manager = get_test_manager()

    async def execute_test_case(
        self, test_case: TestCase, session_id: str = "default"
    ) -> TestResult:
        """
        Execute all steps of a test case.

        Args:
            test_case: The test case to execute.
            session_id: WebSocket session for live updates.

        Returns:
            TestResult with execution details.
        """
        logger.info(f"Executing test case: {test_case.name}")
        await ws_manager.send_status("running", f"Executing: {test_case.name}", session_id)

        start_time = time.time()
        steps_passed = 0
        steps_failed = 0
        screenshots = []

        # Update test case status
        await self._test_manager.update_test_case(
            test_case.id, {"status": "running"}
        )

        for step in test_case.steps:
            await ws_manager.send_action(
                step.action,
                step.target or step.value,
                "executing",
                session_id,
            )

            result = await self._execute_step(step, session_id)

            if result.get("screenshot"):
                screenshots.append(result["screenshot"])

            if result.get("passed", False):
                steps_passed += 1
                step.status = "passed"
                step.actual_result = result.get("actual_result", "")
                await ws_manager.send_action(
                    step.action, step.target, "passed", session_id
                )
            else:
                steps_failed += 1
                step.status = "failed"
                step.actual_result = result.get("error", result.get("actual_result", ""))
                await ws_manager.send_action(
                    step.action, step.target, "failed", session_id
                )
                await ws_manager.send_log(
                    f"Step {step.order} failed: {step.actual_result}",
                    "error",
                    session_id,
                )

        duration = time.time() - start_time
        overall_status = "passed" if steps_failed == 0 else "failed"

        # Update test case
        await self._test_manager.update_test_case(
            test_case.id,
            {
                "status": overall_status,
                "steps": [s.model_dump() for s in test_case.steps],
            },
        )

        # Create and save result
        test_result = TestResult(
            test_case_id=test_case.id,
            status=overall_status,
            steps_total=len(test_case.steps),
            steps_passed=steps_passed,
            steps_failed=steps_failed,
            duration_seconds=round(duration, 2),
            screenshots=screenshots,
        )

        await self._test_manager.save_test_result(test_result)
        await ws_manager.send_test_result(test_result.model_dump(), session_id)
        await ws_manager.send_status(
            overall_status,
            f"Test '{test_case.name}': {steps_passed}/{len(test_case.steps)} passed "
            f"({duration:.1f}s)",
            session_id,
        )

        logger.info(
            f"Test case '{test_case.name}' completed: {overall_status} "
            f"({steps_passed}/{len(test_case.steps)} passed, {duration:.1f}s)"
        )

        return test_result

    async def _execute_step(
        self, step: TestStep, session_id: str = "default"
    ) -> dict[str, Any]:
        """Execute a single test step."""
        try:
            action = step.action.lower().strip()

            if action == "open_page":
                return await self._execute_open_page(step, session_id)
            elif action == "click":
                return await self._execute_click(step, session_id)
            elif action == "type_text":
                return await self._execute_type(step, session_id)
            elif action == "verify_screen":
                return await self._execute_verify(step, session_id)
            elif action == "take_screenshot":
                return await self._execute_screenshot(step, session_id)
            elif action == "scroll":
                return await self._execute_scroll(step, session_id)
            elif action == "press_key":
                return await self._execute_press_key(step, session_id)
            else:
                return {
                    "passed": False,
                    "error": f"Unknown action: {action}",
                }
        except Exception as e:
            logger.error(f"Step execution error: {e}")
            return {"passed": False, "error": str(e)}

    async def _execute_open_page(
        self, step: TestStep, session_id: str
    ) -> dict[str, Any]:
        """Execute an open_page step."""
        url = step.value or step.target
        await ws_manager.send_log(f"Opening page: {url}", "info", session_id)

        result = await self._browser.open_page(url)
        if result["status"] == "success":
            # Take screenshot after opening
            ss = await self._screenshot.take_screenshot(self._browser.page)
            await ws_manager.send_screenshot(
                ss.get("file_path", ""),
                f"Page loaded: {result.get('title', '')}",
                session_id,
            )
            return {
                "passed": True,
                "actual_result": f"Page loaded: {result.get('title', '')}",
                "screenshot": ss.get("file_path", ""),
            }
        return {"passed": False, "error": result.get("error", "Failed to open page")}

    async def _execute_click(
        self, step: TestStep, session_id: str
    ) -> dict[str, Any]:
        """Execute a click step by finding element visually."""
        element_desc = step.target
        await ws_manager.send_log(f"Finding element: {element_desc}", "info", session_id)

        # Take screenshot for visual analysis
        screenshot_b64 = await self._screenshot.take_screenshot_base64(self._browser.page)

        # Use Gemini to find the element
        element = await self._gemini.find_element(screenshot_b64, element_desc)

        if not element.get("found", False):
            return {
                "passed": False,
                "error": f"Element not found: {element_desc}",
            }

        # Click at the found coordinates
        x, y = element["x"], element["y"]
        await ws_manager.send_log(
            f"Clicking at ({x}, {y}): {element_desc}", "info", session_id
        )

        click_result = await self._browser.click_at_coordinates(x, y)

        if click_result["status"] == "success":
            # Take post-click screenshot
            ss = await self._screenshot.take_screenshot(self._browser.page)
            await ws_manager.send_screenshot(
                ss.get("file_path", ""),
                f"After clicking: {element_desc}",
                session_id,
            )

            # Verify if expected result is specified
            if step.expected_result:
                verify = await self._verify.verify_screen(
                    self._browser.page, step.expected_result
                )
                return {
                    "passed": verify.get("passed", True),
                    "actual_result": verify.get("actual", f"Clicked {element_desc}"),
                    "screenshot": ss.get("file_path", ""),
                }

            return {
                "passed": True,
                "actual_result": f"Clicked {element_desc} at ({x}, {y})",
                "screenshot": ss.get("file_path", ""),
            }

        return {"passed": False, "error": click_result.get("error", "Click failed")}

    async def _execute_type(
        self, step: TestStep, session_id: str
    ) -> dict[str, Any]:
        """Execute a type_text step."""
        text = step.value
        field_desc = step.target

        await ws_manager.send_log(
            f"Typing into: {field_desc}", "info", session_id
        )

        # Find the field visually if described
        x, y = 0, 0
        if field_desc:
            screenshot_b64 = await self._screenshot.take_screenshot_base64(
                self._browser.page
            )
            element = await self._gemini.find_element(screenshot_b64, field_desc)
            if element.get("found", False):
                x, y = element["x"], element["y"]
            else:
                return {
                    "passed": False,
                    "error": f"Input field not found: {field_desc}",
                }

        result = await self._browser.type_text(text, x, y)
        if result["status"] == "success":
            ss = await self._screenshot.take_screenshot(self._browser.page)
            return {
                "passed": True,
                "actual_result": f"Typed '{text}' into {field_desc}",
                "screenshot": ss.get("file_path", ""),
            }
        return {"passed": False, "error": result.get("error", "Type failed")}

    async def _execute_verify(
        self, step: TestStep, session_id: str
    ) -> dict[str, Any]:
        """Execute a verify_screen step."""
        expected = step.expected_result or step.target
        await ws_manager.send_log(f"Verifying: {expected}", "info", session_id)

        result = await self._verify.verify_screen(self._browser.page, expected)
        ss = await self._screenshot.take_screenshot(self._browser.page)

        return {
            "passed": result.get("passed", False),
            "actual_result": result.get("actual", ""),
            "screenshot": ss.get("file_path", ""),
        }

    async def _execute_screenshot(
        self, step: TestStep, session_id: str
    ) -> dict[str, Any]:
        """Execute a take_screenshot step."""
        name = step.value or step.target or ""
        ss = await self._screenshot.take_screenshot(self._browser.page, name=name)
        await ws_manager.send_screenshot(
            ss.get("file_path", ""),
            step.target or "Screenshot captured",
            session_id,
        )
        return {
            "passed": True,
            "actual_result": "Screenshot captured",
            "screenshot": ss.get("file_path", ""),
        }

    async def _execute_scroll(
        self, step: TestStep, session_id: str
    ) -> dict[str, Any]:
        """Execute a scroll step."""
        direction = step.value or "down"
        amount = 300
        try:
            if step.target and step.target.isdigit():
                amount = int(step.target)
        except ValueError:
            pass

        result = await self._browser.scroll(direction, amount)
        if result["status"] == "success":
            return {"passed": True, "actual_result": f"Scrolled {direction} by {amount}px"}
        return {"passed": False, "error": result.get("error", "Scroll failed")}

    async def _execute_press_key(
        self, step: TestStep, session_id: str
    ) -> dict[str, Any]:
        """Execute a press_key step."""
        key = step.value or step.target
        result = await self._browser.press_key(key)
        if result["status"] == "success":
            return {"passed": True, "actual_result": f"Pressed key: {key}"}
        return {"passed": False, "error": result.get("error", "Key press failed")}


# Global instance
_executor_agent: ExecutorAgent | None = None


def get_executor_agent() -> ExecutorAgent:
    """Get or create the executor agent."""
    global _executor_agent
    if _executor_agent is None:
        _executor_agent = ExecutorAgent()
    return _executor_agent
