"""
Agent Orchestrator for VisionQA
High-level orchestration layer that coordinates the agent, planner, and executor
for complex multi-step workflows.
"""

import logging
from typing import Any

from visionqa.agent.agent import get_agent
from visionqa.agent.executor import get_executor_agent
from visionqa.agent.planner import get_planner_agent
from visionqa.backend.websocket import ws_manager
from visionqa.services.test_manager import get_test_manager
from visionqa.tools.browser_tool import get_browser_tool
from visionqa.tools.speech_tool import get_speech_tool

logger = logging.getLogger("visionqa.agent.orchestrator")


class Orchestrator:
    """
    High-level orchestrator that coordinates between the agent, planner,
    and executor for complex workflows like:
    - "Test this page and save test cases"
    - "Run all tests"
    - "Create a test plan for the login flow"
    """

    def __init__(self):
        self._agent = get_agent()
        self._planner = get_planner_agent()
        self._executor = get_executor_agent()
        self._test_manager = get_test_manager()
        self._browser = get_browser_tool()
        self._speech = get_speech_tool()

    async def process_voice_command(
        self, transcript: str, session_id: str = "default"
    ) -> dict[str, Any]:
        """
        Process a voice command through the full pipeline.

        Args:
            transcript: Voice command text from speech-to-text.
            session_id: WebSocket session for live updates.

        Returns:
            dict with processing result.
        """
        logger.info(f"Processing voice command: {transcript}")

        # Process the voice command
        command = await self._speech.process_voice_command(transcript)
        intent = command.get("intent", "general")

        await ws_manager.send_log(
            f"Voice command: '{transcript}' (intent: {intent})",
            "info",
            session_id,
        )

        # Route to the main agent for intelligent processing
        response = await self._agent.process_message(transcript, session_id)

        return {
            "status": "success",
            "intent": intent,
            "command": transcript,
            "response": response,
        }

    async def process_text_command(
        self, text: str, session_id: str = "default"
    ) -> dict[str, Any]:
        """
        Process a text command through the agent.

        Args:
            text: Text command from the user.
            session_id: WebSocket session for live updates.

        Returns:
            dict with processing result.
        """
        logger.info(f"Processing text command: {text}")

        response = await self._agent.process_message(text, session_id)

        return {
            "status": "success",
            "command": text,
            "response": response,
        }

    async def run_full_test_workflow(
        self, instruction: str, url: str, session_id: str = "default"
    ) -> dict[str, Any]:
        """
        Run a complete test workflow:
        1. Open the page
        2. Create a test plan
        3. Execute all test cases
        4. Save results

        Args:
            instruction: What to test.
            url: URL to test.
            session_id: WebSocket session.

        Returns:
            Complete workflow results.
        """
        logger.info(f"Running full test workflow: {instruction} at {url}")
        await ws_manager.send_status(
            "running", f"Starting full test workflow for: {url}", session_id
        )

        # Step 1: Open the page
        await ws_manager.send_log("Step 1: Opening page...", "info", session_id)
        open_result = await self._browser.open_page(url)
        if open_result["status"] != "success":
            return {"status": "error", "error": f"Failed to open {url}"}

        # Step 2: Create test plan
        await ws_manager.send_log(
            "Step 2: Creating test plan...", "info", session_id
        )
        plan_result = await self._planner.create_test_plan(
            instruction=instruction,
            url=url,
            page=self._browser.page,
        )

        if plan_result.get("status") != "success":
            return {"status": "error", "error": "Failed to create test plan"}

        await ws_manager.send_plan(plan_result, session_id)

        # Step 3: Execute test cases
        await ws_manager.send_log(
            "Step 3: Executing test cases...", "info", session_id
        )
        results = []
        for tc_id in plan_result.get("test_case_ids", []):
            test_case = await self._test_manager.get_test_case(tc_id)
            if test_case:
                result = await self._executor.execute_test_case(test_case, session_id)
                results.append(result.model_dump())

        # Summary
        total = len(results)
        passed = sum(1 for r in results if r.get("status") == "passed")
        summary = {
            "status": "completed",
            "plan_id": plan_result.get("plan_id"),
            "plan_name": plan_result.get("plan_name"),
            "total_tests": total,
            "passed": passed,
            "failed": total - passed,
            "results": results,
        }

        # Step 4: Auto-generate report (MANDATORY)
        await ws_manager.send_log(
            "Step 4: Generating report...", "info", session_id
        )
        try:
            from visionqa.agent.agent import generate_report
            report_title = f"Test Report: {plan_result.get('plan_name', url)}"
            report_summary = (
                f"Full test workflow completed for {url}. "
                f"Tested {total} cases: {passed} passed, {total - passed} failed."
            )
            await generate_report(
                title=report_title,
                summary=report_summary,
                session_id=session_id,
            )
        except Exception as e:
            logger.warning(f"Auto-report generation failed: {e}")

        await ws_manager.send_status(
            "completed",
            f"Workflow complete: {passed}/{total} tests passed",
            session_id,
        )

        return summary

    async def cleanup(self):
        """Clean up resources."""
        try:
            await self._browser.close()
        except Exception as e:
            logger.warning(f"Cleanup error: {e}")

    def reset(self):
        """Reset the agent state."""
        self._agent.reset_chat()
        logger.info("Orchestrator reset")


# Global instance
_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    """Get or create the global orchestrator."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator
