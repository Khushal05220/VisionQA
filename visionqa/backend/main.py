"""
VisionQA FastAPI Backend
Main application entry point with REST API endpoints and WebSocket support.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from visionqa.agent.orchestrator import get_orchestrator
from visionqa.backend.config import ensure_dirs, get_settings
from visionqa.backend.websocket import ws_manager
from visionqa.services.test_manager import (
    TestCase,
    TestPlan,
    get_test_manager,
)

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("visionqa")


# --- Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    ensure_dirs()
    logger.info("🚀 VisionQA server starting...")
    yield
    # Cleanup
    orchestrator = get_orchestrator()
    await orchestrator.cleanup()
    logger.info("VisionQA server shutdown complete")


# --- FastAPI App ---
app = FastAPI(
    title="VisionQA",
    description="Voice Controlled Multimodal Visual QA Agent",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request/Response Models ---


class CommandRequest(BaseModel):
    """Text command request."""
    command: str
    session_id: str = "default"


class VoiceCommandRequest(BaseModel):
    """Voice command (already transcribed) request."""
    transcript: str
    session_id: str = "default"


class TestWorkflowRequest(BaseModel):
    """Full test workflow request."""
    instruction: str
    url: str
    session_id: str = "default"


class AgentResponse(BaseModel):
    """Standard agent response."""
    status: str
    response: str = ""
    data: dict[str, Any] = {}


# --- REST API Endpoints ---


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the frontend dashboard."""
    try:
        import os
        frontend_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "frontend",
            "index.html",
        )
        if os.path.exists(frontend_path):
            return FileResponse(frontend_path, media_type="text/html")
    except Exception:
        pass

    return HTMLResponse(
        content="<h1>VisionQA API</h1><p>Frontend not found. API is running.</p>"
    )


