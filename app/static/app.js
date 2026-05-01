const state = {
  videos: [],
  selectedVideoId: null,
  selectedGroup: "transcript",
  selectedTab: "polished",
  pollTimer: null,
};
window.state = state;

const flash = document.querySelector("#flash");
const checkResult = document.querySelector("#check-result");
const videoList = document.querySelector("#video-list");
const detailEmpty = document.querySelector("#detail-empty");
const detailView = document.querySelector("#detail-view");
const detailContent = document.querySelector("#detail-content");
const retryButton = document.querySelector("#retry-button");
const detailTags = document.querySelector("#detail-tags");

const groupConfig = {
  transcript: [
    { key: "polished", label: "AI润色版" },
    { key: "original", label: "原文" },
    { key: "timestamp", label: "时间戳" },
  ],
  study: [
    { key: "summary", label: "摘要" },
    { key: "outline", label: "大纲" },
  ],
  ops: [
    { key: "notes", label: "处理记录" },
    { key: "meta", label: "任务信息" },
  ],
};

function showFlash(message, isError = false) {
  flash.hidden = false;
  flash.textContent = message;
  flash.style.background = isError ? "#f6e7df" : "#e8f2eb";
  flash.style.color = isError ? "#8b3a1c" : "#25523c";
  flash.style.borderColor = isError ? "rgba(188, 90, 45, 0.15)" : "rgba(47, 107, 79, 0.15)";
}

function clearFlash() {
  flash.hidden = true;
  flash.textContent = "";
}

function setMetric(id, value) {
  const element = document.querySelector(id);
  if (element) {
    element.textContent = value;
  }
}

function formatTime(date = new Date()) {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderInlineMarkdown(text) {
  let html = escapeHtml(text);
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  return html;
}

function renderParagraphText(lines) {
  return renderInlineMarkdown(lines.join("\n")).replace(/\n/g, "<br />");
}

function renderMarkdown(text) {
  const normalized = (text || "").replace(/\r\n/g, "\n").trim();
  if (!normalized) {
    return "<p>暂无内容。</p>";
  }

  const lines = normalized.split("\n");
  const html = [];
  let index = 0;
  let inCodeBlock = false;

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();

    if (trimmed.startsWith("```")) {
      if (inCodeBlock) {
        html.push("</code></pre>");
        inCodeBlock = false;
      } else {
        html.push("<pre><code>");
        inCodeBlock = true;
      }
      index += 1;
      continue;
    }

    if (inCodeBlock) {
      html.push(`${escapeHtml(line)}\n`);
      index += 1;
      continue;
    }

    if (!trimmed) {
      index += 1;
      continue;
    }

    if (/^#{1,6}\s+/.test(trimmed)) {
      const level = trimmed.match(/^#+/)[0].length;
      const content = trimmed.replace(/^#{1,6}\s+/, "");
      html.push(`<h${level}>${renderInlineMarkdown(content)}</h${level}>`);
      index += 1;
      continue;
    }

    if (/^【.+】$/.test(trimmed)) {
      html.push(`<h4>${renderInlineMarkdown(trimmed)}</h4>`);
      index += 1;
      continue;
    }

    if (/^>\s?/.test(trimmed)) {
      html.push(`<blockquote>${renderInlineMarkdown(trimmed.replace(/^>\s?/, ""))}</blockquote>`);
      index += 1;
      continue;
    }

    if (/^(\-|\*)\s+/.test(trimmed)) {
      const items = [];
      while (index < lines.length && /^(\-|\*)\s+/.test(lines[index].trim())) {
        items.push(`<li>${renderInlineMarkdown(lines[index].trim().replace(/^(\-|\*)\s+/, ""))}</li>`);
        index += 1;
      }
      html.push(`<ul>${items.join("")}</ul>`);
      continue;
    }

    if (/^\d+\.\s+/.test(trimmed)) {
      const items = [];
      while (index < lines.length && /^\d+\.\s+/.test(lines[index].trim())) {
        items.push(`<li>${renderInlineMarkdown(lines[index].trim().replace(/^\d+\.\s+/, ""))}</li>`);
        index += 1;
      }
      html.push(`<ol>${items.join("")}</ol>`);
      continue;
    }

    const paragraphLines = [trimmed];
    index += 1;
    while (index < lines.length) {
      const next = lines[index].trim();
      if (
        !next ||
        /^#{1,6}\s+/.test(next) ||
        /^【.+】$/.test(next) ||
        /^>\s?/.test(next) ||
        /^(\-|\*)\s+/.test(next) ||
        /^\d+\.\s+/.test(next) ||
        next.startsWith("```")
      ) {
        break;
      }
      paragraphLines.push(next);
      index += 1;
    }
    html.push(`<p>${renderParagraphText(paragraphLines)}</p>`);
  }

  if (inCodeBlock) {
    html.push("</code></pre>");
  }

  return html.join("");
}

async function request(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: "请求失败" }));
    throw new Error(payload.detail || "请求失败");
  }
  return response.json();
}

