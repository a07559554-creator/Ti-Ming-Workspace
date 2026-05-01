# Ti-Ming Workspace

Ti-Ming Workspace is a product-focused repository for turning Bilibili videos into structured knowledge files.

This version is the public GitHub release edition. It only keeps the final product code and the minimum usage documentation needed to run the app locally.

Internal research notes, planning documents, and production process files are intentionally kept out of this repository.

## What It Does

- Validate Bilibili video links
- Extract real video metadata
- Run background transcript jobs
- Download audio with `yt-dlp`
- Transcribe audio locally with `faster-whisper`
- Generate polished study notes
- Show task progress in the file list
- Manage knowledge files with delete support
- Render result details with Markdown

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
  static/
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

If you want model-generated study notes:

```bash
export TIMING_LLM_PROVIDER=deepseek
export TIMING_LLM_MODEL=deepseek-v4-pro
export TIMING_LLM_API_KEY=your_api_key
export TIMING_LLM_THINKING=disabled
```

Then start the service normally.

## Current Limitations

- In-memory storage only
- No persistent database yet
- No queue system like Celery/Redis yet
- Whisper defaults to `tiny` for speed rather than best accuracy

## Next Steps

- Persist files and tasks in a database
- Add batch operations and export
- Expand result layers into a richer knowledge workspace
