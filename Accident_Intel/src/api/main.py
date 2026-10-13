# sys.path surgery MUST happen before any domain imports so that all submodules
# (vehicle_tracking, VLM, rag, Car_damage_cost) are importable as bare packages.
import sys
from pathlib import Path

_src_dir = str(Path(__file__).parents[2])              # Accident_Intel/
_src_src_dir = str(Path(__file__).parents[2] / "src")  # Accident_Intel/src/
_car_damage_dir = str(Path(__file__).parents[2] / "src" / "Car_damage_cost")
for _p in (_src_dir, _src_src_dir, _car_damage_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from .config import Settings  # noqa: E402
from .models import init_db  # noqa: E402
from .routers.accidents import router as accidents_router  # noqa: E402
from .routers.damage import router as damage_router  # noqa: E402
from .routers.laws import router as laws_router  # noqa: E402


def _get_settings() -> Settings:
    from .dependencies import get_settings

    return get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = _get_settings()

    # Create required output directories
    for subdir in ("", "accidents", "damage"):
        Path(settings.data_dir, subdir).mkdir(parents=True, exist_ok=True)

    # Initialise the SQLite database
    init_db(str(settings.db_path))

    yield


def create_app() -> FastAPI:
    settings = _get_settings()
    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        lifespan=lifespan,
        description=(
            "Backend for the Accident-Intel React UI. Wraps the project's real models: "
            "Qwen2-VL video analysis, YOLO11x + BoT-SORT tracking, VTL hybrid RAG retrieval, "
            "Groq liability reasoning and the Car_damage_cost repair estimator."
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(accidents_router)
    app.include_router(damage_router)
    app.include_router(laws_router)

    @app.get("/health", tags=["health"])
    def health():
        """Health + mode report so the UI can show what is actually running."""
        return {
            "status": "ok",
            "version": settings.api_version,
            "models": {
                "vlm": {"model": settings.vlm_model_id, "mock": settings.vlm_mock},
                "tracking": {
                    "model": settings.tracking_model,
                    "mock": settings.tracking_mock,
                },
                "rag": {
                    "mode": settings.rag_mode,
                    "index": str(settings.rag_out_dir),
                    "rerank": settings.rag_rerank,
                    "mock": settings.rag_mock,
                },
                "reasoning": {
                    "provider": "groq",
                    "model": settings.reasoning_model,
                    "keyConfigured": bool(settings.reasoning_key),
                    "mock": settings.reasoning_mock,
                },
                "damage": {
                    "weights": settings.damage_weights,
                    "mock": settings.damage_mock,
                },
            },
        }

    return app


app = create_app()
