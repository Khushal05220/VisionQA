"""
WebSocket Manager for VisionQA
Handles real-time streaming of agent actions, logs, and screenshots to the frontend.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from enum import Enum

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("visionqa.websocket")


class MessageType(str, Enum):
    """Types of WebSocket messages."""
    LOG = "log"
    SCREENSHOT = "screenshot"
    ACTION = "action"
    STATUS = "status"
    TEST_RESULT = "test_result"
    PLAN = "plan"
    ERROR = "error"
    HEARTBEAT = "heartbeat"
    AGENT_THOUGHT = "agent_thought"
    VOICE_TRANSCRIPT = "voice_transcript"
    REPORT_READY = "report_ready"


class ConnectionManager:
    """
    Manages WebSocket connections and broadcasts messages to all connected clients.
    Supports multiple concurrent sessions.
    """

    def __init__(self):
        self._active_connections: dict[str, list[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, session_id: str = "default"):
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            if session_id not in self._active_connections:
                self._active_connections[session_id] = []
            self._active_connections[session_id].append(websocket)
        logger.info(f"Client connected to session '{session_id}'. "
                     f"Active connections: {len(self._active_connections[session_id])}")

    async def disconnect(self, websocket: WebSocket, session_id: str = "default"):
        """Remove a WebSocket connection."""
        async with self._lock:
            if session_id in self._active_connections:
                if websocket in self._active_connections[session_id]:
                    self._active_connections[session_id].remove(websocket)
                if not self._active_connections[session_id]:
                    del self._active_connections[session_id]
        logger.info(f"Client disconnected from session '{session_id}'")

    async def send_message(
        self,
        message_type: MessageType,
        data: dict,
        session_id: str = "default",
    ):
        """Send a typed message to all clients in a session."""
        payload = {
            "type": message_type.value,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._broadcast(json.dumps(payload, default=str), session_id)

    async def send_log(self, message: str, level: str = "info", session_id: str = "default"):
        """Send a log message."""
        await self.send_message(
            MessageType.LOG,
            {"message": message, "level": level},
            session_id,
        )

    async def send_screenshot(self, image_url: str, description: str = "", session_id: str = "default"):
        """Send a screenshot notification with URL."""
        await self.send_message(
            MessageType.SCREENSHOT,
            {"image_url": image_url, "description": description},
            session_id,
        )

    async def send_action(self, action: str, target: str = "", status: str = "executing", session_id: str = "default"):
        """Send an action status update."""
        await self.send_message(
            MessageType.ACTION,
            {"action": action, "target": target, "status": status},
            session_id,
        )

    async def send_status(self, status: str, details: str = "", session_id: str = "default"):
        """Send overall status update."""
        await self.send_message(
            MessageType.STATUS,
            {"status": status, "details": details},
            session_id,
        )

    async def send_test_result(self, result: dict, session_id: str = "default"):
        """Send a test result."""
        await self.send_message(MessageType.TEST_RESULT, result, session_id)

    async def send_plan(self, plan: dict, session_id: str = "default"):
        """Send a test plan."""
        await self.send_message(MessageType.PLAN, plan, session_id)

    async def send_error(self, error: str, session_id: str = "default"):
        """Send an error message."""
        await self.send_message(
            MessageType.ERROR,
            {"error": error},
            session_id,
        )

    async def send_agent_thought(self, thought: str, session_id: str = "default"):
        """Send agent's reasoning/thought to the UI."""
        await self.send_message(
            MessageType.AGENT_THOUGHT,
            {"thought": thought},
            session_id,
        )

    async def send_report_ready(
        self, download_url: str, filename: str, summary: str = "", session_id: str = "default"
    ):
        """Notify the frontend that a PDF report is ready for download."""
        await self.send_message(
            MessageType.REPORT_READY,
            {
                "download_url": download_url,
                "filename": filename,
                "summary": summary,
            },
            session_id,
        )

    async def _broadcast(self, message: str, session_id: str):
        """Broadcast a message to all connections in a session."""
        async with self._lock:
            connections = self._active_connections.get(session_id, [])
            dead_connections = []
            for connection in connections:
                try:
                    await connection.send_text(message)
                except (WebSocketDisconnect, RuntimeError, Exception) as e:
                    logger.warning(f"Failed to send message: {e}")
                    dead_connections.append(connection)

            # Clean up dead connections
            for dead in dead_connections:
                if dead in self._active_connections.get(session_id, []):
                    self._active_connections[session_id].remove(dead)

    def get_active_sessions(self) -> list[str]:
        """Get list of active session IDs."""
        return list(self._active_connections.keys())

    def get_connection_count(self, session_id: str = "default") -> int:
        """Get number of active connections for a session."""
        return len(self._active_connections.get(session_id, []))


# Global connection manager instance
ws_manager = ConnectionManager()
