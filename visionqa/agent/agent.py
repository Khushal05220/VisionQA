"""
ADK Agent Definition for VisionQA
Defines the root agent with all tools using Google ADK patterns.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from google import genai
from google.genai import types

from visionqa.agent.prompts import ORCHESTRATOR_PROMPT
from visionqa.backend.config import get_settings
from visionqa.backend.websocket import ws_manager
from visionqa.tools.browser_tool import get_browser_tool
from visionqa.tools.gemini_tool import get_gemini_tool
from visionqa.tools.screenshot_tool import get_screenshot_tool
from visionqa.tools.verify_tool import get_verify_tool

logger = logging.getLogger("visionqa.agent")

# --- In-memory per-session action log ---
# Tracks everything the agent does so generate_report always has data
_session_log: dict[str, list[dict]] = {}


def _log_action(session_id: str, action: str, target: str, status: str, detail: str = ""):
    """Record a test action to the session log."""
    if session_id not in _session_log:
        _session_log[session_id] = []
    _session_log[session_id].append({
        "action": action,
        "target": target,
        "status": status,  # 'pass', 'fail', 'info'
        "detail": detail,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    })


def _get_session_log(session_id: str) -> list[dict]:
    return _session_log.get(session_id, [])


def _clear_session_log(session_id: str):
    _session_log[session_id] = []


# --- Tool Function Definitions for ADK ---
# These are the functions the agent can call.
# Each tool opens the browser lazily (auto-initializes on first use).


async def open_page(url: str, session_id: str = "default") -> str:
    """Open a webpage in the browser, take a screenshot, and show it in Live View.

    Args:
        url: The URL to navigate to.
        session_id: WebSocket session to send updates to.

    Returns:
        JSON string with page title and status.
    """
    import re
    # Extract actual URL if Gemini passes conversational text like "open example.com"
    url_match = re.search(r'(https?://[^\s]+|[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/[^\s]*)?)', url)
    clean_url = url_match.group(1) if url_match else url.strip()
    
    # Pre-validation fallback so Playwright doesn't throw a fatal kernel exception
    if " " in clean_url or not ("." in clean_url or clean_url.startswith("http")):
        return json.dumps({
            "status": "error", 
            "error": f"Extracted text '{clean_url}' does not look like a valid URL or host. Please specify a real web address."
        })
    
    browser = get_browser_tool()
    result = await browser.open_page(clean_url)
    await ws_manager.send_log(f"🌐 Opened: {clean_url}", "info", session_id)

    # Auto-take a screenshot so it shows in Live View
    if result.get("status") == "success" and browser.page:
        screenshot_tool = get_screenshot_tool()
        ss = await screenshot_tool.take_screenshot(browser.page, name="")
        if ss.get("file_path"):
            await ws_manager.send_screenshot(
                ss["file_path"],
                f"Opened: {result.get('title', clean_url)}",
                session_id,
            )
            result["screenshot"] = ss["file_path"]

    return json.dumps(result)


async def take_screenshot(name: str = "", session_id: str = "default") -> str:
    """Take a screenshot of the current browser page and show it in Live View.

    Args:
        name: Optional name for the screenshot file.
        session_id: WebSocket session.

    Returns:
        JSON string with screenshot file path.
    """
    browser = get_browser_tool()
    screenshot_tool = get_screenshot_tool()
    if browser.page:
        result = await screenshot_tool.take_screenshot(browser.page, name=name)
        if result.get("file_path"):
            await ws_manager.send_screenshot(result["file_path"], name, session_id)
        # Don't return full base64 to agent to save tokens
        safe_result = {k: v for k, v in result.items() if k != "base64"}
        return json.dumps(safe_result)
    return json.dumps({"status": "error", "error": "No browser page open. Use open_page first."})


async def analyze_ui(instruction: str = "", session_id: str = "default") -> str:
    """Analyze the current page screenshot to identify UI elements.

    Args:
        instruction: Specific instruction for analysis.
        session_id: WebSocket session.

    Returns:
        JSON string with analysis of UI elements and their coordinates.
    """
    browser = get_browser_tool()
    gemini = get_gemini_tool()
    screenshot_tool = get_screenshot_tool()

    if not browser.page:
        return json.dumps({"status": "error", "error": "No browser page open. Use open_page first."})

    b64 = await screenshot_tool.take_screenshot_base64(browser.page)
    result = await gemini.analyze_ui(b64, instruction)
    await ws_manager.send_agent_thought(
        f"UI Analysis: {result.get('analysis', '')[:200]}", session_id
    )
    return json.dumps(result)


async def click(element_description: str, session_id: str = "default") -> str:
    """Click on a UI element identified by visual description.

    Args:
        element_description: Visual description of the element to click.
        session_id: WebSocket session.

    Returns:
        JSON string with click result.
    """
    browser = get_browser_tool()
    gemini = get_gemini_tool()
    screenshot_tool = get_screenshot_tool()

    if not browser.page:
        return json.dumps({"status": "error", "error": "No browser page open. Use open_page first."})

    # Take screenshot and ask Gemini to find the element
    b64 = await screenshot_tool.take_screenshot_base64(browser.page)
    element = await gemini.find_element(b64, element_description)

    if not element.get("found", False):
        _log_action(session_id, "click", element_description, "fail", "Element not found")
        return json.dumps({
            "status": "error",
            "error": f"Element not found: {element_description}",
        })

    x, y = element["x"], element["y"]
    await ws_manager.send_action("click", f"{element_description} at ({x},{y})", "executing", session_id)
    await ws_manager.send_log(f"🖱️ Clicking: {element_description} at ({x},{y})", "info", session_id)
    result = await browser.click_at_coordinates(x, y)
    await ws_manager.send_action("click", element_description, "completed", session_id)
    _log_action(session_id, "click", element_description, "pass", f"Clicked at ({x},{y})")

    # Take screenshot after click to show updated state in Live View
    await asyncio.sleep(2.5)  # Let page navigate/update before screenshot
    ss = await screenshot_tool.take_screenshot(browser.page, name="")
    if ss.get("file_path"):
        await ws_manager.send_screenshot(
            ss["file_path"],
            f"After clicking: {element_description}",
            session_id,
        )
    result["screenshot"] = ss.get("file_path", "")

    return json.dumps(result)


async def type_text(text: str, element_description: str = "", session_id: str = "default") -> str:
    """Type text into a field, optionally identified by visual description.

    Args:
        text: The text to type.
        element_description: Visual description of the input field.
        session_id: WebSocket session.

    Returns:
        JSON string with typing result.
    """
    browser = get_browser_tool()
    gemini = get_gemini_tool()
    screenshot_tool = get_screenshot_tool()

    if not browser.page:
        return json.dumps({"status": "error", "error": "No browser page open. Use open_page first."})

    x, y = 0, 0
    if element_description:
        b64 = await screenshot_tool.take_screenshot_base64(browser.page)
        element = await gemini.find_element(b64, element_description)
        if element.get("found", False):
            x, y = element["x"], element["y"]

    await ws_manager.send_action("type", f"Typing into {element_description}", "executing", session_id)
    await ws_manager.send_log(f"⌨️ Typing: '{text[:30]}...' into {element_description or 'focused field'}", "info", session_id)
    result = await browser.type_text(text, x, y)
    await ws_manager.send_action("type", element_description, "completed", session_id)

    # Screenshot after typing
    ss = await screenshot_tool.take_screenshot(browser.page, name="")
    if ss.get("file_path"):
        await ws_manager.send_screenshot(
            ss["file_path"],
            f"After typing into: {element_description or 'field'}",
            session_id,
        )

    return json.dumps(result)


async def verify_screen(expected_state: str, session_id: str = "default") -> str:
    """Verify the current screen matches an expected state.

    Args:
        expected_state: Description of what the screen should show.
        session_id: WebSocket session.

    Returns:
        JSON string with verification result (matches, confidence, explanation).
    """
    browser = get_browser_tool()
    verify_tool = get_verify_tool()

    if not browser.page:
        return json.dumps({"status": "error", "error": "No browser page open. Use open_page first."})

    result = await verify_tool.verify_screen(browser.page, expected_state)
    passed = result.get("passed", False)
    status = "PASS ✅" if passed else "FAIL ❌"
    _log_action(
        session_id, "verify", expected_state,
        "pass" if passed else "fail",
        result.get("explanation", ""),
    )
    await ws_manager.send_log(
        f"Verification {status}: {expected_state} (confidence: {result.get('confidence', 0):.0%})",
        "success" if passed else "error",
        session_id,
    )
    return json.dumps(result)


async def save_test_case(name: str, description: str, steps_json: str, session_id: str = "default") -> str:
    """Save a test case to the database.

    Args:
        name: Name of the test case.
        description: Description of what the test case verifies.
        steps_json: JSON string of test steps array.
        session_id: WebSocket session.

    Returns:
        JSON string with saved test case ID.
    """
    from visionqa.services.test_manager import TestCase, TestStep, get_test_manager

    try:
        steps_data = json.loads(steps_json)
        steps = [TestStep(**s) for s in steps_data]
    except (json.JSONDecodeError, Exception):
        steps = []

    browser = get_browser_tool()
    url = browser.page.url if browser.page else ""

    test_case = TestCase(
        name=name,
        description=description,
        url=url,
        steps=steps,
        tags=["agent-created"],
    )

    manager = get_test_manager()
    tc_id = await manager.save_test_case(test_case)
    await ws_manager.send_log(f"💾 Saved test case: {name} (ID: {tc_id})", "success", session_id)
    return json.dumps({"status": "success", "test_case_id": tc_id, "name": name})


async def create_test_plan(instruction: str, url: str = "", session_id: str = "default") -> str:
    """Generate a comprehensive test plan using AI.

    Args:
        instruction: What to test (e.g., "test login page").
        url: URL of the page to test.
        session_id: WebSocket session.

    Returns:
        JSON string with generated test plan details.
    """
    from visionqa.agent.planner import get_planner_agent

    browser = get_browser_tool()
    if not url and browser.page:
        url = browser.page.url

    planner = get_planner_agent()
    result = await planner.create_test_plan(
        instruction=instruction,
        url=url,
        page=browser.page,
    )

    if result.get("status") == "success":
        await ws_manager.send_plan(result, session_id)
        await ws_manager.send_log(
            f"📋 Created test plan: {result.get('plan_name', '')} "
            f"with {result.get('total_test_cases', 0)} test cases",
            "success",
            session_id,
        )

    return json.dumps(result, default=str)


async def run_test_plan(plan_id: str, session_id: str = "default") -> str:
    """Execute a saved test plan.

    Args:
        plan_id: ID of the test plan to execute.
        session_id: WebSocket session.

    Returns:
        JSON string with execution results.
    """
    from visionqa.agent.executor import get_executor_agent
    from visionqa.services.test_manager import get_test_manager

    manager = get_test_manager()
    plan = await manager.get_test_plan(plan_id)

    if not plan:
        return json.dumps({"status": "error", "error": f"Plan {plan_id} not found"})

    executor = get_executor_agent()
    results = []

    for tc_id in plan.test_cases:
        test_case = await manager.get_test_case(tc_id)
        if test_case:
            result = await executor.execute_test_case(test_case)
            results.append(result.model_dump())

    # Update plan status
    total = len(results)
    passed = sum(1 for r in results if r.get("status") == "passed")
    plan_status = "completed" if total > 0 else "failed"
    await manager.update_test_plan(plan_id, {"status": plan_status})

    return json.dumps({
        "status": "success",
        "plan_id": plan_id,
        "total_tests": total,
        "passed": passed,
        "failed": total - passed,
        "results": results,
    }, default=str)


async def press_key(key: str, session_id: str = "default") -> str:
    """Press a keyboard key.

    Args:
        key: Key to press (e.g., 'Enter', 'Tab', 'Escape').
        session_id: WebSocket session.

    Returns:
        JSON string with key press result.
    """
    browser = get_browser_tool()
    if not browser.page:
        return json.dumps({"status": "error", "error": "No browser page open. Use open_page first."})

    await ws_manager.send_log(f"⌨️ Pressing key: {key}", "info", session_id)
    result = await browser.press_key(key)

    # Screenshot after key press
    screenshot_tool = get_screenshot_tool()
    ss = await screenshot_tool.take_screenshot(browser.page, name="")
    if ss.get("file_path"):
        await ws_manager.send_screenshot(ss["file_path"], f"After pressing {key}", session_id)

    return json.dumps(result)


async def scroll(direction: str = "down", amount: int = 300, session_id: str = "default") -> str:
    """Scroll the page.

    Args:
        direction: Direction to scroll ('up' or 'down').
        amount: Number of pixels to scroll.
        session_id: WebSocket session.

    Returns:
        JSON string with scroll result.
    """
    browser = get_browser_tool()
    if not browser.page:
        return json.dumps({"status": "error", "error": "No browser page open. Use open_page first."})

    result = await browser.scroll(direction, amount)

    # Screenshot after scroll
    screenshot_tool = get_screenshot_tool()
    ss = await screenshot_tool.take_screenshot(browser.page, name="")
    if ss.get("file_path"):
        await ws_manager.send_screenshot(ss["file_path"], f"After scrolling {direction}", session_id)

    return json.dumps(result)


async def go_back(session_id: str = "default") -> str:
    """Navigate back to the previous page in history.

    Args:
        session_id: WebSocket session.

    Returns:
        JSON string with result.
    """
    browser = get_browser_tool()
    if not browser.page:
        return json.dumps({"status": "error", "error": "No browser page open."})

    result = await browser.go_back()
    
    # Screenshot after navigating back
    screenshot_tool = get_screenshot_tool()
    ss = await screenshot_tool.take_screenshot(browser.page, name="")
    if ss.get("file_path"):
        await ws_manager.send_screenshot(ss["file_path"], "Navigated Back", session_id)

    return json.dumps(result)


async def close_browser(session_id: str = "default") -> str:
    """Close the browser.
    
    Args:
        session_id: WebSocket session.
        
    Returns:
        JSON string.
    """
    browser = get_browser_tool()
    
    # Optional: Send a black "closed" screen or a generic icon to Live View.
    await ws_manager.send_log("🔴 Closing the live browser instance", "info", session_id)
    
    result = await browser.close_browser()
    return json.dumps(result)


async def generate_report(title: str = "", summary: str = "", session_id: str = "default") -> str:
    """Generate test results summary and show it as a rich card in the chat.

    This is called automatically at the end of every testing session.
    It collects all test actions from the session, builds a results table,
    identifies bugs, and sends the rich results card to the chat with
    a CSV download button.

    Args:
        title: Title for the report.
        summary: AI-generated executive summary of findings.
        session_id: WebSocket session.

    Returns:
        JSON string with report summary.
    """
    from visionqa.backend.websocket import MessageType
    import re

    await ws_manager.send_log("📄 Generating test report...", "info", session_id)

    browser = get_browser_tool()
    url = ""
    try:
        if browser.page:
            url = browser.page.url
    except Exception:
        pass

    # --- Use in-memory session log as primary source ---
    actions = _get_session_log(session_id)

    # Build test items by grouping related actions into logical tests.
    # A "verify" action marks the end of a logical test (the verify result
    # determines if the test passed or failed). Standalone actions without
    # a subsequent verify are grouped as individual test items.
    test_items = []
    pending_actions = []  # Buffer actions before a verify

    for act in actions:
        if act["action"] == "verify":
            # The verify "target" is the expected state description —
            # use that as the test name because the agent was instructed to
            # write descriptive expected states.
            test_name = act["target"][:120]

            test_items.append({
                "name": test_name,
                "status": "passed" if act["status"] == "pass" else "failed",
                "steps_passed": sum(1 for a in pending_actions if a["status"] == "pass") + (1 if act["status"] == "pass" else 0),
                "steps_failed": sum(1 for a in pending_actions if a["status"] == "fail") + (1 if act["status"] == "fail" else 0),
                "steps_total": len(pending_actions) + 1,
                "url": url,
                "timestamp": act.get("timestamp", ""),
                "detail": act.get("detail", ""),
            })
            pending_actions = []
        else:
            pending_actions.append(act)

    # Any remaining un-verified actions become individual test items
    for act in pending_actions:
        if act["status"] == "info":
            continue  # Skip pure info actions (they're not test assertions)
        # Clean up the name: capitalize the action and give a readable name
        action_label = act["action"].replace("_", " ").title()
        clean_target = act["target"][:80]
        test_name = f"{action_label}: {clean_target}" if clean_target else action_label
        test_items.append({
            "name": test_name,
            "status": "passed" if act["status"] == "pass" else "failed" if act["status"] == "fail" else "info",
            "steps_passed": 1 if act["status"] == "pass" else 0,
            "steps_failed": 1 if act["status"] == "fail" else 0,
            "steps_total": 1,
            "url": url,
            "timestamp": act.get("timestamp", ""),
            "detail": act.get("detail", ""),
        })

    # If there are no test items at all but we have actions, show at least a summary
    if not test_items and actions:
        test_items.append({
            "name": "Tested navigation and scrolling",
            "status": "passed",
            "steps_passed": len(actions),
            "steps_failed": 0,
            "url": url,
            "timestamp": actions[-1].get("timestamp", "") if actions else "",
            "detail": "All actions completed successfully.",
        })

    # Extract bugs — from failed test items
    bugs = []
    seen_bug_names = set()
    for item in test_items:
        if item["status"] in ("failed", "fail"):
            bug_name = item["name"]
            if bug_name not in seen_bug_names:
                seen_bug_names.add(bug_name)
                bugs.append({
                    "name": bug_name,
                    "severity": "Major",
                    "url": item.get("url", url),
                    "detail": item.get("detail", ""),
                })

    # Also parse bugs from the AI-generated summary text (deduplicated)
    if summary:
        bug_matches = re.findall(r'[Bb]ug[:\s]+([^.\n]+)', summary)
        for bm in bug_matches:
            clean_name = bm.strip()
            if clean_name and clean_name not in seen_bug_names:
                seen_bug_names.add(clean_name)
                bugs.append({"name": clean_name, "severity": "Major", "url": url, "detail": ""})

    total = len(test_items)
    passed_count = sum(1 for t in test_items if t["status"] in ("passed", "pass"))
    failed_count = total - passed_count

    # Build a proper title from the URL if not provided
    report_title = title
    if not report_title and url:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc or parsed.path
            report_title = f"Test Report for {domain}"
        except Exception:
            report_title = "Test Results"
    elif not report_title:
        report_title = "Test Results"

    # --- Send rich test summary card to chat ---
    await ws_manager.send_message(
        MessageType.REPORT_READY,
        {
            "title": report_title,
            "summary": summary,
            "url": url,
            "total": total,
            "passed": passed_count,
            "failed": failed_count,
            "test_items": test_items,
            "bugs": bugs,
            "actions": actions,
        },
        session_id,
    )

    await ws_manager.send_log(f"✅ Report generated: {total} tests, {passed_count} passed, {failed_count} failed", "success", session_id)

    return json.dumps({"status": "success", "message": "Results shown in chat", "total": total, "passed": passed_count, "failed": failed_count})


# --- Agent Tool Registry ---

AGENT_TOOLS = [
    open_page,
    take_screenshot,
    analyze_ui,
    click,
    type_text,
    verify_screen,
    save_test_case,
    create_test_plan,
    run_test_plan,
    press_key,
    scroll,
    go_back,
    close_browser,
    generate_report,
]


class VisionQAAgent:
    """
    The root VisionQA agent.
    Uses Gemini as the LLM backbone with tool-calling capabilities.
    """

    def __init__(self):
        settings = get_settings()
        self._client = genai.Client(api_key=settings.google_api_key)
        self._model = settings.gemini_model
        self._chat = None
        self._session_id = "default"
        self._initialize_chat()

    def _initialize_chat(self):
        """Initialize the chat session with tool declarations."""
        # Build function declarations manually since our tools are async
        # and google-genai automatic calling does not support coroutines.
        fn_declarations = [
            types.FunctionDeclaration(
                name="open_page",
                description="Open a webpage in the browser. Use this when the user asks to open, navigate to, or go to a URL/website. A screenshot will be automatically taken and shown.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={"url": types.Schema(type="STRING", description="The URL to navigate to. Always include https:// prefix.")},
                    required=["url"],
                ),
            ),
            types.FunctionDeclaration(
                name="take_screenshot",
                description="Take a screenshot of the current browser page and show it in the Live View.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={"name": types.Schema(type="STRING", description="Optional name for the screenshot.")},
                ),
            ),
            types.FunctionDeclaration(
                name="analyze_ui",
                description="Analyze the current page screenshot to identify all UI elements, buttons, links, and input fields with their coordinates. Use this before clicking or interacting with elements.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={"instruction": types.Schema(type="STRING", description="Specific instruction for analysis.")},
                ),
            ),
            types.FunctionDeclaration(
                name="click",
                description="Click on a UI element identified by visual description (e.g., 'the login button', 'the search bar', 'the submit button'). The element is located visually using AI vision. A screenshot is taken after clicking.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={"element_description": types.Schema(type="STRING", description="Visual description of the element to click, e.g. 'the blue Login button' or 'the email input field'.")},
                    required=["element_description"],
                ),
            ),
            types.FunctionDeclaration(
                name="type_text",
                description="Type text into an input field. Optionally specify which field by visual description. A screenshot is taken after typing.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "text": types.Schema(type="STRING", description="The text to type."),
                        "element_description": types.Schema(type="STRING", description="Visual description of the input field to type into."),
                    },
                    required=["text"],
                ),
            ),
            types.FunctionDeclaration(
                name="verify_screen",
                description="Verify the current screen matches an expected state using AI vision. Use this to check if a page loaded correctly, a button was clicked, or an action succeeded.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={"expected_state": types.Schema(type="STRING", description="Description of what the screen should show.")},
                    required=["expected_state"],
                ),
            ),
            types.FunctionDeclaration(
                name="save_test_case",
                description="Save a test case to the database.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "name": types.Schema(type="STRING", description="Name of the test case."),
                        "description": types.Schema(type="STRING", description="Description of what the test case verifies."),
                        "steps_json": types.Schema(type="STRING", description="JSON string of test steps array."),
                    },
                    required=["name", "description", "steps_json"],
                ),
            ),
            types.FunctionDeclaration(
                name="create_test_plan",
                description="Generate a comprehensive test plan using AI. Use when the user asks to create test cases or a test plan for a page.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "instruction": types.Schema(type="STRING", description="What to test, e.g. 'test login page' or 'test all forms'."),
                        "url": types.Schema(type="STRING", description="URL of the page to test."),
                    },
                    required=["instruction"],
                ),
            ),
            types.FunctionDeclaration(
                name="run_test_plan",
                description="Execute a saved test plan by its ID.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={"plan_id": types.Schema(type="STRING", description="ID of the test plan to execute.")},
                    required=["plan_id"],
                ),
            ),
            types.FunctionDeclaration(
                name="press_key",
                description="Press a keyboard key (e.g., 'Enter', 'Tab', 'Escape', 'Backspace'). A screenshot is taken after the key press.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={"key": types.Schema(type="STRING", description="Key to press.")},
                    required=["key"],
                ),
            ),
            types.FunctionDeclaration(
                name="scroll",
                description="Scroll the page up or down to view more content. A screenshot is taken after scrolling.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "direction": types.Schema(type="STRING", description="'up' or 'down'"),
                        "amount": types.Schema(type="INTEGER", description="pixels to scroll (e.g. 300, 500)"),
                    },
                ),
            ),
            types.FunctionDeclaration(
                name="go_back",
                description="Navigate back to the previous page in the browser history. Use this when you have clicked a link to test it and need to return to the original page to continue tasks.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={},
                ),
            ),
            types.FunctionDeclaration(
                name="close_browser",
                description="Closes the physical browser window and ends the browsing session.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={},
                ),
            ),
            types.FunctionDeclaration(
                name="generate_report",
                description="Generate a test results report showing all test cases, pass/fail status, and bugs found. ONLY call this after an explicit test session (when the user asked to 'test', 'check', or 'find bugs'). NEVER call this after simple navigation commands like 'open', 'click', 'scroll'. The report appears as a rich card in the chat with CSV/XLSX download buttons.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "title": types.Schema(type="STRING", description="Title for the report, e.g. 'Login Page Test Report'."),
                        "summary": types.Schema(type="STRING", description="Executive summary of findings — what was tested, what passed, what failed, key bugs found."),
                    },
                ),
            ),
        ]

        tool_obj = types.Tool(function_declarations=fn_declarations)

        self._chat = self._client.aio.chats.create(
            model=self._model,
            config=types.GenerateContentConfig(
                system_instruction=ORCHESTRATOR_PROMPT,
                tools=[tool_obj],
                temperature=0.1,
            ),
        )
        logger.info(f"VisionQA agent initialized with {len(fn_declarations)} tools")

    async def process_message(
        self, message: str, session_id: str = "default"
    ) -> str:
        """
        Process a user message through the agent.
        The agent will decide which tools to call and orchestrate the workflow.

        Args:
            message: User's text message/command.
            session_id: WebSocket session ID.

        Returns:
            Agent's text response.
        """
        self._session_id = session_id
        logger.info(f"Processing message: {message}")
        await ws_manager.send_status("processing", f"Agent thinking: {message}", session_id)

        # Track which tools were called for building a fallback response
        tools_called = []

        try:
            # Send message to Gemini asynchronously
            response = await self._chat.send_message(message)

            # Process any tool calls the agent makes
            while response.candidates and any(
                part.function_call for part in response.candidates[0].content.parts
                if hasattr(part, "function_call") and part.function_call
            ):
                tool_results = []
                for part in response.candidates[0].content.parts:
                    if hasattr(part, "function_call") and part.function_call:
                        fc = part.function_call
                        func_name = fc.name
                        func_args = dict(fc.args) if fc.args else {}

                        logger.info(f"Agent calling tool: {func_name}({func_args})")
                        await ws_manager.send_agent_thought(
                            f"🔧 Calling: {func_name}", session_id
                        )

                        # Execute the tool (runs in the event loop)
                        result = await self._execute_tool(func_name, func_args, session_id)

                        # Track tool for fallback response
                        tools_called.append({
                            "name": func_name,
                            "args": func_args,
                            "result_preview": str(result)[:100] if result else "",
                        })

                        tool_results.append(
                            types.Part.from_function_response(
                                name=func_name,
                                response={"result": result},
                            )
                        )

                # Send tool results back to the model asynchronously
                response = await self._chat.send_message(tool_results)

            # Extract final text response
            final_text = ""
            if response.candidates:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, "text") and part.text:
                        final_text += part.text

            # If Gemini returned no text, build a descriptive fallback
            if not final_text.strip() and tools_called:
                final_text = self._build_fallback_response(tools_called)

            await ws_manager.send_status("completed", final_text[:200] if final_text else "Ready", session_id)
            return final_text or "I'm ready. How can I help you?"

        except Exception as e:
            error_msg = f"Agent error: {str(e)}"
            logger.error(error_msg, exc_info=True)
            await ws_manager.send_error(error_msg, session_id)
            return error_msg

    def _build_fallback_response(self, tools_called: list) -> str:
        """Build a descriptive response when Gemini returned no text after tool calls."""
        descriptions = []
        for tool in tools_called:
            name = tool["name"]
            args = tool["args"]
            if name == "open_page":
                url = args.get("url", "the page")
                descriptions.append(f"Opened {url}")
            elif name == "click":
                target = args.get("element_description", "the element")
                descriptions.append(f"Clicked on '{target}'")
            elif name == "type_text":
                text = args.get("text", "")
                target = args.get("element_description", "the field")
                descriptions.append(f"Typed '{text}' into {target}")
            elif name == "scroll":
                direction = args.get("direction", "down")
                descriptions.append(f"Scrolled {direction}")
            elif name == "go_back":
                descriptions.append("Navigated back to the previous page")
            elif name == "take_screenshot":
                descriptions.append("Took a screenshot")
            elif name == "analyze_ui":
                descriptions.append("Analyzed the UI elements")
            elif name == "verify_screen":
                descriptions.append("Verified the screen state")
            elif name == "generate_report":
                descriptions.append("Generated the test report")
            elif name == "press_key":
                key = args.get("key", "")
                descriptions.append(f"Pressed the '{key}' key")
            elif name == "close_browser":
                descriptions.append("Closed the browser")
            else:
                descriptions.append(f"Executed {name}")

        if len(descriptions) == 1:
            return f"Done! {descriptions[0]}."
        else:
            return "Done! " + ". ".join(descriptions) + "."

    async def _execute_tool(self, func_name: str, args: dict, session_id: str = "default") -> str:
        """Execute a tool function by name."""
        tool_map = {func.__name__: func for func in AGENT_TOOLS}
        if func_name in tool_map:
            try:
                # Inject session_id so tools can send WS updates
                args["session_id"] = session_id
                result = await tool_map[func_name](**args)
                return result
            except TypeError:
                # If session_id is not a valid param, try without it
                args.pop("session_id", None)
                try:
                    result = await tool_map[func_name](**args)
                    return result
                except Exception as e:
                    logger.error(f"Tool execution error ({func_name}): {e}", exc_info=True)
                    return json.dumps({"status": "error", "error": str(e)})
            except Exception as e:
                logger.error(f"Tool execution error ({func_name}): {e}", exc_info=True)
                return json.dumps({"status": "error", "error": str(e)})
        return json.dumps({"status": "error", "error": f"Unknown tool: {func_name}"})

    def reset_chat(self):
        """Reset the chat session."""
        self._initialize_chat()
        logger.info("Agent chat session reset")


# Global instance
_agent: VisionQAAgent | None = None


def get_agent() -> VisionQAAgent:
    """Get or create the global VisionQA agent."""
    global _agent
    if _agent is None:
        _agent = VisionQAAgent()
    return _agent
