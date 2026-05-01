from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import json

from ..config import settings


@dataclass(frozen=True)
class StudyArtifacts:
    polished_transcript: str
    summary_text: str
    feynman_deep_text: str
    key_points_text: str
    outline_text: str
    tags: list[str]


class VideoCategory(str, Enum):
    HARDCORE_SCIENCE = "HARDCORE_SCIENCE"
    EXPERIENCE_OPINION = "EXPERIENCE_OPINION"
    TUTORIAL_OPERATION = "TUTORIAL_OPERATION"


def deepseek_enabled() -> bool:
    return settings.llm_provider.lower() == "deepseek" and bool(settings.llm_api_key.strip())


def _trim_transcript(text: str, limit: int = 16000) -> str:
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "\n\n[内容过长，已截断后送入模型。]"


def _compact_segments(segments: list[dict], limit: int = 16) -> str:
    rows = []
    for segment in segments[:limit]:
        rows.append(f"[{segment['start']}] {segment['text'].strip()}")
    return "\n".join(rows)


def _extract_content(payload: dict) -> str:
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError("DeepSeek 返回中没有 choices。")
    message = choices[0].get("message") or {}
    content = (message.get("content") or "").strip()
    if not content:
        raise RuntimeError("DeepSeek 返回了空内容。")
    return content


def _parse_json_block(content: str) -> dict:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise RuntimeError("DeepSeek 返回内容不是可解析的 JSON。")
        return json.loads(content[start : end + 1])


