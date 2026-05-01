from __future__ import annotations

from threading import Lock
from typing import Iterable
from uuid import uuid4

from .models import TaskRecord, VideoRecord, now_iso


class InMemoryStore:
    def __init__(self) -> None:
        self._videos: dict[str, VideoRecord] = {}
        self._tasks: dict[str, TaskRecord] = {}
        self._lock = Lock()

    def create_video(self, payload: dict) -> VideoRecord:
        with self._lock:
            video = VideoRecord(
                id=str(uuid4()),
                source_platform="bilibili",
                source_url=payload["source_url"],
                normalized_url=payload["normalized_url"],
                title=payload["title"],
                uploader=payload["uploader"],
                duration_sec=payload["duration_sec"],
                cover_url=payload["cover_url"],
                status="pending",
                source_type=payload["source_type"],
                bvid=payload["bvid"],
                cid=payload["cid"],
                series_title=payload.get("series_title"),
                series_index=payload.get("series_index"),
                series_total=payload.get("series_total"),
            )
            self._videos[video.id] = video
            return video

    def create_task(self, video_id: str, task_type: str = "transcribe") -> TaskRecord:
        with self._lock:
            retry_count = sum(1 for task in self._tasks.values() if task.video_id == video_id)
            task = TaskRecord(
                id=str(uuid4()),
                video_id=video_id,
                task_type=task_type,
                status="pending",
                progress=0,
                retry_count=retry_count,
            )
            self._tasks[task.id] = task
            video = self._videos[video_id]
            video.last_task_id = task.id
            video.updated_at = now_iso()
            return task

    def update_video(self, video_id: str, **changes: object) -> VideoRecord:
        with self._lock:
            video = self._videos[video_id]
            for key, value in changes.items():
                setattr(video, key, value)
            video.updated_at = now_iso()
            return video

    def update_task(self, task_id: str, **changes: object) -> TaskRecord:
        with self._lock:
            task = self._tasks[task_id]
            for key, value in changes.items():
                setattr(task, key, value)
            return task

    def list_videos(self) -> Iterable[VideoRecord]:
        return sorted(self._videos.values(), key=lambda item: item.created_at, reverse=True)

    def get_video(self, video_id: str) -> VideoRecord | None:
        return self._videos.get(video_id)

    def get_task(self, task_id: str | None) -> TaskRecord | None:
        if not task_id:
            return None
        return self._tasks.get(task_id)

    def delete_video(self, video_id: str) -> bool:
        with self._lock:
            video = self._videos.pop(video_id, None)
            if video is None:
                return False
            task_ids = [task_id for task_id, task in self._tasks.items() if task.video_id == video_id]
            for task_id in task_ids:
                self._tasks.pop(task_id, None)
            return True


store = InMemoryStore()
