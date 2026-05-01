# Ti-Ming Workspace

Ti-Ming Workspace is a product-focused repository for turning Bilibili videos into reusable knowledge files.

This is the public GitHub release edition. It only keeps the product code and the minimum documentation needed to run the app locally. Internal research notes, planning documents, and production process files are intentionally excluded.

## What It Does

- Validate Bilibili video links
- Extract real video metadata
- Run background transcript jobs with progress tracking
- Download audio with `yt-dlp`
- Transcribe audio locally with `faster-whisper`
- Prefer official subtitles when available, then fall back to ASR
- Persist workspace data locally in JSON
- Mark interrupted jobs safely on shutdown
- Manage knowledge files with delete and retry support
- Render knowledge file details with Markdown
- Generate layered study outputs with optional DeepSeek integration

## Result Layers

Each knowledge file is organized into 4 result groups:

- `视频文案`
  - `AI润色版`
  - `原文`
  - `时间戳`
- `费曼教学`
  - `极速掌握模式`
  - `深度学习模式`
- `核心知识点`
  - `核心知识点`
  - `结构大纲`
- `处理记录`
  - `处理记录`
  - `任务信息`

## Stack

- FastAPI
- Uvicorn
- yt-dlp
- faster-whisper
- Optional DeepSeek integration

## Project Structure

```text
app/
  config.py
  main.py
  models.py
  schemas.py
  store.py
  services/
    bilibili.py
    llm_writer.py
    transcript_pipeline.py
  static/
    index.html
    styles.css
    app.js
requirements.txt
```

## Run Locally

Use Python 3.11 if possible:

```bash
python3.11 -m venv .venv311
source .venv311/bin/activate
pip install -r requirements.txt
```

Start in real transcript mode:

```bash
TIMING_PIPELINE_MODE=real \
TIMING_DEMO_MODE=false \
TIMING_WHISPER_MODEL=tiny \
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open:

- [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

On the first real transcript run, the Whisper model will be downloaded into `data/models/`.

## Optional DeepSeek Setup

If you want model-generated study outputs:

```bash
export TIMING_LLM_PROVIDER=deepseek
export TIMING_LLM_MODEL=deepseek-v4-pro
export TIMING_LLM_API_KEY=your_api_key
export TIMING_LLM_THINKING=disabled
```

Then start the service normally.

## Local Data

- Workspace data is stored in `data/workspace_store.json`
- Completed files are restored on restart
- Interrupted active jobs are automatically marked as failed on restart or shutdown

## Current Limitations

- JSON persistence only, no database yet
- No queue system like Celery/Redis yet
- Whisper defaults to `tiny` for speed rather than best accuracy
- Export, batch operations, and cross-file knowledge retrieval are still in progress

## Next Steps

- Persist files and tasks in a database
- Add batch operations and export
- Expand the knowledge workspace into search and Q&A flows
