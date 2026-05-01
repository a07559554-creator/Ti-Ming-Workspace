from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    app_name: str
    demo_mode: bool
    pipeline_mode: str
    default_language: str
    storage_dir: Path
    download_dir: Path
    model_dir: Path
    whisper_model: str
    llm_provider: str
    llm_model: str
    llm_base_url: str
    llm_api_key: str
    llm_thinking: str
    llm_timeout_sec: int


def load_settings() -> Settings:
    storage_dir = Path(os.getenv("TIMING_STORAGE_DIR", "data"))
    return Settings(
        app_name=os.getenv("TIMING_APP_NAME", "Timming Transcript Tool"),
        demo_mode=os.getenv("TIMING_DEMO_MODE", "true").lower() == "true",
        pipeline_mode=os.getenv("TIMING_PIPELINE_MODE", "demo"),
        default_language=os.getenv("TIMING_DEFAULT_LANGUAGE", "auto"),
        storage_dir=storage_dir,
        download_dir=storage_dir / "downloads",
        model_dir=storage_dir / "models",
        whisper_model=os.getenv("TIMING_WHISPER_MODEL", "tiny"),
        llm_provider=os.getenv("TIMING_LLM_PROVIDER", "none"),
        llm_model=os.getenv("TIMING_LLM_MODEL", "deepseek-v4-pro"),
        llm_base_url=os.getenv("TIMING_LLM_BASE_URL", "https://api.deepseek.com"),
        llm_api_key=os.getenv("TIMING_LLM_API_KEY", os.getenv("DEEPSEEK_API_KEY", "")),
        llm_thinking=os.getenv("TIMING_LLM_THINKING", "disabled"),
        llm_timeout_sec=int(os.getenv("TIMING_LLM_TIMEOUT_SEC", "120")),
    )


settings = load_settings()
settings.storage_dir.mkdir(parents=True, exist_ok=True)
settings.download_dir.mkdir(parents=True, exist_ok=True)
settings.model_dir.mkdir(parents=True, exist_ok=True)
