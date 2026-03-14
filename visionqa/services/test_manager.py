"""
Test Manager Service for VisionQA
CRUD operations for test cases, results, and plans in Firestore.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from visionqa.database.firestore_client import get_firestore_client

logger = logging.getLogger("visionqa.services.test_manager")


# --- Pydantic Models ---


class TestStep(BaseModel):
    """A single step in a test case."""
    order: int
    action: str
    target: str = ""
    value: str = ""
    expected_result: str = ""
    actual_result: str = ""
    status: str = "pending"  # pending, passed, failed, skipped
    screenshot_url: str = ""


class TestCase(BaseModel):
    """A test case with steps and metadata."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str = ""
    url: str = ""
    steps: list[TestStep] = []
    status: str = "created"  # created, running, passed, failed
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    tags: list[str] = []


class TestResult(BaseModel):
    """Result of executing a test case."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    test_case_id: str
    status: str = "pending"  # pending, running, passed, failed
    steps_total: int = 0
    steps_passed: int = 0
    steps_failed: int = 0
    duration_seconds: float = 0.0
    error_message: str = ""
    screenshots: list[str] = []
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class TestPlan(BaseModel):
    """A test plan containing multiple test cases."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str = ""
    url: str = ""
    test_cases: list[str] = []  # List of test case IDs
    status: str = "created"  # created, running, completed
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# --- Test Manager Service ---


class TestManager:
    """Manages test cases, results, and plans in Firestore."""

    def __init__(self):
        self._db = get_firestore_client()

    # --- Test Cases ---

    async def save_test_case(self, test_case: TestCase) -> str:
        """Save a test case to Firestore."""
        doc_id = await self._db.add_document(
            "test_cases",
            test_case.model_dump(),
            doc_id=test_case.id,
        )
        logger.info(f"Saved test case: {test_case.name} (ID: {doc_id})")
        return doc_id

    async def get_test_case(self, test_case_id: str) -> TestCase | None:
        """Get a test case by ID."""
        doc = await self._db.get_document("test_cases", test_case_id)
        if doc:
            return TestCase(**doc)
        return None

    async def list_test_cases(self, limit: int = 50) -> list[TestCase]:
        """List all test cases."""
        docs = await self._db.list_documents("test_cases", limit)
        return [TestCase(**doc) for doc in docs]

    async def update_test_case(self, test_case_id: str, updates: dict) -> bool:
        """Update a test case."""
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        return await self._db.update_document("test_cases", test_case_id, updates)

    async def delete_test_case(self, test_case_id: str) -> bool:
        """Delete a test case."""
        return await self._db.delete_document("test_cases", test_case_id)

    # --- Test Results ---

    async def save_test_result(self, result: TestResult) -> str:
        """Save a test execution result."""
        doc_id = await self._db.add_document(
            "test_results",
            result.model_dump(),
            doc_id=result.id,
        )
        logger.info(
            f"Saved test result: {result.status} for case {result.test_case_id} "
            f"({result.steps_passed}/{result.steps_total} passed)"
        )
        return doc_id

    async def get_test_result(self, result_id: str) -> TestResult | None:
        """Get a test result by ID."""
        doc = await self._db.get_document("test_results", result_id)
        if doc:
            return TestResult(**doc)
        return None

    async def list_test_results(
        self, test_case_id: str = "", limit: int = 50
    ) -> list[TestResult]:
        """List test results, optionally filtered by test case."""
        if test_case_id:
            docs = await self._db.query_documents(
                "test_results", "test_case_id", test_case_id, limit
            )
        else:
            docs = await self._db.list_documents("test_results", limit)
        return [TestResult(**doc) for doc in docs]

    # --- Test Plans ---

    async def save_test_plan(self, plan: TestPlan) -> str:
        """Save a test plan."""
        doc_id = await self._db.add_document(
            "test_plans",
            plan.model_dump(),
            doc_id=plan.id,
        )
        logger.info(f"Saved test plan: {plan.name} (ID: {doc_id})")
        return doc_id

    async def get_test_plan(self, plan_id: str) -> TestPlan | None:
        """Get a test plan by ID."""
        doc = await self._db.get_document("test_plans", plan_id)
        if doc:
            return TestPlan(**doc)
        return None

    async def list_test_plans(self, limit: int = 50) -> list[TestPlan]:
        """List all test plans."""
        docs = await self._db.list_documents("test_plans", limit)
        return [TestPlan(**doc) for doc in docs]

    async def update_test_plan(self, plan_id: str, updates: dict) -> bool:
        """Update a test plan."""
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        return await self._db.update_document("test_plans", plan_id, updates)


# Global instance
_test_manager: TestManager | None = None


def get_test_manager() -> TestManager:
    """Get or create the global test manager."""
    global _test_manager
    if _test_manager is None:
        _test_manager = TestManager()
    return _test_manager
