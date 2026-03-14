"""
Planner Sub-Agent for VisionQA
Handles test plan creation and management using Gemini AI.
"""

import logging
from typing import Any

from visionqa.services.plan_generator import get_plan_generator
from visionqa.services.test_manager import TestCase, TestPlan, get_test_manager
from visionqa.tools.gemini_tool import get_gemini_tool
from visionqa.tools.screenshot_tool import get_screenshot_tool

logger = logging.getLogger("visionqa.agent.planner")


class PlannerAgent:
    """
    Sub-agent responsible for creating and managing test plans.
    Uses Gemini AI to generate test plans from natural language instructions.
    """

    def __init__(self):
        self._generator = get_plan_generator()
        self._test_manager = get_test_manager()
        self._gemini = get_gemini_tool()
        self._screenshot = get_screenshot_tool()

    async def create_test_plan(
        self,
        instruction: str,
        url: str = "",
        page=None,
    ) -> dict[str, Any]:
        """
        Create a comprehensive test plan from a user instruction.

        Args:
            instruction: Natural language instruction (e.g., "test login page").
            url: URL of the page to test.
            page: Optional Playwright page for screenshot context.

        Returns:
            dict with the generated test plan details.
        """
        logger.info(f"Creating test plan for: {instruction}")

        screenshot_b64 = ""
        if page:
            screenshot_b64 = await self._screenshot.take_screenshot_base64(page)

        result = await self._generator.generate_test_plan(
            instruction=instruction,
            url=url,
            screenshot_b64=screenshot_b64,
        )

        # generate_test_plan now returns a dict with plan info
        return result

    async def create_single_test(
        self,
        instruction: str,
        url: str = "",
        page=None,
    ) -> dict[str, Any]:
        """
        Create a single test case.

        Args:
            instruction: What to test.
            url: URL of the page.
            page: Optional Playwright page.

        Returns:
            dict with the generated test case.
        """
        logger.info(f"Creating test case for: {instruction}")

        screenshot_b64 = ""
        if page:
            screenshot_b64 = await self._screenshot.take_screenshot_base64(page)

        test_case = await self._generator.generate_test_case(
            instruction=instruction,
            url=url,
            screenshot_b64=screenshot_b64,
        )

        return {
            "status": "success",
            "test_case": test_case.model_dump(),
        }

    async def get_plan(self, plan_id: str) -> dict[str, Any]:
        """Get a test plan by ID."""
        plan = await self._test_manager.get_test_plan(plan_id)
        if plan:
            return {"status": "success", "plan": plan.model_dump()}
        return {"status": "not_found", "error": f"Plan {plan_id} not found"}

    async def list_plans(self) -> dict[str, Any]:
        """List all test plans."""
        plans = await self._test_manager.list_test_plans()
        return {
            "status": "success",
            "plans": [p.model_dump() for p in plans],
            "total": len(plans),
        }


# Global instance
_planner_agent: PlannerAgent | None = None


def get_planner_agent() -> PlannerAgent:
    """Get or create the planner agent."""
    global _planner_agent
    if _planner_agent is None:
        _planner_agent = PlannerAgent()
    return _planner_agent
