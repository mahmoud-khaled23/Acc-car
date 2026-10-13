"""API configuration.

All heavy ML components can be swapped for canned responses with the ``*_MOCK``
flags.  They default to **real models** (``false``) because the React UI is
meant to drive the actual project models; set a flag to ``true`` only when you
deliberately want a canned response (offline demo, CI, no GPU).
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict as SettingsConfig


class Settings(BaseSettings):
    # --- API metadata ------------------------------------------------------
    api_title: str = "Accident-Intel API"
    api_version: str = "0.2.0"

    # --- storage -----------------------------------------------------------
    data_dir: Path = Path("out")
    db_path: Path = Path("out/accident_intel.db")

    # --- VLM (src/VLM) -----------------------------------------------------
    vlm_model_id: str = "Qwen/Qwen2-VL-7B-Instruct"
    vlm_n_frames: int = 32
    vlm_max_tokens: int = 1024
    vlm_load_in_4bit: bool = False
    vlm_load_in_8bit: bool = False

    # --- vehicle tracking (src/vehicle_tracking) ---------------------------
    tracking_model: str = "yolo11x.pt"
    tracking_min_frames: int = 6

    # --- RAG / law retrieval (src/rag) ------------------------------------
    rag_out_dir: Path = Path("out")
    rag_top_k: int = 5
    # hybrid = dense (bge-m3) + BM25 fused, bm25 = keyword only, dense = embeddings only
    rag_mode: str = "hybrid"
    # cross-encoder re-ranking (downloads BAAI/bge-reranker-v2-m3 on first use)
    rag_rerank: bool = False

    # --- reasoning LLM (Groq, OpenAI-compatible) --------------------------
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    reasoning_model: str = "openai/gpt-oss-120b"
    reasoning_timeout: float = 120.0

    # --- damage assessment (src/Car_damage_cost) --------------------------
    damage_weights: str = "weights/damage_seg.pt"
    parts_weights: str = "weights/parts_segmentation.pt"
    prices_path: str = "data/prices.json"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-lite-latest"

    # --- mock switches (default: real models) -----------------------------
    vlm_mock: bool = False
    tracking_mock: bool = False
    reasoning_mock: bool = False
    rag_mock: bool = False
    damage_mock: bool = False

    # --- CORS --------------------------------------------------------------
    # Extra allowed origins.  The Vite dev server origins and the hosted
    # preview domain are always allowed (see ``cors_regex``).
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:4173",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:4173",
    ]
    # Any http(s) origin (covers sandbox/preview hosts such as *.e2b.app).
    cors_regex: str = r"https?://.*"

    model_config = SettingsConfig(env_file=".env", extra="ignore")

    # ------------------------------------------------------------------ keys
    @property
    def reasoning_key(self) -> str:
        """Groq API key, falling back to the generic OPENAI_API_KEY name."""
        import os

        return self.groq_api_key or os.getenv("OPENAI_API_KEY", "")
