from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class VideoRecord:
    id: str
    source_platform: str
    source_url: str
    normalized_url: str
    title: str
    uploader: str
    duration_sec: int
    cover_url: str
    status: str
    source_type: str
    bvid: str
    cid: str
    series_title: str | None = None
    series_index: int | None = None
    series_total: int | None = None
    original_transcript: str = ""
    polished_transcript: str = ""
    transcript_with_timestamp: str = ""
    summary_text: str = ""
    feynman_deep_text: str = ""
    key_points_text: str = ""
    outline_text: str = ""
    tags: list[str] = field(default_factory=list)
    processing_notes: list[str] = field(default_factory=list)
    error_message: str | None = None
    last_task_id: str | None = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class TaskRecord:
    id: str
    video_id: str
    task_type: str
    status: str
    progress: int
    retry_count: int
    created_at: str = field(default_factory=now_iso)
    started_at: str | None = None
    finished_at: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()
