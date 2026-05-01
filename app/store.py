from __future__ import annotations

import json
from threading import Lock
from typing import Iterable
from uuid import uuid4

from .config import settings
from .models import TaskRecord, VideoRecord, now_iso


class InMemoryStore:
    def __init__(self) -> None:
        self._videos: dict[str, VideoRecord] = {}
        self._tasks: dict[str, TaskRecord] = {}
        self._lock = Lock()
        self._store_path = settings.storage_dir / "workspace_store.json"
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if not self._store_path.exists():
            return

        payload = json.loads(self._store_path.read_text(encoding="utf-8"))
        videos = payload.get("videos") or {}
        tasks = payload.get("tasks") or {}
        self._videos = {video_id: VideoRecord(**video_payload) for video_id, video_payload in videos.items()}
        self._tasks = {task_id: TaskRecord(**task_payload) for task_id, task_payload in tasks.items()}
        self._recover_interrupted_tasks()

    def _recover_interrupted_tasks(self) -> None:
        active_statuses = {"pending", "checking", "downloading", "transcribing"}
        interrupted_at = now_iso()

        for task in self._tasks.values():
            if task.status not in active_statuses:
                continue
            task.status = "failed"
            task.progress = 100
            task.finished_at = interrupted_at
            task.error_message = "服务重启导致任务中断，请重新处理。"

        for video in self._videos.values():
            if video.status not in active_statuses:
                continue
            video.status = "failed"
            video.error_message = "服务重启导致任务中断，请重新处理。"
            if "服务重启导致任务中断，请重新处理。" not in video.processing_notes:
                video.processing_notes.append("服务重启导致任务中断，请重新处理。")
            video.updated_at = interrupted_at

        self._persist()

    def _persist(self) -> None:
        payload = {
            "videos": {video_id: video.to_dict() for video_id, video in self._videos.items()},
            "tasks": {task_id: task.to_dict() for task_id, task in self._tasks.items()},
        }
        self._store_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

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
            self._persist()
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
            self._persist()
            return task

    def update_video(self, video_id: str, **changes: object) -> VideoRecord:
        with self._lock:
            video = self._videos[video_id]
            for key, value in changes.items():
                setattr(video, key, value)
            video.updated_at = now_iso()
            self._persist()
            return video

    def update_task(self, task_id: str, **changes: object) -> TaskRecord:
        with self._lock:
            task = self._tasks[task_id]
            for key, value in changes.items():
                setattr(task, key, value)
            self._persist()
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
            self._persist()
            return True


store = InMemoryStore()
