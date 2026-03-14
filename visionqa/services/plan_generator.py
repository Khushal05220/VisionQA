"""
Plan Generator Service for VisionQA
Uses Gemini to automatically generate test plans from user instructions.
"""

import json
import logging
from typing import Any

from visionqa.tools.gemini_tool import get_gemini_tool
from visionqa.services.test_manager import (
    TestCase,
    TestPlan,
    TestStep,
    get_test_manager,
)

logger = logging.getLogger("visionqa.services.plan_generator")


class PlanGenerator:
    """
    Generates test plans and test cases using Gemini AI.
    Takes a high-level user instruction and produces actionable test steps.
    """

    def __init__(self):
        self._gemini = get_gemini_tool()
        self._test_manager = get_test_manager()

    async def generate_test_plan(
        self, instruction: str, url: str = "", screenshot_b64: str = ""
    ) -> dict:
        """
        Generate a comprehensive test plan from a user instruction.

        Args:
            instruction: User's natural language test instruction.
            url: URL of the page to test.
            screenshot_b64: Optional screenshot for context.

        Returns:
            dict with plan info, test case IDs, and status.
        """
        prompt = self._build_plan_prompt(instruction, url)

        if screenshot_b64:
            # Use vision to understand the page
            analysis = await self._gemini.analyze_ui(
                screenshot_b64,
                f"Analyze this webpage to help create a test plan for: {instruction}. "
                f"Identify all interactive elements, forms, buttons, and navigation items."
            )
            page_context = analysis.get("analysis", "")
            prompt += f"\n\nPage Analysis:\n{page_context}"

        # Generate the plan using Gemini
        response = await self._gemini.generate_text(prompt)

        # Parse the response into structured test plan + test case objects
        plan, test_case_objects = self._parse_plan_response(response, instruction, url)

        # Save the plan and its test cases
        test_case_ids = []
        for tc in test_case_objects:
            tc_id = await self._test_manager.save_test_case(tc)
            test_case_ids.append(tc_id)

        plan.test_cases = test_case_ids
        await self._test_manager.save_test_plan(plan)
        logger.info(
            f"Generated test plan '{plan.name}' with {len(test_case_ids)} test cases"
        )

        return {
            "status": "success",
            "plan_id": plan.id,
            "plan_name": plan.name,
            "total_test_cases": len(test_case_ids),
            "test_case_ids": test_case_ids,
        }

    async def generate_test_case(
        self, instruction: str, url: str = "", screenshot_b64: str = ""
    ) -> TestCase:
        """
        Generate a single test case from an instruction.

        Args:
            instruction: What to test.
            url: URL of the page.
            screenshot_b64: Optional screenshot for context.

        Returns:
            Generated TestCase.
        """
        prompt = self._build_test_case_prompt(instruction, url)

        if screenshot_b64:
            analysis = await self._gemini.analyze_ui(
                screenshot_b64,
                f"Analyze this webpage for testing: {instruction}"
            )
            prompt += f"\n\nPage Analysis:\n{analysis.get('analysis', '')}"

        response = await self._gemini.generate_text(prompt)
        test_case = self._parse_test_case_response(response, instruction, url)

        await self._test_manager.save_test_case(test_case)
        logger.info(f"Generated test case: {test_case.name}")
        return test_case

    def _build_plan_prompt(self, instruction: str, url: str) -> str:
        """Build the Gemini prompt for test plan generation."""
        return f"""You are an expert QA engineer. Create a comprehensive test plan for the following:

Instruction: {instruction}
URL: {url or 'Not specified'}

Generate a test plan in the following JSON format:
{{
    "name": "Test Plan Name",
    "description": "Brief description of the test plan",
    "test_cases": [
        {{
            "name": "Test Case Name",
            "description": "What this test case verifies",
            "steps": [
                {{
                    "order": 1,
                    "action": "open_page | click | type_text | verify_screen | scroll | press_key | take_screenshot",
                    "target": "Description of the UI element to interact with",
                    "value": "Value to type or URL to open (if applicable)",
                    "expected_result": "What should happen after this step"
                }}
            ]
        }}
    ]
}}

Rules:
1. Each test case should test ONE specific feature or flow
2. Steps should use visual descriptions (NOT CSS selectors)
3. Include verification steps to confirm expected behavior
4. Available actions: open_page, click, type_text, verify_screen, scroll, press_key, take_screenshot
5. For click and type_text, target should describe the visual element (e.g., "the Login button", "the username input field")
6. For open_page, put the URL in the value field
7. For verify_screen, put the expected state in expected_result
8. Include take_screenshot steps after important actions
9. Return ONLY valid JSON, no markdown formatting

Think step-by-step about what a real user would do."""

    def _build_test_case_prompt(self, instruction: str, url: str) -> str:
        """Build prompt for single test case generation."""
        return f"""You are an expert QA engineer. Create a single test case for:

Instruction: {instruction}
URL: {url or 'Not specified'}

Generate a test case in this JSON format:
{{
    "name": "Test Case Name",
    "description": "What this test case verifies",
    "steps": [
        {{
            "order": 1,
            "action": "open_page | click | type_text | verify_screen | scroll | press_key | take_screenshot",
            "target": "Description of the UI element",
            "value": "Value to type or URL to open",
            "expected_result": "Expected outcome"
        }}
    ]
}}

Rules:
1. Use visual descriptions for targets, NOT CSS selectors
2. Available actions: open_page, click, type_text, verify_screen, scroll, press_key, take_screenshot
3. Include verification steps
4. Return ONLY valid JSON, no markdown formatting
5. Be thorough but practical"""

    def _parse_plan_response(
        self, response: str, instruction: str, url: str
    ) -> tuple[TestPlan, list[TestCase]]:
        """Parse Gemini response into a TestPlan and list of TestCase objects."""
        try:
            # Clean up response
            cleaned = response.strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json")[1].split("```")[0].strip()
            elif "```" in cleaned:
                cleaned = cleaned.split("```")[1].split("```")[0].strip()

            data = json.loads(cleaned)

            plan = TestPlan(
                name=data.get("name", f"Test Plan: {instruction}"),
                description=data.get("description", instruction),
                url=url,
            )

            test_case_objects = []

            for tc_data in data.get("test_cases", []):
                steps = []
                for step_data in tc_data.get("steps", []):
                    steps.append(TestStep(
                        order=step_data.get("order", len(steps) + 1),
                        action=step_data.get("action", ""),
                        target=step_data.get("target", ""),
                        value=step_data.get("value", ""),
                        expected_result=step_data.get("expected_result", ""),
                    ))

                test_case = TestCase(
                    name=tc_data.get("name", "Unnamed Test"),
                    description=tc_data.get("description", ""),
                    url=url,
                    steps=steps,
                    tags=["auto-generated"],
                )
                test_case_objects.append(test_case)

            return plan, test_case_objects

        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Failed to parse plan response: {e}")
            # Create a basic plan from the raw response
            plan = TestPlan(
                name=f"Test Plan: {instruction}",
                description=response[:500],
                url=url,
            )
            return plan, []

    def _parse_test_case_response(
        self, response: str, instruction: str, url: str
    ) -> TestCase:
        """Parse Gemini response into a TestCase object."""
        try:
            cleaned = response.strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json")[1].split("```")[0].strip()
            elif "```" in cleaned:
                cleaned = cleaned.split("```")[1].split("```")[0].strip()

            data = json.loads(cleaned)

            steps = []
            for step_data in data.get("steps", []):
                steps.append(TestStep(
                    order=step_data.get("order", len(steps) + 1),
                    action=step_data.get("action", ""),
                    target=step_data.get("target", ""),
                    value=step_data.get("value", ""),
                    expected_result=step_data.get("expected_result", ""),
                ))

            return TestCase(
                name=data.get("name", f"Test: {instruction}"),
                description=data.get("description", instruction),
                url=url,
                steps=steps,
                tags=["auto-generated"],
            )

        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Failed to parse test case response: {e}")
            return TestCase(
                name=f"Test: {instruction}",
                description=instruction,
                url=url,
                tags=["auto-generated", "parse-failed"],
            )


# Global instance
_plan_generator: PlanGenerator | None = None


def get_plan_generator() -> PlanGenerator:
    """Get or create the global plan generator."""
    global _plan_generator
    if _plan_generator is None:
        _plan_generator = PlanGenerator()
    return _plan_generator