@app.get("/api/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "VisionQA", "version": "1.0.0"}


@app.post("/api/command", response_model=AgentResponse)
async def process_command(request: CommandRequest) -> AgentResponse:
    """
    Process a text command through the VisionQA agent.
    The agent autonomously decides which tools to use.
    """
    orchestrator = get_orchestrator()
    result = await orchestrator.process_text_command(
        request.command, request.session_id
    )
    return AgentResponse(
        status=result.get("status", "error"),
        response=result.get("response", ""),
        data=result,
    )


@app.post("/api/voice", response_model=AgentResponse)
async def process_voice_command(request: VoiceCommandRequest) -> AgentResponse:
    """
    Process a voice command (already transcribed by the frontend).
    """
    orchestrator = get_orchestrator()
    result = await orchestrator.process_voice_command(
        request.transcript, request.session_id
    )
    return AgentResponse(
        status=result.get("status", "error"),
        response=result.get("response", ""),
        data=result,
    )


@app.post("/api/test/workflow", response_model=AgentResponse)
async def run_test_workflow(request: TestWorkflowRequest) -> AgentResponse:
    """
    Run a full test workflow: open page → create plan → execute → report.
    """
    orchestrator = get_orchestrator()
    result = await orchestrator.run_full_test_workflow(
        request.instruction, request.url, request.session_id
    )
    return AgentResponse(
        status=result.get("status", "error"),
        response=f"Workflow completed: {result.get('passed', 0)}/{result.get('total_tests', 0)} passed",
        data=result,
    )


@app.post("/api/agent/reset")
async def reset_agent() -> dict[str, str]:
    """Reset the agent's chat session."""
    orchestrator = get_orchestrator()
    orchestrator.reset()
    return {"status": "success", "message": "Agent session reset"}


# --- Test Cases API ---


@app.get("/api/test-cases")
async def list_test_cases(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict]:
    """List all test cases."""
    manager = get_test_manager()
    cases = await manager.list_test_cases(limit)
    return [c.model_dump() for c in cases]


@app.get("/api/test-cases/{test_case_id}")
async def get_test_case(test_case_id: str) -> dict | None:
    """Get a test case by ID."""
    manager = get_test_manager()
    case = await manager.get_test_case(test_case_id)
    if case:
        return case.model_dump()
    return None


@app.delete("/api/test-cases/{test_case_id}")
async def delete_test_case(test_case_id: str) -> dict[str, str]:
    """Delete a test case."""
    manager = get_test_manager()
    deleted = await manager.delete_test_case(test_case_id)
    if deleted:
        return {"status": "success", "message": f"Deleted test case {test_case_id}"}
    return {"status": "not_found", "message": f"Test case {test_case_id} not found"}


# --- Test Plans API ---


@app.get("/api/test-plans")
async def list_test_plans(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict]:
    """List all test plans."""
    manager = get_test_manager()
    plans = await manager.list_test_plans(limit)
    return [p.model_dump() for p in plans]


@app.get("/api/test-plans/{plan_id}")
async def get_test_plan(plan_id: str) -> dict | None:
    """Get a test plan by ID."""
    manager = get_test_manager()
    plan = await manager.get_test_plan(plan_id)
    if plan:
        return plan.model_dump()
    return None


# --- Test Results API ---


@app.get("/api/test-results")
async def list_test_results(
    test_case_id: Annotated[str, Query()] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict]:
    """List test results, optionally filtered by test case."""
    manager = get_test_manager()
    results = await manager.list_test_results(test_case_id, limit)
    return [r.model_dump() for r in results]


# --- Report Download API ---


@app.get("/api/report/download/{filename}")
async def download_report(filename: str):
    """Download a generated PDF test report."""
    import os
    from pathlib import Path
    from visionqa.backend.config import get_settings

    settings = get_settings()
    reports_dir = Path(settings.screenshot_dir).parent / "reports"
    file_path = reports_dir / filename

    if not file_path.exists():
        return Response(content="Report not found", status_code=404)

    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- WebSocket Endpoint ---


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str = "default"):
    """
    WebSocket endpoint for real-time streaming.
    Receives commands and streams agent actions, logs, and screenshots.
    """
    await ws_manager.connect(websocket, session_id)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                import json
                message = json.loads(data)
                msg_type = message.get("type", "command")
                payload = message.get("data", {})

                if msg_type == "command":
                    command = payload.get("command", "")
                    if command:
                        orchestrator = get_orchestrator()
                        # Process in background to not block WebSocket
                        asyncio.create_task(
                            _process_ws_command(orchestrator, command, session_id)
                        )

                elif msg_type == "voice":
                    transcript = payload.get("transcript", "")
                    if transcript:
                        orchestrator = get_orchestrator()
                        asyncio.create_task(
                            _process_ws_voice(orchestrator, transcript, session_id)
                        )

                elif msg_type == "heartbeat":
                    await ws_manager.send_message(
                        ws_manager.MessageType if hasattr(ws_manager, 'MessageType') else __import__('visionqa.backend.websocket', fromlist=['MessageType']).MessageType.HEARTBEAT,
                        {"status": "alive"},
                        session_id,
                    )

            except Exception as e:
                await ws_manager.send_error(str(e), session_id)

    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket, session_id)


async def _process_ws_command(orchestrator, command: str, session_id: str):
    """Process a WebSocket command in the background."""
    try:
        result = await orchestrator.process_text_command(command, session_id)
        await ws_manager.send_message(
            __import__('visionqa.backend.websocket', fromlist=['MessageType']).MessageType.STATUS,
            {"status": "completed", "response": result.get("response", "")},
            session_id,
        )
    except Exception as e:
        await ws_manager.send_error(str(e), session_id)


async def _process_ws_voice(orchestrator, transcript: str, session_id: str):
    """Process a WebSocket voice command in the background."""
    try:
        result = await orchestrator.process_voice_command(transcript, session_id)
        await ws_manager.send_message(
            __import__('visionqa.backend.websocket', fromlist=['MessageType']).MessageType.STATUS,
            {"status": "completed", "response": result.get("response", "")},
            session_id,
        )
    except Exception as e:
        await ws_manager.send_error(str(e), session_id)


# --- Static Files ---
# Mount frontend static files (for CSS, JS, etc.)
import os
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

# Mount screenshots directory so the Live View can display them
screenshots_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), settings.screenshot_dir)
os.makedirs(screenshots_dir, exist_ok=True)
app.mount("/screenshots", StaticFiles(directory=screenshots_dir), name="screenshots")

# Mount reports directory for PDF downloads
reports_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")
os.makedirs(reports_dir, exist_ok=True)
app.mount("/reports", StaticFiles(directory=reports_dir), name="reports")
