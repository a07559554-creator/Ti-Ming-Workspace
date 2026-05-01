from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse
import re

try:
    from yt_dlp import YoutubeDL
except ImportError:  # pragma: no cover - optional runtime dependency
    YoutubeDL = None


VALID_HOSTS = {"www.bilibili.com", "bilibili.com", "b23.tv", "m.bilibili.com"}
BVID_PATTERN = re.compile(r"(BV[0-9A-Za-z]{10})")


@dataclass
class CheckedSource:
    normalized_url: str
    source_type: str
    videos: list[dict]


def _parse_bvid(url: str) -> str:
    match = BVID_PATTERN.search(url)
    if match:
        return match.group(1)
    raise ValueError("未识别到有效的 B 站 BV 号。")


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("链接格式无效，请输入完整的 B 站链接。")
    if parsed.netloc not in VALID_HOSTS:
        raise ValueError("当前仅支持 B 站链接。")
    return parsed.geturl()


def has_real_backend() -> bool:
    return YoutubeDL is not None


def _extract_with_ytdlp(url: str) -> dict:
    if YoutubeDL is None:
        raise RuntimeError("未安装 yt-dlp，无法执行真实 B站解析。")
    opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
    }
    with YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def check_bilibili_source_real(url: str) -> CheckedSource:
    normalized_url = _normalize_url(url)
    info = _extract_with_ytdlp(normalized_url)

    source_type = "single"
    parsed = urlparse(normalized_url)
    query = parse_qs(parsed.query)
    if "p" in query:
        source_type = "multi_part"
    elif "series" in normalized_url or "season_id" in query or "collectiondetail" in normalized_url:
        source_type = "collection"

    video = {
        "title": info.get("title") or f"示例视频 {info.get('id')}",
        "source_url": normalized_url,
        "normalized_url": normalized_url,
        "source_type": source_type,
        "bvid": info.get("id") or _parse_bvid(normalized_url),
        "cid": str(info.get("cid") or f"cid-{(info.get('id') or '')[-6:]}"),
        "uploader": info.get("uploader") or "未知作者",
        "duration_sec": int(float(info.get("duration") or 0)),
        "cover_url": info.get("thumbnail") or "https://placehold.co/640x360?text=video-cover",
        "series_title": info.get("playlist_title"),
        "series_index": info.get("playlist_index"),
        "series_total": info.get("n_entries"),
    }
    return CheckedSource(normalized_url=normalized_url, source_type=source_type, videos=[video])


def check_bilibili_source(url: str) -> CheckedSource:
    normalized_url = _normalize_url(url)
    parsed = urlparse(normalized_url)
    query = parse_qs(parsed.query)
    bvid = _parse_bvid(normalized_url)

    source_type = "single"
    if "p" in query:
        source_type = "multi_part"
    elif "series" in normalized_url or "season_id" in query or "collectiondetail" in normalized_url:
        source_type = "collection"

    base_video = {
        "title": f"示例视频 {bvid}",
        "source_url": normalized_url,
        "normalized_url": normalized_url,
        "source_type": source_type,
        "bvid": bvid,
        "cid": f"cid-{bvid[-6:]}",
        "uploader": "待接入 B站作者信息",
        "duration_sec": 1260,
        "cover_url": "https://placehold.co/640x360?text=video-cover",
        "series_title": None,
        "series_index": None,
        "series_total": None,
    }

    if source_type == "single":
        return CheckedSource(normalized_url=normalized_url, source_type=source_type, videos=[base_video])

    if source_type == "multi_part":
        current_part = int(query.get("p", ["1"])[0])
        videos = []
        for part_index in range(1, 4):
            item = base_video.copy()
            item["title"] = f"示例分P视频 {bvid} - P{part_index}"
            item["cid"] = f"cid-{bvid[-6:]}-{part_index}"
            item["series_title"] = f"示例分P合集 {bvid}"
            item["series_index"] = part_index
            item["series_total"] = 3
            videos.append(item)
        videos[current_part - 1]["title"] += "（当前）"
        return CheckedSource(normalized_url=normalized_url, source_type=source_type, videos=videos)

    videos = []
    for index in range(1, 4):
        item = base_video.copy()
        item["title"] = f"示例课程视频 {bvid} - 第{index}讲"
        item["cid"] = f"cid-{bvid[-6:]}-series-{index}"
        item["series_title"] = f"示例课程系列 {bvid}"
        item["series_index"] = index
        item["series_total"] = 3
        videos.append(item)
    return CheckedSource(normalized_url=normalized_url, source_type=source_type, videos=videos)
