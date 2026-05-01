from __future__ import annotations

from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import json

from ..config import settings


@dataclass(frozen=True)
class StudyArtifacts:
    polished_transcript: str
    summary_text: str
    outline_text: str
    tags: list[str]


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
    prompt = f"""
你是“视频知识工作台”的学习稿整理助手。请把转写文稿整理成适合中文用户阅读的知识文件。

视频标题：{title}
作者：{uploader}
时长（秒）：{duration_sec}

请输出严格 JSON，不要输出 JSON 之外的任何解释。字段要求如下：
{{
  "polished_transcript": "一份适合阅读的学习稿，保留 3-6 个关键要点，中文为主，必要时可引用少量原句。",
  "summary_text": "必须使用以下四个标题：\\n【核心洞见】\\n【内容脉络】\\n【关键要点】\\n【可行动观察】",
  "outline_text": "使用 1. 2. 3. 编号，给出 4-6 条结构化大纲。",
  "tags": ["3到5个中文标签"]
}}

写作要求：
1. 不要编造视频里没有说过的事实。
2. 如果文稿本身是英文，请用中文总结，但可以保留最关键的一两句英文原话。
3. 如果内容信息量有限，保持克制，不要强行拔高。
4. 输出内容适合直接展示在知识文件详情页。

转写片段：
{segment_excerpt}

完整文稿（可能已截断）：
{transcript_excerpt}
""".strip()

    payload = {
        "model": settings.llm_model,
        "messages": [
            {
                "role": "system",
                "content": "你是严谨的知识整理助手，只输出用户要求的 JSON。",
            },
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    if settings.llm_thinking:
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
        with urlopen(request, timeout=settings.llm_timeout_sec) as response:  # nosec - user requested external API call
            raw = response.read().decode("utf-8")
    except HTTPError as exc:  # pragma: no cover - network error path
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"DeepSeek 请求失败，HTTP {exc.code}。{detail}") from exc
    except URLError as exc:  # pragma: no cover - network error path
        raise RuntimeError(f"DeepSeek 网络请求失败：{exc.reason}") from exc

    content = _extract_content(json.loads(raw))
    parsed = _parse_json_block(content)
    polished = str(parsed.get("polished_transcript") or "").strip()
    summary = str(parsed.get("summary_text") or "").strip()
    outline = str(parsed.get("outline_text") or "").strip()
    tags = [str(item).strip() for item in (parsed.get("tags") or []) if str(item).strip()]

    if not polished or not summary or not outline:
        raise RuntimeError("DeepSeek 返回字段不完整。")

    return StudyArtifacts(
        polished_transcript=polished,
        summary_text=summary,
        outline_text=outline,
        tags=tags[:5],
    )
