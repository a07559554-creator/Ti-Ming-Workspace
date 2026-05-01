from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen
import json
import re

try:
    from yt_dlp import YoutubeDL
except ImportError:  # pragma: no cover - optional runtime dependency
    YoutubeDL = None

from ..config import settings
from ..models import now_iso
from ..store import InMemoryStore
from .llm_writer import StudyArtifacts, deepseek_enabled, generate_study_artifacts

try:
    from faster_whisper import WhisperModel
except ImportError:  # pragma: no cover - optional runtime dependency
    WhisperModel = None


def _format_timestamp(seconds: int) -> str:
    minutes, second = divmod(seconds, 60)
    hour, minute = divmod(minutes, 60)
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def _ensure_real_runtime() -> None:
    missing = []
    if WhisperModel is None:
        missing.append("faster-whisper")
    if YoutubeDL is None:
        missing.append("yt-dlp")
    if missing:
        raise RuntimeError(f"缺少真实转写依赖：{', '.join(missing)}")


def _clean_transcript_text(text: str) -> str:
    text = re.sub(r"\s+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _collect_sentence_candidates(text: str) -> list[str]:
    normalized = text.replace("\n", " ")
    parts = re.split(r"(?<=[。！？.!?])\s+", normalized)
    return [part.strip() for part in parts if len(part.strip()) > 30]


def _pick_key_sentences(text: str, limit: int = 4) -> list[str]:
    candidates = _collect_sentence_candidates(text)
    unique: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        compact = item[:120]
        if compact in seen:
            continue
        seen.add(compact)
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def _pick_focus_segments(segments: list[dict], limit: int = 4) -> list[dict]:
    picked: list[dict] = []
    for segment in segments:
        text = segment["text"].strip()
        if len(text) < 35:
            continue
        picked.append(segment)
        if len(picked) >= limit:
            break
    return picked or segments[:limit]


def _build_outline_from_segments(segments: list[dict]) -> str:
    lines = []
    for index, segment in enumerate(_pick_focus_segments(segments, limit=6), start=1):
        excerpt = segment["text"].strip().replace("\n", " ")
        if len(excerpt) > 42:
            excerpt = excerpt[:42].rstrip() + "..."
        lines.append(f"{index}. [{segment['start']}] {excerpt}")
    return "\n".join(lines)


def _build_summary_from_text(text: str, segments: list[dict]) -> str:
    key_sentences = _pick_key_sentences(text, limit=4)
    focus_segments = _pick_focus_segments(segments, limit=3)
    core_insight = key_sentences[0] if key_sentences else text[:180].strip()
    key_points = key_sentences[1:4] if len(key_sentences) > 1 else [segment["text"].strip() for segment in focus_segments[:3]]
    flow_lines = [
        f"{index}. [{segment['start']}] {segment['text'].strip()[:72].rstrip()}"
        for index, segment in enumerate(focus_segments, start=1)
    ]
    action_line = key_points[-1] if key_points else core_insight

    return "\n".join(
        [
            "【核心洞见】",
            core_insight,
            "",
            "【内容脉络】",
            *flow_lines,
            "",
            "【关键要点】",
            *[f"- {point}" for point in key_points],
            "",
            "【可行动观察】",
            f"- 如果要继续深挖这条视频，优先从这句展开：{action_line}",
        ]
    )


def _build_polished_transcript(text: str) -> str:
    sentences = _pick_key_sentences(text, limit=8)
    if not sentences:
        sentences = [line.strip() for line in text.splitlines() if line.strip()][:8]
    lead = sentences[0] if sentences else text[:180].strip()
    bullets = "\n".join(f"- {sentence}" for sentence in sentences[1:7])
    return "\n".join(
        [
            "【学习稿】",
            "",
            lead,
            "",
            "【展开理解】",
            bullets or "- 当前文稿较短，建议直接阅读原文。",
        ]
    )


def _build_timestamp_text(segments: list[dict]) -> str:
    return "\n".join(f"[{segment['start']}] {segment['text'].strip()}" for segment in segments)


def _pick_best_audio_format(formats: list[dict]) -> str | None:
    audio_only = [fmt for fmt in formats if fmt.get("vcodec") == "none" and fmt.get("acodec") != "none"]
    if not audio_only:
        return None
    audio_only.sort(key=lambda item: (item.get("filesize") or item.get("filesize_approx") or 10**12, item.get("abr") or 10**12))
    return str(audio_only[0]["format_id"])


def _download_audio(info: dict, target_dir: Path) -> tuple[Path, list[str]]:
    format_id = _pick_best_audio_format(info.get("formats") or [])
    if not format_id:
        raise RuntimeError("未找到可下载的音频格式。")

    target_dir.mkdir(parents=True, exist_ok=True)
    selected = next(fmt for fmt in info.get("formats", []) if str(fmt.get("format_id")) == format_id)
    audio_url = selected.get("url")
    if not audio_url:
        raise RuntimeError("解析到了音频格式，但未拿到可下载 URL。")

    ext = selected.get("ext") or "m4a"
    audio_path = target_dir / f"{info['id']}.{ext}"
    request = Request(audio_url, headers=selected.get("http_headers") or {})
    with urlopen(request) as response, audio_path.open("wb") as file_handle:  # nosec - yt-dlp resolved URL
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            file_handle.write(chunk)

    note = f"已下载真实音频格式 {format_id}，文件 {audio_path.name}"
    return audio_path, [note]


def _try_fetch_subtitle_text(info: dict) -> tuple[str | None, list[str]]:
    subtitles = info.get("subtitles") or {}
    automatic = info.get("automatic_captions") or {}
    notes: list[str] = []
    for source_name, source in (("subtitles", subtitles), ("automatic_captions", automatic)):
        for lang in ("zh-CN", "zh-Hans", "zh", "en"):
            entries = source.get(lang) or []
            for entry in entries:
                subtitle_url = entry.get("url")
                ext = entry.get("ext")
                if not subtitle_url or ext not in {"json3", "vtt", "srt"}:
                    continue
                with urlopen(subtitle_url) as response:  # nosec - yt-dlp provided URL
                    payload = response.read().decode("utf-8", errors="ignore")
                if ext == "json3":
                    data = json.loads(payload)
                    events = data.get("events") or []
                    lines = []
                    for event in events:
                        text = "".join(item.get("utf8", "") for item in event.get("segs") or [])
                        if text.strip():
                            lines.append(text.strip())
                    if lines:
                        notes.append(f"已使用 {source_name}:{lang} 的远程字幕。")
                        return "\n".join(lines), notes
                else:
                    text = re.sub(r"<[^>]+>", "", payload)
                    text = re.sub(r"\d+\n\d{2}:\d{2}:\d{2}.*?\n", "", text)
                    text = _clean_transcript_text(text)
                    if text:
                        notes.append(f"已使用 {source_name}:{lang} 的远程字幕。")
                        return text, notes
    notes.append("未获取到正式字幕，改走本地音频转写。")
    return None, notes


def _transcribe_audio(audio_path: Path) -> tuple[str, list[dict], list[str]]:
    if WhisperModel is None:
        raise RuntimeError("未安装 faster-whisper，无法执行本地 ASR。")
    model = WhisperModel(settings.whisper_model, device="cpu", compute_type="int8", download_root=str(settings.model_dir))
    language_arg = None if settings.default_language in {"auto", "", None} else settings.default_language
    segments, info = model.transcribe(str(audio_path), language=language_arg, vad_filter=True, beam_size=1)
    segment_rows = []
    transcript_lines = []
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        segment_rows.append(
            {
                "start": _format_timestamp(int(segment.start)),
                "end": _format_timestamp(int(segment.end)),
                "text": text,
            }
        )
        transcript_lines.append(text)
    notes = [
        f"已使用 faster-whisper {settings.whisper_model} 模型执行本地 ASR。",
        f"检测语言：{getattr(info, 'language', settings.default_language)}",
    ]
    return "\n\n".join(transcript_lines), segment_rows, notes


def _build_demo_transcript(title: str) -> tuple[str, str, str, str, str, list[str]]:
    sections = [
        f"{title} 主要讨论如何把学习视频转成可沉淀的知识文件。",
        "第一步是拿到稳定的视频来源与元信息，确保任务不会在入口层就失败。",
        "第二步是获取音频并完成转写，把口语内容还原成可用文稿。",
        "第三步是进行清洗与摘要，把原始文稿变成更适合阅读与复习的版本。",
        "第四步是把结果存成知识文件，方便后续搜索、问答和导出。",
    ]
    original = "\n\n".join(sections)
    polished = (
        f"【学习稿】{title}\n\n"
        "这个视频的核心价值，在于展示如何把长视频内容整理成可复用的学习资产。\n\n"
        + "\n".join(f"- {line}" for line in sections[1:])
    )
    timestamped = "\n".join(
        f"[{_format_timestamp(index * 120)}] {line}" for index, line in enumerate(sections, start=0)
    )
    summary = (
        "这条视频适合做转文稿工具的演示样本。"
        "它覆盖了入口校验、音频转写、文稿清洗、知识文件沉淀四个核心阶段。"
    )
    outline = "\n".join(
        [
            "1. 入口校验",
            "2. 音频获取",
            "3. 转写生成",
            "4. AI 清洗与摘要",
            "5. 文件化沉淀",
        ]
    )
    tags = ["视频转文稿", "学习工作台", "知识文件"]
    return original, polished, timestamped, summary, outline, tags


def _build_study_outputs(
    *,
    title: str,
    uploader: str,
    duration_sec: int,
    transcript_text: str,
    segment_rows: list[dict],
    generate_polish: bool,
    generate_summary: bool,
) -> tuple[str, str, str, list[str], list[str]]:
    fallback_polished = _build_polished_transcript(transcript_text) if generate_polish else ""
    fallback_summary = _build_summary_from_text(transcript_text, segment_rows) if generate_summary else ""
    fallback_outline = _build_outline_from_segments(segment_rows) if generate_summary else ""
    fallback_tags = ["真实转写", "B站视频", "知识文件"]

    if not deepseek_enabled():
        return fallback_polished, fallback_summary, fallback_outline, fallback_tags, []

    try:
        artifacts: StudyArtifacts = generate_study_artifacts(
            title=title,
            uploader=uploader,
            duration_sec=duration_sec,
            transcript_text=transcript_text,
            segments=segment_rows,
        )
    except Exception as exc:
        return (
            fallback_polished,
            fallback_summary,
            fallback_outline,
            fallback_tags,
            [f"DeepSeek 生成失败，已回退到规则版学习稿：{exc}"],
        )

    polished = artifacts.polished_transcript if generate_polish else ""
    summary = artifacts.summary_text if generate_summary else ""
    outline = artifacts.outline_text if generate_summary else ""
    tags = artifacts.tags or fallback_tags
    return polished, summary, outline, tags, [f"已使用 DeepSeek 模型 {settings.llm_model} 生成学习稿。"]


def run_demo_pipeline(store: InMemoryStore, video_id: str, task_id: str, generate_polish: bool, generate_summary: bool) -> None:
    store.update_video(video_id, status="checking", error_message=None)
    store.update_task(task_id, status="checking", progress=10, started_at=now_iso())

    store.update_video(video_id, status="transcribing")
    store.update_task(task_id, status="transcribing", progress=45)

    video = store.get_video(video_id)
    if video is None:
        raise ValueError(f"视频不存在: {video_id}")

    original, polished, timestamped, summary, outline, tags = _build_demo_transcript(video.title)

    store.update_video(
        video_id,
        status="completed",
        original_transcript=original,
        polished_transcript=polished if generate_polish else "",
        transcript_with_timestamp=timestamped,
        summary_text=summary if generate_summary else "",
        outline_text=outline if generate_summary else "",
        tags=tags,
    )
    store.update_task(task_id, status="completed", progress=100, finished_at=now_iso())


def run_real_pipeline(store: InMemoryStore, video_id: str, task_id: str, generate_polish: bool, generate_summary: bool) -> None:
    _ensure_real_runtime()

    video = store.get_video(video_id)
    if video is None:
        raise ValueError(f"视频不存在: {video_id}")

    store.update_video(video_id, status="checking", error_message=None, processing_notes=[])
    store.update_task(task_id, status="checking", progress=5, started_at=now_iso())

    with YoutubeDL({"skip_download": True, "quiet": True, "no_warnings": True}) as ydl:
        info = ydl.extract_info(video.normalized_url, download=False)

    subtitle_text, notes = _try_fetch_subtitle_text(info)
    all_notes = list(notes)
    store.update_task(task_id, status="downloading", progress=20)

    if subtitle_text:
        transcript_text = _clean_transcript_text(subtitle_text)
        segment_rows = [
            {"start": _format_timestamp(index * 15), "end": _format_timestamp(index * 15 + 15), "text": chunk.strip()}
            for index, chunk in enumerate([line for line in transcript_text.splitlines() if line.strip()])
        ]
    else:
        audio_path, download_notes = _download_audio(info, settings.download_dir / video.bvid)
        all_notes.extend(download_notes)
        store.update_task(task_id, status="transcribing", progress=55)
        transcript_text, segment_rows, asr_notes = _transcribe_audio(audio_path)
        all_notes.extend(asr_notes)

    transcript_text = _clean_transcript_text(transcript_text)
    timestamp_text = _build_timestamp_text(segment_rows)
    polished, summary, outline, tags, llm_notes = _build_study_outputs(
        title=video.title,
        uploader=video.uploader,
        duration_sec=video.duration_sec,
        transcript_text=transcript_text,
        segment_rows=segment_rows,
        generate_polish=generate_polish,
        generate_summary=generate_summary,
    )
    all_notes.extend(llm_notes)

    store.update_video(
        video_id,
        status="completed",
        original_transcript=transcript_text,
        polished_transcript=polished,
        transcript_with_timestamp=timestamp_text,
        summary_text=summary,
        outline_text=outline,
        tags=tags,
        processing_notes=all_notes,
    )
    store.update_task(task_id, status="completed", progress=100, finished_at=now_iso())
