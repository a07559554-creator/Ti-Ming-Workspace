from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen
import json
import re

from yt_dlp import YoutubeDL

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
            "## 核心洞见",
            core_insight,
            "",
            "## 为什么重要",
            "这条内容值得学，不在于信息量大，而在于它给出了一个可迁移的判断框架或问题视角。",
            "",
            "## 学习目标",
            "- 说清这条视频的核心结论。",
            "- 理解内容是如何一步步展开的。",
            "- 知道自己接下来该从哪一点继续深挖。",
            "",
            "## 快速掌握",
            *flow_lines,
            "",
            "## 可立即应用",
            *[f"- {point}" for point in key_points],
            f"- 如果要继续深挖这条视频，优先从这句展开：{action_line}",
        ]
    )


def _build_feynman_deep_from_text(text: str, segments: list[dict]) -> str:
    key_sentences = _pick_key_sentences(text, limit=6)
    focus_segments = _pick_focus_segments(segments, limit=4)
    core_insight = key_sentences[0] if key_sentences else text[:180].strip()
    support_points = key_sentences[1:4] if len(key_sentences) > 1 else [segment["text"].strip() for segment in focus_segments[:3]]
    concept_seed = support_points[0] if support_points else core_insight
    misconception_seed = support_points[1] if len(support_points) > 1 else "不要把这条内容只理解成表面观点，更要看它背后的判断逻辑。"
    action_seed = support_points[-1] if support_points else core_insight
    distilled_points = [f"- {point}" for point in support_points] if support_points else [f"- {core_insight}"]
    concept_distinction = (
        support_points[1] if len(support_points) > 1 else "它关注的不是表面现象本身，而是驱动现象出现的底层机制。"
    )
    misconception_reason = (
        support_points[2] if len(support_points) > 2 else "因为学习者很容易停留在结论层，而忽略论证路径、适用边界和反例。"
    )
    logic_rows = [
        f"{index}. [{segment['start']}] {segment['text'].strip()[:88].rstrip()}"
        for index, segment in enumerate(focus_segments, start=1)
    ]

    return "\n".join(
        [
            "## 核心洞见（顶层结论）",
            core_insight,
            "",
            "## 为什么这个洞见重要",
            "它不是单纯复述内容，而是在帮我们抽出一个可复用的理解框架，方便后续迁移到学习、工作和判断里。",
            "",
            "## 学习目标",
            "- 能用自己的话解释视频最核心的结论。",
            "- 能说清视频的展开顺序与关键支撑点。",
            "- 能把其中至少一个观点迁移到真实场景中。",
            "",
            "## 核心知识点",
            f"- 核心观点：{core_insight}",
            f"- 支撑信息：{support_points[0] if support_points else core_insight}",
            f"- 延展线索：{support_points[1] if len(support_points) > 1 else action_seed}",
            "",
            "## 1. 背景与问题",
            "这条视频试图回答的，不只是一个表层问题，而是背后更深的原因、机制或选择逻辑。",
            f"当前内容中最值得追的问题是：{core_insight}",
            "",
            "## 2. 核心概念",
            "### 概念 1",
            f"- 生活比喻：可以把它理解成你在现实里反复遇到、但不一定会命名的那类问题。",
            f"- 一句话定义：{concept_seed}",
            f"- 核心要点：{support_points[0] if support_points else core_insight}",
            f"- 与相近概念的区分：{concept_distinction}",
            f"- 常见误区：{misconception_seed}",
            f"- 为什么容易误解：{misconception_reason}",
            f"- 实际应用：优先把它用在你当前最接近的视频、项目或判断场景里。",
            "",
            "## 3. 逻辑关系",
            *logic_rows,
            "",
            "## 4. 关键要点提炼",
            *distilled_points,
            "",
            "## 5. 盲点识别",
            f"- 容易把“{core_insight}”误解成一个漂亮结论，却忽略它成立所依赖的前提。",
            f"- 容易把“{concept_seed}”和相近概念混在一起，结果会在应用时套错场景。",
            "- 容易只记住作者的措辞或案例，而没有真正理解因果链条、适用边界和反例。",
            "",
            "## 6. 实践行动",
            f"1. 先用 30 秒复述这条视频最重要的一句话：{core_insight}",
            f"2. 再拿一个你当前正在处理的真实场景去验证：{action_seed}",
            "3. 最后把验证结果改写成一条你以后能重复使用的判断原则。",
            "",
            "检查标准：如果你能脱离原视频，用自己的语言解释它，并且知道在什么场景下该用、什么场景下不该用，就算真正掌握。",
            "",
            "## 7. 费曼自测",
            f"- 一句话复述：如果只给你一句话，你会怎么解释“{core_insight}”？",
            f"- 概念区分：你能说清“{concept_seed}”和它最容易混淆的概念差别吗？",
            f"- 场景应用：如果你在真实工作或学习里遇到“{action_seed}”这种情况，你会怎么用今天的结论做判断？",
            "",
            "## 查理·芒格视角",
            f"- 反向思考：如果想把这条视频里的结论彻底做反，你最可能会做出什么错误动作？这能帮助你看到失败路径。",
            f"- 激励机制：围绕“{concept_seed}”，谁的激励在推动这件事发生，谁又会因为激励错位而做出短视决策？",
            f"- 机会成本：如果你选择忽略“{core_insight}”，你实际放弃的是什么？",
            f"- 二阶效应：短期看“{action_seed}”也许只是一个动作，但长期会带来什么连锁后果？",
            "- 能力圈：这条视频最值得你吸收的部分是什么，哪些内容则应该只当作启发而不是立即照搬？",
            "",
            "## 知识点总结",
            f"- 顶层结论：{core_insight}",
            f"- 关键支撑：{support_points[0] if support_points else core_insight}",
            f"- 应用提醒：{action_seed}",
            "- 检查标准：你是否已经能用自己的语言复述，而不是只会引用原句。",
        ]
    )