def _call_llm(messages: list[dict], expect_json: bool = False) -> str:
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "stream": False,
    }
    if expect_json:
        payload["response_format"] = {"type": "json_object"}
    
    if settings.llm_thinking and settings.llm_thinking != "disabled":
        payload["thinking"] = {"type": settings.llm_thinking}

    request = Request(
        url=f"{settings.llm_base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.llm_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=settings.llm_timeout_sec) as response:  # nosec
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"DeepSeek 请求失败，HTTP {exc.code}。{detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"DeepSeek 网络请求失败：{exc.reason}") from exc

    return _extract_content(json.loads(raw))


def _classify_video(title: str, uploader: str, excerpt: str) -> VideoCategory:
    prompt = f"""
请根据以下视频信息，将其分类到最合适的一类中。你只需返回对应的英文枚举词，不要返回任何解释。

分类列表：
1. HARDCORE_SCIENCE (硬核科普)：主要介绍科学原理、复杂概念解析、学术或深度技术分析。
2. EXPERIENCE_OPINION (经验观点)：主要是职场分享、人生经验、行业吐槽、趋势观点等非硬核软知识。
3. TUTORIAL_OPERATION (教程操作)：主要是操作指南、SOP步骤、避坑攻略、工具教学、材料准备等。

视频标题：{title}
UP主：{uploader}
文稿片段：
{excerpt[:500]}
"""
    messages = [
        {"role": "system", "content": "你是一个视频分类器。只返回指定的枚举词汇之一。"},
        {"role": "user", "content": prompt.strip()}
    ]
    try:
        result = _call_llm(messages, expect_json=False).strip().upper()
        if "HARDCORE_SCIENCE" in result:
            return VideoCategory.HARDCORE_SCIENCE
        if "TUTORIAL_OPERATION" in result:
            return VideoCategory.TUTORIAL_OPERATION
        return VideoCategory.EXPERIENCE_OPINION
    except Exception:
        # Default fallback
        return VideoCategory.EXPERIENCE_OPINION

# --- PROMPT TEMPLATES ---

COMMON_SYSTEM_PROMPT = "你是严谨的知识文件编辑器。你的目标不是写好看的摘要，而是帮助用户把视频内容保存成适合长期复看和复用的知识文件。请只输出合法的 JSON 格式数据。"

PROMPT_HARDCORE_SCIENCE = """
你正在处理一条【硬核科普类】视频，需要生成结构化的知识文件。
视频标题：{title}
作者：{uploader}
时长（秒）：{duration_sec}

请输出严格 JSON，不要输出 JSON 之外的任何解释。字段要求如下：
{{
  "polished_transcript": "保持原意，不做大幅扩写，优先提升可读性和段落组织，可加少量小标题。",
  "summary_text": "极速掌握模式，要求Markdown，包含：## 核心概念、## 为什么重要、## 快速掌握、## 适用场景。",
  "feynman_deep_text": "费曼深度模式，要求Markdown，包含：## 核心洞见、## 1. 背景与问题、## 2. 概念拆解（包含生活比喻）、## 3. 逻辑关系、## 4. 常见误区与防坑、## 5. 费曼自测。",
  "key_points_text": "核心知识点复用层，Markdown，包含：## 知识骨架、## 核心判断、## 一句话回顾。",
  "outline_text": "使用 1. 2. 3. 编号，给出 4-6 条结构化大纲。",
  "tags": ["3到5个中文标签"]
}}

文稿片段：
{segment_excerpt}

完整文稿：
{transcript_excerpt}
"""

PROMPT_EXPERIENCE_OPINION = """
你正在处理一条【经验观点类】视频，需要生成结构化的知识文件。请去除生硬的科普模型，聚焦于提炼痛点、解法和共鸣金句。
视频标题：{title}
作者：{uploader}
时长（秒）：{duration_sec}

请输出严格 JSON，不要输出 JSON 之外的任何解释。字段要求如下：
{{
  "polished_transcript": "对原本口语化、松散的吐槽和分享进行平滑化整理，保留UP主个人风格，但提升阅读流畅度。",
  "summary_text": "极速速读模式，要求Markdown，包含：## 核心观点、## 痛点共鸣、## 关键建议。",
  "feynman_deep_text": "深度复盘模式（复用此字段），要求Markdown，包含：## 核心洞见、## 1. 痛点与现象分析、## 2. 深度观点拆解、## 3. 可执行的解法或建议、## 4. 避坑指南（如果有）。",
  "key_points_text": "金句与留存层，要求Markdown，包含：## 爆款金句、## 核心判断、## 行动启发。",
  "outline_text": "使用 1. 2. 3. 编号，给出 4-6 条讨论大纲。",
  "tags": ["3到5个中文标签"]
}}

文稿片段：
{segment_excerpt}

完整文稿：
{transcript_excerpt}
"""

PROMPT_TUTORIAL_OPERATION = """
你正在处理一条【教程操作类】视频，需要生成结构化的实操指南文件。重点提炼SOP步骤、材料工具和避坑指南。
视频标题：{title}
作者：{uploader}
时长（秒）：{duration_sec}

请输出严格 JSON，不要输出 JSON 之外的任何解释。字段要求如下：
{{
  "polished_transcript": "平滑化操作讲解内容，将口语化的步骤描述整理为清晰的叙述。",
  "summary_text": "极速了解模式，要求Markdown，包含：## 教学目标、## 适用人群、## 核心耗时或难度评估。",
  "feynman_deep_text": "SOP实操指南（复用此字段），要求Markdown，包含：## 适用目标、## 准备工作（材料/工具/条件）、## 操作步骤 (SOP)、## 避坑指南 (Do & Don't)、## 常见问题排查。",
  "key_points_text": "工具清单与核对表，要求Markdown，包含：## 核心工具清单、## 关键注意事项、## 一步总结。",
  "outline_text": "使用 1. 2. 3. 编号，列出操作流程大纲。",
  "tags": ["3到5个中文标签"]
}}

文稿片段：
{segment_excerpt}

完整文稿：
{transcript_excerpt}
"""


def generate_study_artifacts(
    *,
    title: str,
    uploader: str,
    duration_sec: int,
    transcript_text: str,
    segments: list[dict],
) -> StudyArtifacts:
    if not deepseek_enabled():
        raise RuntimeError("当前未启用 DeepSeek。")

    transcript_excerpt = _trim_transcript(transcript_text)
    segment_excerpt = _compact_segments(segments)

    # 阶段 1：对视频进行轻量分类
    category = _classify_video(title, uploader, transcript_excerpt)

    # 阶段 2：选择对应的 Prompt 模板
    if category == VideoCategory.HARDCORE_SCIENCE:
        prompt_template = PROMPT_HARDCORE_SCIENCE
    elif category == VideoCategory.TUTORIAL_OPERATION:
        prompt_template = PROMPT_TUTORIAL_OPERATION
    else:
        prompt_template = PROMPT_EXPERIENCE_OPINION

    prompt = prompt_template.format(
        title=title,
        uploader=uploader,
        duration_sec=duration_sec,
        segment_excerpt=segment_excerpt,
        transcript_excerpt=transcript_excerpt,
    ).strip()

    messages = [
        {"role": "system", "content": COMMON_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    # 阶段 3：执行最终提取
    content = _call_llm(messages, expect_json=True)
    parsed = _parse_json_block(content)

    polished = str(parsed.get("polished_transcript") or "").strip()
    summary = str(parsed.get("summary_text") or "").strip()
    feynman_deep = str(parsed.get("feynman_deep_text") or "").strip()
    key_points = str(parsed.get("key_points_text") or "").strip()
    outline = str(parsed.get("outline_text") or "").strip()
    tags = [str(item).strip() for item in (parsed.get("tags") or []) if str(item).strip()]

    if not polished or not summary or not feynman_deep or not key_points or not outline:
        raise RuntimeError(f"DeepSeek 返回字段不完整。类别: {category.value}")

    return StudyArtifacts(
        polished_transcript=polished,
        summary_text=summary,
        feynman_deep_text=feynman_deep,
        key_points_text=key_points,
        outline_text=outline,
        tags=tags[:5],
    )
