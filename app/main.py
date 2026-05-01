from __future__ import annotations

from pathlib import Path
from threading import Event, Lock, Thread

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .models import now_iso
from .schemas import (
    BilibiliCheckRequest,
    BilibiliCheckResponse,
    BilibiliProcessItem,
    BilibiliProcessRequest,
    BilibiliProcessResponse,
    CheckedVideoItem,
    TaskSummary,
    VideoDetailResponse,
    VideoSummary,
)
from .services.bilibili import check_bilibili_source, check_bilibili_source_real, has_real_backend
from .services.transcript_pipeline import run_demo_pipeline, run_real_pipeline
from .store import store


app = FastAPI(title=settings.app_name, version="0.1.0")
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")

ACTIVE_TASK_STATUSES = {"pending", "checking", "downloading", "transcribing"}
INTERRUPTED_MESSAGE = "服务停止导致任务中断，请重新处理。"
shutdown_event = Event()
active_jobs_lock = Lock()
active_jobs: dict[str, str] = {}


def build_task_summary(task) -> TaskSummary:
    return TaskSummary(**task.to_dict())


def build_video_summary(video) -> VideoSummary:
    task = store.get_task(video.last_task_id)
    payload = {
        "id": video.id,
        "title": video.title,
        "status": video.status,
        "source_type": video.source_type,
        "source_url": video.source_url,
        "duration_sec": video.duration_sec,
        "uploader": video.uploader,
        "cover_url": video.cover_url,
        "created_at": video.created_at,
        "updated_at": video.updated_at,
        "last_task_id": video.last_task_id,
        "last_task": build_task_summary(task) if task else None,
    }
    return VideoSummary(**payload)


def build_video_detail(video) -> VideoDetailResponse:
    task = store.get_task(video.last_task_id)
    payload = video.to_dict()
    payload["last_task"] = build_task_summary(task) if task else None
    return VideoDetailResponse(**payload)


def _track_job(task_id: str, video_id: str) -> None:
    with active_jobs_lock:
        active_jobs[task_id] = video_id


def _untrack_job(task_id: str) -> None:
    with active_jobs_lock:
        active_jobs.pop(task_id, None)


def _mark_job_interrupted(video_id: str, task_id: str) -> None:
    task = store.get_task(task_id)
    if task is not None and task.status in ACTIVE_TASK_STATUSES:
        store.update_task(
            task_id,
            status="failed",
            progress=100,
            finished_at=now_iso(),
            error_message=INTERRUPTED_MESSAGE,
        )

    video = store.get_video(video_id)
    if video is not None and video.status in ACTIVE_TASK_STATUSES:
        notes = list(video.processing_notes)
        if INTERRUPTED_MESSAGE not in notes:
            notes.append(INTERRUPTED_MESSAGE)
        store.update_video(
            video_id,
            status="failed",
            error_message=INTERRUPTED_MESSAGE,
            processing_notes=notes,
        )


def _mark_all_active_jobs_interrupted() -> None:
    with active_jobs_lock:
        job_pairs = list(active_jobs.items())
    for task_id, video_id in job_pairs:
        _mark_job_interrupted(video_id=video_id, task_id=task_id)


def _run_pipeline_job(video_id: str, task_id: str, generate_polish: bool, generate_summary: bool) -> None:
    _track_job(task_id=task_id, video_id=video_id)
    try:
        if shutdown_event.is_set():
            _mark_job_interrupted(video_id=video_id, task_id=task_id)
            return
        if settings.pipeline_mode == "real":
            run_real_pipeline(
                store=store,
                video_id=video_id,
                task_id=task_id,
                generate_polish=generate_polish,
                generate_summary=generate_summary,
            )
        else:
            run_demo_pipeline(
                store=store,
                video_id=video_id,
                task_id=task_id,
                generate_polish=generate_polish,
                generate_summary=generate_summary,
            )
    except BaseException as exc:
        if shutdown_event.is_set():
            _mark_job_interrupted(video_id=video_id, task_id=task_id)
            return
        if store.get_video(video_id) is not None:
            store.update_video(video_id, status="failed", error_message=str(exc))
        if store.get_task(task_id) is not None:
            store.update_task(task_id, status="failed", progress=100, finished_at=now_iso(), error_message=str(exc))
    finally:
        _untrack_job(task_id)


