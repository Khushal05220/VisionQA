"""
Firestore Client for VisionQA
Handles all database operations for test cases, results, and plans.
Supports both real Firestore and a local fallback for development.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("visionqa.firestore")


class LocalFirestoreClient:
    """
    Local file-based fallback when Firestore is not available.
    Stores data as JSON files for development/testing.
    """

    def __init__(self, data_dir: str = "local_db"):
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Using local file-based storage at: {self._data_dir.absolute()}")

    def _collection_dir(self, collection: str) -> Path:
        path = self._data_dir / collection
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def add_document(self, collection: str, data: dict, doc_id: str | None = None) -> str:
        """Add a document to a collection."""
        if doc_id is None:
            doc_id = str(uuid.uuid4())
        data["id"] = doc_id
        data["created_at"] = datetime.now(timezone.utc).isoformat()
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        file_path = self._collection_dir(collection) / f"{doc_id}.json"
        file_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        logger.info(f"Added document '{doc_id}' to '{collection}'")
        return doc_id

    async def get_document(self, collection: str, doc_id: str) -> dict | None:
        """Get a document by ID."""
        file_path = self._collection_dir(collection) / f"{doc_id}.json"
        if file_path.exists():
            return json.loads(file_path.read_text(encoding="utf-8"))
        return None

    async def update_document(self, collection: str, doc_id: str, data: dict) -> bool:
        """Update an existing document."""
        file_path = self._collection_dir(collection) / f"{doc_id}.json"
        if not file_path.exists():
            return False
        existing = json.loads(file_path.read_text(encoding="utf-8"))
        existing.update(data)
        existing["updated_at"] = datetime.now(timezone.utc).isoformat()
        file_path.write_text(json.dumps(existing, indent=2, default=str), encoding="utf-8")
        logger.info(f"Updated document '{doc_id}' in '{collection}'")
        return True

    async def delete_document(self, collection: str, doc_id: str) -> bool:
        """Delete a document."""
        file_path = self._collection_dir(collection) / f"{doc_id}.json"
        if file_path.exists():
            file_path.unlink()
            logger.info(f"Deleted document '{doc_id}' from '{collection}'")
            return True
        return False

    async def list_documents(self, collection: str, limit: int = 100) -> list[dict]:
        """List all documents in a collection."""
        docs = []
        col_dir = self._collection_dir(collection)
        for file_path in sorted(col_dir.glob("*.json"), reverse=True)[:limit]:
            docs.append(json.loads(file_path.read_text(encoding="utf-8")))
        return docs

    async def query_documents(
        self, collection: str, field: str, value: Any, limit: int = 100
    ) -> list[dict]:
        """Simple query by field value."""
        docs = await self.list_documents(collection, limit=1000)
        return [d for d in docs if d.get(field) == value][:limit]


class FirestoreClient:
    """
    Google Cloud Firestore client.
    Falls back to local storage if Firestore SDK is not available.
    """

    def __init__(self, project: str = "", database: str = "(default)"):
        self._db = None
        self._local_client: LocalFirestoreClient | None = None

        try:
            from google.cloud import firestore

            if project:
                self._db = firestore.AsyncClient(project=project, database=database)
            else:
                self._db = firestore.AsyncClient(database=database)
            logger.info("Connected to Google Cloud Firestore")
        except Exception as e:
            logger.warning(f"Firestore SDK not available, using local storage: {e}")
            self._local_client = LocalFirestoreClient()

    @property
    def is_cloud(self) -> bool:
        return self._db is not None

    async def add_document(self, collection: str, data: dict, doc_id: str | None = None) -> str:
        """Add a document to a collection."""
        if self._local_client:
            return await self._local_client.add_document(collection, data, doc_id)

        data["created_at"] = datetime.now(timezone.utc)
        data["updated_at"] = datetime.now(timezone.utc)

        if doc_id:
            await self._db.collection(collection).document(doc_id).set(data)
            return doc_id
        else:
            doc_ref = self._db.collection(collection).document()
            data["id"] = doc_ref.id
            await doc_ref.set(data)
            return doc_ref.id

    async def get_document(self, collection: str, doc_id: str) -> dict | None:
        """Get a document by ID."""
        if self._local_client:
            return await self._local_client.get_document(collection, doc_id)

        doc = await self._db.collection(collection).document(doc_id).get()
        if doc.exists:
            return doc.to_dict()
        return None

    async def update_document(self, collection: str, doc_id: str, data: dict) -> bool:
        """Update an existing document."""
        if self._local_client:
            return await self._local_client.update_document(collection, doc_id, data)

        data["updated_at"] = datetime.now(timezone.utc)
        try:
            await self._db.collection(collection).document(doc_id).update(data)
            return True
        except Exception:
            return False

    async def delete_document(self, collection: str, doc_id: str) -> bool:
        """Delete a document."""
        if self._local_client:
            return await self._local_client.delete_document(collection, doc_id)

        try:
            await self._db.collection(collection).document(doc_id).delete()
            return True
        except Exception:
            return False

    async def list_documents(self, collection: str, limit: int = 100) -> list[dict]:
        """List documents in a collection."""
        if self._local_client:
            return await self._local_client.list_documents(collection, limit)

        docs = []
        query = self._db.collection(collection).limit(limit)
        async for doc in query.stream():
            doc_dict = doc.to_dict()
            doc_dict["id"] = doc.id
            docs.append(doc_dict)
        return docs

    async def query_documents(
        self, collection: str, field: str, value: Any, limit: int = 100
    ) -> list[dict]:
        """Query documents by field value."""
        if self._local_client:
            return await self._local_client.query_documents(collection, field, value, limit)

        docs = []
        query = (
            self._db.collection(collection)
            .where(field, "==", value)
            .limit(limit)
        )
        async for doc in query.stream():
            doc_dict = doc.to_dict()
            doc_dict["id"] = doc.id
            docs.append(doc_dict)
        return docs


# Global client instance (initialized lazily)
_firestore_client: FirestoreClient | None = None


def get_firestore_client() -> FirestoreClient:
    """Get or create the global Firestore client."""
    global _firestore_client
    if _firestore_client is None:
        from visionqa.backend.config import get_settings
        settings = get_settings()
        _firestore_client = FirestoreClient(
            project=settings.google_cloud_project,
            database=settings.firestore_database,
        )
    return _firestore_client