def _build_key_points_text(text: str, segments: list[dict]) -> str:
    key_sentences = _pick_key_sentences(text, limit=5)
    focus_segments = _pick_focus_segments(segments, limit=3)
    points = key_sentences[:4] or [segment["text"].strip() for segment in focus_segments]
    logic_rows = [
        f"{index}. [{segment['start']}] {segment['text'].strip()[:88].rstrip()}"
        for index, segment in enumerate(focus_segments, start=1)
    ]
    closing = points[0] if points else text[:120].strip()

    return "\n".join(
        [
            "## 核心知识点",
            *[f"- {point}" for point in points],
            "",
            "## 逻辑主线",
            *logic_rows,
            "",
            "## 适用场景",
            "- 用来快速回看一条长视频的核心判断。",
            "- 用来整理复盘笔记、知识卡片或分享提纲。",
            "- 用来给后续 AI 问答准备更稳定的知识骨架。",
            "",
            "## 一句话回顾",
            closing,
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


def _build_demo_transcript(title: str) -> tuple[str, str, str, str, str, str, str, list[str]]:
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
    feynman_quick = "\n".join(
        [
            "## 核心洞见",
            "把视频转成文稿只是第一步，真正有价值的是把文稿继续整理成可学习、可复用的知识文件。",
            "",
            "## 为什么重要",
            "这样你不需要反复回看长视频，也能抓住核心内容并继续加工。",
            "",
            "## 学习目标",
            "- 理解转文稿工具的最小闭环。",
            "- 认出从原始文稿到知识文件之间的加工层。",
            "- 知道这个闭环后续还能接问答和导出。",
            "",
            "## 快速掌握",
            "1. 先拿到稳定的视频来源与元信息。",
            "2. 再把语音还原成可读文稿。",
            "3. 最后把文稿整理成知识文件。",
            "",
            "## 可立即应用",
            "- 先用一条真实视频验证从链接到文稿是否稳定。",
            "- 再判断哪些结果层值得放进你的学习库。",
        ]
    )
    feynman_deep = "\n".join(
        [
            "## 核心洞见（顶层结论）",
            "视频转文稿工具的真正价值，不在于转写本身，而在于把语音内容进一步变成可读、可查、可再利用的知识文件。",
            "",
            "## 为什么这个洞见重要",
            "如果只有原始文稿，用户还是得自己提炼重点；但一旦变成结构化学习稿，它就能进入知识库和问答链路。",
            "",
            "## 学习目标",
            "- 理解转文稿只是知识处理链路的起点。",
            "- 区分原文、润色稿、学习稿、知识点稿的角色。",
            "- 知道后续如何把它接进学习库工作流。",
            "",
            "## 核心知识点",
            "- 原始文稿：保留完整内容。",
            "- AI 润色版：提高可读性。",
            "- 学习稿：帮助快速掌握与复习。",
            "",
            "## 1. 背景与问题",
            "长视频难以快速消化，最大的阻力不是拿不到内容，而是拿到之后没有结构。",
            "",
            "## 2. 核心概念",
            "### 知识文件",
            "- 生活比喻：就像把一段原始录音整理成可以反复查阅的课程笔记。",
            "- 一句话定义：把视频内容沉淀成统一结构的可复用文档对象。",
            "- 核心要点：有原文、有学习稿、有知识点、有后续动作。",
            "- 常见误区：以为只要有字幕就等于完成知识沉淀。",
            "- 实际应用：用在学习视频、访谈、课程回顾和资料归档。",
            "",
            "## 3. 逻辑关系",
            "1. 链接解析 -> 拿到稳定来源。",
            "2. 音频转写 -> 生成原始文稿。",
            "3. 文稿加工 -> 生成学习稿和知识点。",
            "4. 文件沉淀 -> 支撑问答、导出和复用。",
            "",
            "## 4. 关键要点提炼",
            "- 转写只解决“听不完”的问题。",
            "- 学习稿解决“记不住”的问题。",
            "- 知识点稿解决“用不起来”的问题。",
            "",
            "## 5. 盲点识别",
            "- 不要把字幕结果误当成最终产品。",
            "- 不要忽略时间戳和结构层对复习效率的提升。",
            "",
            "## 6. 实践行动",
            "- 先选一条视频跑通完整链路。",
            "- 再决定哪些输出最适合你的学习库。",
            "- 最后把结果接到搜索、问答和导出里。",
            "",
            "## 7. 费曼自测",
            "- 你能解释为什么原始文稿还不够吗？",
            "- 你能说清学习稿和知识点稿的差别吗？",
            "",
            "## 知识点总结",
            "- 顶层结论：文稿只是起点，知识文件才是目标。",
            "- 关键逻辑：转写 -> 加工 -> 沉淀 -> 复用。",
            "- 应用提醒：先做最小闭环，再加高级能力。",
        ]
    )
    key_points = "\n".join(
        [
            "## 核心知识点",
            "- 原始文稿负责完整留存。",
            "- AI 润色版负责提升可读性。",
            "- 学习稿负责帮助快速掌握。",
            "- 知识点稿负责抽出最稳定的知识骨架。",
            "",
            "## 逻辑主线",
            "1. 导入视频。",
            "2. 获取文稿。",
            "3. 生成学习结果。",
            "4. 存成知识文件。",
            "",
            "## 适用场景",
            "- 学习视频整理。",
            "- 访谈知识沉淀。",
            "- 长内容复盘与分享。",
            "",
            "## 一句话回顾",
            "真正值得做的不是转文稿，而是把视频变成知识文件。",
        ]
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
    return original, polished, timestamped, feynman_quick, feynman_deep, key_points, outline, tags
def _build_study_outputs(
    *,
    title: str,
    uploader: str,
    duration_sec: int,
    transcript_text: str,
    segment_rows: list[dict],
    generate_polish: bool,
    generate_summary: bool,
) -> tuple[str, str, str, str, str, list[str], list[str]]:
    fallback_polished = _build_polished_transcript(transcript_text) if generate_polish else ""
    fallback_summary = _build_summary_from_text(transcript_text, segment_rows) if generate_summary else ""
    fallback_feynman_deep = _build_feynman_deep_from_text(transcript_text, segment_rows) if generate_summary else ""
    fallback_key_points = _build_key_points_text(transcript_text, segment_rows) if generate_summary else ""
    fallback_outline = _build_outline_from_segments(segment_rows) if generate_summary else ""
    fallback_tags = ["真实转写", "B站视频", "知识文件"]

    if not deepseek_enabled():
        return (
            fallback_polished,
            fallback_summary,
            fallback_feynman_deep,
            fallback_key_points,
            fallback_outline,
            fallback_tags,
            [],
        )

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
            fallback_feynman_deep,
            fallback_key_points,
            fallback_outline,
            fallback_tags,
            [f"DeepSeek 生成失败，已回退到规则版学习稿：{exc}"],
        )

    polished = artifacts.polished_transcript if generate_polish else ""
    summary = artifacts.summary_text if generate_summary else ""
    feynman_deep = artifacts.feynman_deep_text if generate_summary else ""
    key_points = artifacts.key_points_text if generate_summary else ""
    outline = artifacts.outline_text if generate_summary else ""
    tags = artifacts.tags or fallback_tags
    return (
        polished,
        summary,
        feynman_deep,
        key_points,
        outline,
        tags,
        [f"已使用 DeepSeek 模型 {settings.llm_model} 生成学习稿与费曼教学模式。"],
    )


def run_demo_pipeline(store: InMemoryStore, video_id: str, task_id: str, generate_polish: bool, generate_summary: bool) -> None:
    store.update_video(video_id, status="checking", error_message=None)
    store.update_task(task_id, status="checking", progress=10, started_at=now_iso())

    store.update_video(video_id, status="transcribing")
    store.update_task(task_id, status="transcribing", progress=45)

    video = store.get_video(video_id)
    if video is None:
        raise ValueError(f"视频不存在: {video_id}")

    original, polished, timestamped, summary, feynman_deep, key_points, outline, tags = _build_demo_transcript(video.title)

    store.update_video(
        video_id,
        status="completed",
        original_transcript=original,
        polished_transcript=polished if generate_polish else "",
        transcript_with_timestamp=timestamped,
        summary_text=summary if generate_summary else "",
        feynman_deep_text=feynman_deep if generate_summary else "",
        key_points_text=key_points if generate_summary else "",
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
    polished, summary, feynman_deep, key_points, outline, tags, llm_notes = _build_study_outputs(
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
        feynman_deep_text=feynman_deep,
        key_points_text=key_points,
        outline_text=outline,
        tags=tags,
        processing_notes=all_notes,
    )
    store.update_task(task_id, status="completed", progress=100, finished_at=now_iso())