function hydrateInputFromQuery() {
  const params = new URLSearchParams(window.location.search);
  const url = params.get("url");
  if (url) {
    document.querySelector("#source-url").value = url;
  }
}

function buildCheckHtml(payload) {
  const items = payload.videos
    .map(
      (item) => `
        <article class="check-item">
          <strong>${item.title}</strong>
          <p class="video-meta">
            类型：${item.source_type} · 作者：${item.uploader} · 时长：${item.duration_sec}s
          </p>
        </article>
      `
    )
    .join("");

  return `
    <strong>已识别 ${payload.video_count} 条内容</strong>
    <p class="video-meta">来源类型：${payload.source_type} · 规范化链接：${payload.normalized_url}</p>
    <div class="check-list">${items}</div>
  `;
}

function statusLabel(status) {
  const mapping = {
    pending: "待处理",
    checking: "校验中",
    downloading: "下载中",
    transcribing: "转写中",
    completed: "已完成",
    failed: "失败",
  };
  return mapping[status] || status;
}

function isActiveStatus(status) {
  return ["pending", "checking", "downloading", "transcribing"].includes(status);
}

function hasActiveTasks() {
  return state.videos.some((video) => isActiveStatus(video.status) || isActiveStatus(video.last_task?.status));
}

function syncPolling() {
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
  if (!hasActiveTasks()) {
    return;
  }
  state.pollTimer = window.setInterval(() => {
    loadVideos(false, true).catch((error) => {
      console.error(error);
    });
  }, 2500);
}

function renderVideoList() {
  setMetric("#metric-count", String(state.videos.length));
  setMetric("#metric-refresh", formatTime());

  if (state.videos.length === 0) {
    videoList.className = "video-list empty-state";
    videoList.textContent = "还没有文件，先提交一个 B 站链接。";
    return;
  }

  videoList.className = "video-list";
  videoList.innerHTML = state.videos
    .map(
      (video) => {
        const progress = video.last_task?.progress ?? 0;
        const taskStatus = statusLabel(video.last_task?.status || video.status);
        const canDelete = !isActiveStatus(video.status) && !isActiveStatus(video.last_task?.status);
        return `
        <article class="video-item ${video.id === state.selectedVideoId ? "is-active" : ""}" data-video-id="${video.id}">
          <div class="video-item-top">
            <h3>${video.title}</h3>
            <button
              class="icon-button danger"
              type="button"
              data-delete-id="${video.id}"
              ${canDelete ? "" : "disabled"}
              title="${canDelete ? "删除文件" : "处理中暂不可删除"}"
            >
              删除
            </button>
          </div>
          <p class="video-meta">
            ${statusLabel(video.status)} · ${video.source_type} · ${video.duration_sec}s
          </p>
          <p class="video-meta">${video.uploader}</p>
          <div class="task-progress">
            <div class="task-progress-meta">
              <span>${taskStatus}</span>
              <strong>${progress}%</strong>
            </div>
            <div class="task-progress-bar">
              <span style="width: ${progress}%"></span>
            </div>
          </div>
        </article>
      `;
      }
    )
    .join("");

  document.querySelectorAll(".video-item").forEach((item) => {
    item.addEventListener("click", () => {
      selectVideo(item.dataset.videoId);
    });
  });

  document.querySelectorAll("[data-delete-id]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      await handleDelete(button.dataset.deleteId);
    });
  });

  syncPolling();
}

