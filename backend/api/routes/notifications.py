"""Notifications API endpoints.

Provides notification management including listing, marking as read, and deleting notifications.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path as PathLib
from typing import TYPE_CHECKING, Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from backend.core.logger import forge_logger as logger
from backend.api.user_auth import get_user_id
from backend.api.utils.pagination import PaginatedResponse, parse_pagination_params
from backend.api.utils.responses import error, success
from backend.utils.async_utils import call_sync_from_async

if TYPE_CHECKING:
    pass

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


class Notification(BaseModel):
    """Notification model."""

    id: str = Field(..., min_length=1, description="Notification identifier")
    user_id: str = Field(..., min_length=1, description="User identifier")
    type: str = Field(..., min_length=1, description="Notification type")
    title: str = Field(..., min_length=1, description="Notification title")
    message: str = Field(..., min_length=1, description="Notification message")
    read: bool = Field(default=False, description="Whether notification has been read")
    created_at: str = Field(..., min_length=1, description="ISO timestamp of creation")
    action_url: str | None = Field(None, description="Optional action URL")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )

    @field_validator("id", "user_id", "type", "title", "message", "created_at")
    @classmethod
    def validate_required_strings(cls, v: str) -> str:
        """Validate required string fields are non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name="field")


class NotificationStore:
    """Simple file-based notification store.

    In production, this should be migrated to a database.
    """

    def __init__(self, storage_path: str | None = None):
        """Initialize notification store.

        Args:
            storage_path: Path to notification storage directory
        """
        if storage_path is None:
            storage_path = os.path.join(os.getcwd(), ".forge", "notifications")
        self.storage_path = PathLib(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._notifications_cache: dict[str, list[Notification]] = {}
        self._load_notifications()

    def _get_user_file(self, user_id: str) -> PathLib:
        """Get notification file path for user.

        Args:
            user_id: User identifier

        Returns:
            Path to user's notification file
        """
        return self.storage_path / f"{user_id}.json"

    def _load_notifications(self) -> None:
        """Load all notifications from storage."""
        try:
            for file_path in self.storage_path.glob("*.json"):
                user_id = file_path.stem
                try:
                    with open(file_path, encoding="utf-8") as f:
                        data = json.load(f)
                        notifications = [
                            Notification(**n) for n in data.get("notifications", [])
                        ]
                        self._notifications_cache[user_id] = notifications
                except Exception as e:
                    logger.warning(
                        "Error loading notifications from %s: %s", file_path, e
                    )
        except Exception as e:
            logger.error("Error loading notifications: %s", e)

    def _save_notifications(self, user_id: str) -> None:
        """Save notifications for user to storage.

        Args:
            user_id: User identifier
        """
        file_path = self._get_user_file(user_id)
        try:
            notifications = self._notifications_cache.get(user_id, [])
            data = {
                "notifications": [n.model_dump() for n in notifications],
                "updated_at": datetime.now().isoformat(),
            }
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error("Error saving notifications for %s: %s", user_id, e)

    async def create_notification(
        self,
        user_id: str,
        type: str,
        title: str,
        message: str,
        action_url: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Notification:
        """Create a new notification.

        Args:
            user_id: User identifier
            type: Notification type
            title: Notification title
            message: Notification message
            action_url: Optional action URL
            metadata: Optional metadata

        Returns:
            Created notification
        """
        notification = Notification(
            id=str(uuid4()),
            user_id=user_id,
            type=type,
            title=title,
            message=message,
            read=False,
            created_at=datetime.now().isoformat(),
            action_url=action_url,
            metadata=metadata or {},
        )

        if user_id not in self._notifications_cache:
            self._notifications_cache[user_id] = []

        self._notifications_cache[user_id].append(notification)
        await call_sync_from_async(self._save_notifications, user_id)

        logger.info("Created notification %s for user %s", notification.id, user_id)
        return notification

    async def get_notifications(
        self,
        user_id: str,
        read: bool | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Notification]:
        """Get notifications for user.

        Args:
            user_id: User identifier
            read: Filter by read status (None for all)
            limit: Maximum number of notifications
            offset: Offset for pagination

        Returns:
            List of notifications
        """
        notifications = self._notifications_cache.get(user_id, [])

        # Filter by read status
        if read is not None:
            notifications = [n for n in notifications if n.read == read]

        # Sort by created_at descending
        notifications.sort(key=lambda n: n.created_at, reverse=True)

        # Apply pagination
        if offset > 0:
            notifications = notifications[offset:]
        if limit:
            notifications = notifications[:limit]

        return notifications

    async def get_unread_count(self, user_id: str) -> int:
        """Get unread notification count for user.

        Args:
            user_id: User identifier

        Returns:
            Number of unread notifications
        """
        notifications = self._notifications_cache.get(user_id, [])
        return sum(1 for n in notifications if not n.read)

    async def mark_as_read(self, user_id: str, notification_id: str) -> bool:
        """Mark notification as read.

        Args:
            user_id: User identifier
            notification_id: Notification ID

        Returns:
            True if notification was found and updated
        """
        notifications = self._notifications_cache.get(user_id, [])
        for notification in notifications:
            if notification.id == notification_id:
                notification.read = True
                await call_sync_from_async(self._save_notifications, user_id)
                return True
        return False

    async def mark_all_as_read(self, user_id: str) -> int:
        """Mark all notifications as read for user.

        Args:
            user_id: User identifier

        Returns:
            Number of notifications marked as read
        """
        notifications = self._notifications_cache.get(user_id, [])
        count = 0
        for notification in notifications:
            if not notification.read:
                notification.read = True
                count += 1

        if count > 0:
            await call_sync_from_async(self._save_notifications, user_id)

        return count

    async def delete_notification(self, user_id: str, notification_id: str) -> bool:
        """Delete a notification.

        Args:
            user_id: User identifier
            notification_id: Notification ID

        Returns:
            True if notification was found and deleted
        """
        notifications = self._notifications_cache.get(user_id, [])
        for i, notification in enumerate(notifications):
            if notification.id == notification_id:
                notifications.pop(i)
                await call_sync_from_async(self._save_notifications, user_id)
                return True
        return False


# Global notification store instance
_notification_store: NotificationStore | None = None


def get_notification_store() -> NotificationStore:
    """Get or create global notification store instance.

    Returns:
        NotificationStore instance
    """
    global _notification_store
    if _notification_store is None:
        storage_path = os.getenv("NOTIFICATION_STORAGE_PATH")
        _notification_store = NotificationStore(storage_path=storage_path)
    return _notification_store


@router.get("", response_model=None)
async def list_notifications(
    request: Request,
    user_id: str = Depends(get_user_id),
    read: bool | None = Query(None, description="Filter by read status"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> JSONResponse | PaginatedResponse[dict]:
    """List notifications for the current user.

    Args:
        request: FastAPI request
        user_id: User identifier (from dependency)
        read: Filter by read status (None for all)
        page: Page number
        limit: Items per page

    Returns:
        Paginated list of notifications
    """
    try:
        store = get_notification_store()
        params = parse_pagination_params(page=page, limit=limit)

        notifications = await store.get_notifications(
            user_id,
            read=read,
            limit=params.limit,
            offset=params.offset,
        )

        # Get total count
        all_notifications = await store.get_notifications(user_id, read=read)
        total = len(all_notifications)

        return PaginatedResponse.create(
            items=[n.model_dump() for n in notifications],
            page=params.page,
            limit=params.limit,
            total=total,
        )
        # PaginatedResponse is a Pydantic model, FastAPI can serialize it directly

    except Exception as e:
        logger.error("Error listing notifications: %s", e, exc_info=True)
        return error(
            message="Failed to load notifications",
            error_code="NOTIFICATIONS_ERROR",
            request=request,
            status_code=500,
        )


@router.get("/unread-count")
async def get_unread_count(
    request: Request,
    user_id: str = Depends(get_user_id),
) -> JSONResponse:
    """Get unread notification count.

    Args:
        request: FastAPI request
        user_id: User identifier (from dependency)

    Returns:
        Unread notification count
    """
    try:
        store = get_notification_store()
        count = await store.get_unread_count(user_id)

        return success(
            data={"unread_count": count},
            request=request,
        )

    except Exception as e:
        logger.error("Error getting unread count: %s", e, exc_info=True)
        return error(
            message="Failed to get unread count",
            error_code="NOTIFICATIONS_ERROR",
            request=request,
            status_code=500,
        )


@router.get("/{notification_id}")
async def get_notification(
    request: Request,
    notification_id: str,
    user_id: str = Depends(get_user_id),
) -> JSONResponse:
    """Get a specific notification.

    Args:
        request: FastAPI request
        notification_id: Notification ID
        user_id: User identifier (from dependency)

    Returns:
        Notification details
    """
    try:
        store = get_notification_store()
        notifications = await store.get_notifications(user_id)

        for notification in notifications:
            if notification.id == notification_id:
                return success(
                    data=notification.model_dump(),
                    request=request,
                )

        return error(
            message="Notification not found",
            error_code="NOTIFICATION_NOT_FOUND",
            request=request,
            status_code=404,
        )

    except Exception as e:
        logger.error("Error getting notification: %s", e, exc_info=True)
        return error(
            message="Failed to get notification",
            error_code="NOTIFICATIONS_ERROR",
            request=request,
            status_code=500,
        )


@router.patch("/{notification_id}/read")
async def mark_notification_as_read(
    request: Request,
    notification_id: str,
    user_id: str = Depends(get_user_id),
) -> JSONResponse:
    """Mark a notification as read.

    Args:
        request: FastAPI request
        notification_id: Notification ID
        user_id: User identifier (from dependency)

    Returns:
        Success message
    """
    try:
        store = get_notification_store()
        success_flag = await store.mark_as_read(user_id, notification_id)

        if not success_flag:
            return error(
                message="Notification not found",
                error_code="NOTIFICATION_NOT_FOUND",
                request=request,
                status_code=404,
            )

        return success(
            message="Notification marked as read",
            request=request,
        )

    except Exception as e:
        logger.error("Error marking notification as read: %s", e, exc_info=True)
        return error(
            message="Failed to mark notification as read",
            error_code="NOTIFICATIONS_ERROR",
            request=request,
            status_code=500,
        )


@router.patch("/read-all")
async def mark_all_as_read(
    request: Request,
    user_id: str = Depends(get_user_id),
) -> JSONResponse:
    """Mark all notifications as read.

    Args:
        request: FastAPI request
        user_id: User identifier (from dependency)

    Returns:
        Success message with count
    """
    try:
        store = get_notification_store()
        count = await store.mark_all_as_read(user_id)

        return success(
            data={"marked_count": count},
            message=f"Marked {count} notifications as read",
            request=request,
        )

    except Exception as e:
        logger.error("Error marking all as read: %s", e, exc_info=True)
        return error(
            message="Failed to mark all notifications as read",
            error_code="NOTIFICATIONS_ERROR",
            request=request,
            status_code=500,
        )


@router.delete("/{notification_id}")
async def delete_notification(
    request: Request,
    notification_id: Annotated[
        str, Path(..., min_length=1, description="Notification ID")
    ],
    user_id: str = Depends(get_user_id),
) -> JSONResponse:
    """Delete a notification.

    Args:
        request: FastAPI request
        notification_id: Notification ID
        user_id: User identifier (from dependency)

    Returns:
        Success message
    """
    try:
        store = get_notification_store()
        success_flag = await store.delete_notification(user_id, notification_id)

        if not success_flag:
            return error(
                message="Notification not found",
                error_code="NOTIFICATION_NOT_FOUND",
                request=request,
                status_code=404,
            )

        return success(
            message="Notification deleted",
            request=request,
        )

    except Exception as e:
        logger.error("Error deleting notification: %s", e, exc_info=True)
        return error(
            message="Failed to delete notification",
            error_code="NOTIFICATIONS_ERROR",
            request=request,
            status_code=500,
        )