def _start_pipeline_job(video_id: str, task_id: str, generate_polish: bool, generate_summary: bool) -> None:
    worker = Thread(
        target=_run_pipeline_job,
        kwargs={
            "video_id": video_id,
            "task_id": task_id,
            "generate_polish": generate_polish,
            "generate_summary": generate_summary,
        },
        daemon=True,
    )
    worker.start()


@app.on_event("startup")
def on_startup() -> None:
    shutdown_event.clear()


@app.on_event("shutdown")
def on_shutdown() -> None:
    shutdown_event.set()
    _mark_all_active_jobs_interrupted()


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "demo_mode": settings.demo_mode,
        "pipeline_mode": settings.pipeline_mode,
        "real_backend_ready": has_real_backend(),
    }


@app.get("/")
def workspace() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.post("/api/v1/videos/bilibili/check", response_model=BilibiliCheckResponse)
def bilibili_check(payload: BilibiliCheckRequest) -> BilibiliCheckResponse:
    try:
        checked = check_bilibili_source_real(payload.url) if settings.pipeline_mode == "real" else check_bilibili_source(payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"校验失败：{exc}") from exc

    videos = [CheckedVideoItem(**item) for item in checked.videos]
    return BilibiliCheckResponse(
        normalized_url=checked.normalized_url,
        source_type=checked.source_type,
        video_count=len(videos),
        videos=videos,
    )


@app.post("/api/v1/videos/bilibili/process", response_model=BilibiliProcessResponse)
def bilibili_process(payload: BilibiliProcessRequest) -> BilibiliProcessResponse:
    try:
        checked = check_bilibili_source_real(payload.url) if settings.pipeline_mode == "real" else check_bilibili_source(payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"处理前校验失败：{exc}") from exc

    results: list[BilibiliProcessItem] = []
    for item in checked.videos:
        video = store.create_video(item)
        task = store.create_task(video.id)
        _start_pipeline_job(
            video_id=video.id,
            task_id=task.id,
            generate_polish=payload.generate_polish,
            generate_summary=payload.generate_summary,
        )
        results.append(
            BilibiliProcessItem(
                video_id=video.id,
                title=video.title,
                status=store.get_video(video.id).status,
                task=build_task_summary(store.get_task(task.id)),
            )
        )

    return BilibiliProcessResponse(
        normalized_url=checked.normalized_url,
        source_type=checked.source_type,
        video_count=len(results),
        videos=results,
    )


@app.get("/api/v1/videos", response_model=list[VideoSummary])
def list_videos() -> list[VideoSummary]:
    return [build_video_summary(video) for video in store.list_videos()]


@app.get("/api/v1/videos/{video_id}", response_model=VideoDetailResponse)
def get_video(video_id: str) -> VideoDetailResponse:
    video = store.get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="视频不存在。")
    return build_video_detail(video)


@app.post("/api/v1/videos/{video_id}/retry", response_model=VideoDetailResponse)
def retry_video(video_id: str) -> VideoDetailResponse:
    video = store.get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="视频不存在。")

    if video.status in {"pending", "checking", "downloading", "transcribing"}:
        raise HTTPException(status_code=409, detail="当前文件仍在处理中，请稍后再试。")

    task = store.create_task(video_id, task_type="retry_transcribe")
    _start_pipeline_job(
        video_id=video_id,
        task_id=task.id,
        generate_polish=True,
        generate_summary=True,
    )
    return build_video_detail(store.get_video(video_id))


@app.delete("/api/v1/videos/{video_id}")
def delete_video(video_id: str) -> dict[str, str]:
    video = store.get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="视频不存在。")

    if video.status in {"pending", "checking", "downloading", "transcribing"}:
        raise HTTPException(status_code=409, detail="当前文件仍在处理中，暂不支持删除。")

    store.delete_video(video_id)
    return {"status": "deleted", "video_id": video_id}
