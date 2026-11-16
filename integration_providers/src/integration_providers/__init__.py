"""Unified Providers factory for mail/calendar integrations."""

from .base import CalendarWriter
from .files import (
    FileInfo,
    FileStore,
    FileStoreError,
    FolderInfo,
    StoreCheck,
    UploadTarget,
    open_file_store,
)
from .models import (
    BusyItem,
    CalendarEventItem,
    CalendarItem,
    CalendarRefItem,
    CalendarSyncResult,
    EmailItem,
    EventWrite,
    FreeBusyResult,
    WriteResult,
)
from .registry import Providers

__all__ = [
    "BusyItem",
    "CalendarEventItem",
    "CalendarItem",
    "CalendarRefItem",
    "CalendarSyncResult",
    "CalendarWriter",
    "EmailItem",
    "EventWrite",
    "FileInfo",
    "FileStore",
    "FileStoreError",
    "FolderInfo",
    "FreeBusyResult",
    "Providers",
    "StoreCheck",
    "UploadTarget",
    "WriteResult",
    "open_file_store",
]

__version__ = "0.1.0"
