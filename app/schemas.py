from __future__ import annotations

from pydantic import BaseModel, Field


class BilibiliCheckRequest(BaseModel):
    url: str = Field(..., description="B站视频、分P或合集链接")


class BilibiliProcessRequest(BaseModel):
    url: str = Field(..., description="B站视频、分P或合集链接")
    generate_polish: bool = True
    generate_summary: bool = True


class CheckedVideoItem(BaseModel):
    title: str
    source_url: str
    normalized_url: str
    source_type: str
    bvid: str
    cid: str
    uploader: str
    duration_sec: int
    cover_url: str
    series_title: str | None = None
    series_index: int | None = None
    series_total: int | None = None


class BilibiliCheckResponse(BaseModel):
    normalized_url: str
    source_type: str
    video_count: int
    videos: list[CheckedVideoItem]


class TaskSummary(BaseModel):
    id: str
    video_id: str
    task_type: str
    status: str
    progress: int
    retry_count: int
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    error_message: str | None = None


class VideoSummary(BaseModel):
    id: str
    title: str
    status: str
    source_type: str
    source_url: str
    duration_sec: int
    uploader: str
    cover_url: str
    created_at: str
    updated_at: str
    last_task_id: str | None = None
    last_task: TaskSummary | None = None


class BilibiliProcessItem(BaseModel):
    video_id: str
    title: str
    status: str
    task: TaskSummary


class BilibiliProcessResponse(BaseModel):
    normalized_url: str
    source_type: str
    video_count: int
    videos: list[BilibiliProcessItem]


class VideoDetailResponse(BaseModel):
    id: str
    title: str
    source_platform: str
    source_type: str
    source_url: str
    normalized_url: str
    bvid: str
    cid: str
    uploader: str
    duration_sec: int
    cover_url: str
    series_title: str | None = None
    series_index: int | None = None
    series_total: int | None = None
    status: str
    original_transcript: str
    polished_transcript: str
    transcript_with_timestamp: str
    summary_text: str
    outline_text: str
    tags: list[str]
    processing_notes: list[str]
    error_message: str | None = None
    last_task_id: str | None = None
    created_at: str
    updated_at: str
    last_task: TaskSummary | None = None