function getTabContent(video) {
  const tabMap = {
    summary: video.summary_text || "当前没有摘要内容。",
    outline: video.outline_text || "当前没有大纲内容。",
    polished: video.polished_transcript || "当前没有 AI 润色版。",
    original: video.original_transcript || "当前没有原始文稿。",
    timestamp: video.transcript_with_timestamp || "当前没有时间戳文稿。",
    notes: (video.processing_notes || []).length
      ? video.processing_notes.map((item, index) => `${index + 1}. ${item}`).join("\n")
      : "当前没有处理记录。",
    meta: [
      `标题：${video.title}`,
      `作者：${video.uploader}`,
      `状态：${statusLabel(video.status)}`,
      `时长：${video.duration_sec}s`,
      `BVID：${video.bvid}`,
      `创建时间：${video.created_at}`,
      `更新时间：${video.updated_at}`,
      `任务类型：${video.last_task?.task_type || "-"}`,
      `任务状态：${statusLabel(video.last_task?.status || "-")}`,
      `任务进度：${video.last_task?.progress ?? "-"}%`,
    ].join("\n"),
  };
  return tabMap[state.selectedTab] || "暂无内容。";
}

function renderSubTabs() {
  const tabs = groupConfig[state.selectedGroup] || [];
  const container = document.querySelector("#detail-tabs");
  container.innerHTML = tabs
    .map(
      (tab) => `
        <button class="tab-button ${tab.key === state.selectedTab ? "is-active" : ""}" data-tab="${tab.key}">
          ${tab.label}
        </button>
      `
    )
    .join("");

  document.querySelectorAll(".tab-button").forEach((button) => {
    button.addEventListener("click", async () => {
      if (!state.selectedVideoId) {
        return;
      }
      state.selectedTab = button.dataset.tab;
      const detail = await request(`/api/v1/videos/${state.selectedVideoId}`);
      renderDetail(detail);
    });
  });
}

function activateGroupButton() {
  document.querySelectorAll(".group-button").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.group === state.selectedGroup);
  });
}

function activateTabButton() {
  document.querySelectorAll(".tab-button").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.tab === state.selectedTab);
  });
}

function renderTags(video) {
  const tags = [...(video.tags || []), statusLabel(video.status)];
  detailTags.innerHTML = tags.map((tag) => `<span class="detail-tag">${tag}</span>`).join("");
}

function renderDetail(video) {
  detailEmpty.hidden = true;
  detailView.hidden = false;
  retryButton.disabled = isActiveStatus(video.status) || isActiveStatus(video.last_task?.status);
  document.querySelector("#detail-title").textContent = video.title;
  document.querySelector("#detail-meta").textContent =
    `${video.uploader} · ${video.duration_sec}s · ${video.source_type} · ${video.bvid}`;
  document.querySelector("#detail-status").textContent = statusLabel(video.status);
  renderTags(video);
  activateGroupButton();
  renderSubTabs();
  detailContent.innerHTML = renderMarkdown(getTabContent(video));
  activateTabButton();
}

async function loadVideos(selectLatest = false, silent = false) {
  const videos = await request("/api/v1/videos");
  state.videos = videos;
  if ((selectLatest || !state.selectedVideoId) && videos[0]) {
    state.selectedVideoId = videos[0].id;
  }
  renderVideoList();
  if (!state.selectedVideoId && videos[0]) {
    state.selectedVideoId = videos[0].id;
  }
  if (state.selectedVideoId) {
    const selectedExists = videos.some((video) => video.id === state.selectedVideoId);
    if (selectedExists) {
      await fetchSelectedDetail();
    } else {
      state.selectedVideoId = videos[0]?.id || null;
      if (state.selectedVideoId) {
        await fetchSelectedDetail();
      } else {
        detailEmpty.hidden = false;
        detailView.hidden = true;
      }
    }
  } else if (!silent) {
    detailEmpty.hidden = false;
    detailView.hidden = true;
  }
}

async function selectVideo(videoId, rerenderList = true) {
  state.selectedVideoId = videoId;
  state.selectedGroup = "transcript";
  state.selectedTab = "polished";
  if (rerenderList) {
    renderVideoList();
  }
  await fetchSelectedDetail();
}

async function fetchSelectedDetail() {
  if (!state.selectedVideoId) {
    return;
  }
  const detail = await request(`/api/v1/videos/${state.selectedVideoId}`);
  renderDetail(detail);
}

async function handleCheck() {
  clearFlash();
  const url = document.querySelector("#source-url").value.trim();
  if (!url) {
    showFlash("请先输入一个 B 站链接。", true);
    return;
  }
  try {
    const payload = await request("/api/v1/videos/bilibili/check", {
      method: "POST",
      body: JSON.stringify({ url }),
    });
    checkResult.hidden = false;
    checkResult.innerHTML = buildCheckHtml(payload);
  } catch (error) {
    showFlash(error.message, true);
  }
}

async function handleProcess(event) {
  event.preventDefault();
  clearFlash();
  const url = document.querySelector("#source-url").value.trim();
  if (!url) {
    showFlash("请先输入一个 B 站链接。", true);
    return;
  }

  const generate_polish = document.querySelector("#generate-polish").checked;
  const generate_summary = document.querySelector("#generate-summary").checked;

  try {
    const payload = await request("/api/v1/videos/bilibili/process", {
      method: "POST",
      body: JSON.stringify({ url, generate_polish, generate_summary }),
    });
    showFlash(`已创建 ${payload.video_count} 个转文稿任务。`);
    await loadVideos(true);
  } catch (error) {
    showFlash(error.message, true);
  }
}

async function handleRetry() {
  if (!state.selectedVideoId) {
    return;
  }
  clearFlash();
  try {
    const detail = await request(`/api/v1/videos/${state.selectedVideoId}/retry`, {
      method: "POST",
    });
    showFlash("已重新提交处理任务，进度会自动刷新。");
    renderDetail(detail);
    await loadVideos();
  } catch (error) {
    showFlash(error.message, true);
  }
}

async function handleDelete(videoId) {
  clearFlash();
  try {
    await request(`/api/v1/videos/${videoId}`, {
      method: "DELETE",
    });
    if (state.selectedVideoId === videoId) {
      state.selectedVideoId = null;
    }
    showFlash("已删除该知识文件。");
    await loadVideos(false);
  } catch (error) {
    showFlash(error.message, true);
  }
}

function bindGroups() {
  document.querySelectorAll(".group-button").forEach((button) => {
    button.addEventListener("click", async () => {
      if (!state.selectedVideoId) {
        return;
      }
      state.selectedGroup = button.dataset.group;
      state.selectedTab = groupConfig[state.selectedGroup][0].key;
      const detail = await request(`/api/v1/videos/${state.selectedVideoId}`);
      renderDetail(detail);
    });
  });
}

async function boot() {
  const health = await request("/health");
  setMetric("#metric-mode", health.demo_mode ? "Demo" : "Live");
  hydrateInputFromQuery();
  bindGroups();

  document.querySelector("#check-button").addEventListener("click", handleCheck);
  document.querySelector("#source-form").addEventListener("submit", handleProcess);
  document.querySelector("#refresh-button").addEventListener("click", () => loadVideos(false));
  retryButton.addEventListener("click", handleRetry);

  await loadVideos(false);
}

boot().catch((error) => {
  showFlash(error.message, true);
});
