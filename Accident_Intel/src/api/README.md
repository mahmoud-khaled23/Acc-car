# Accident-Intel FastAPI Backend

REST layer that exposes the project's models to the React UI:

| Stage | Model / component | Where |
|---|---|---|
| Vehicle tracking | YOLO11x + BoT-SORT | `src/vehicle_tracking` |
| Scene understanding | Qwen2-VL (2-stage, event-triggered) | `src/VLM` |
| Law retrieval (RAG) | bge-m3 / BM25 over the NY VTL index | `src/rag` |
| Liability reasoning | Groq `openai/gpt-oss-120b` | `src/rag/retrieval/analyze_accident.py` |
| Damage estimation | YOLO-seg damage/parts + cost engine | `src/Car_damage_cost` |

All responses are already translated into the shapes the frontend types
declare (`frontend/src/types/*`) by `src/api/mappers.py`.

---

## Running the server

From the project root (`Accident_Intel/`):

```bash
# with the project virtualenv
.venv/bin/uvicorn src.api.main:app --host 0.0.0.0 --port 8000

# or with global python
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
```

Interactive API docs: **http://localhost:8000/docs** (ReDoc at `/redoc`).

`GET /health` reports which stages currently run the real model and which
are mocked, e.g.

```json
{"status": "ok", "version": "0.2.0",
 "models": {"vlm": {"model": "Qwen/Qwen2-VL-7B-Instruct", "mock": false},
            "tracking": {"model": "yolo11x.pt", "mock": false},
            "rag": {"mode": "hybrid", "index": "out", "rerank": false, "mock": false},
            "reasoning": {"provider": "groq", "model": "openai/gpt-oss-120b",
                          "keyConfigured": true, "mock": false},
            "damage": {"weights": "weights/damage_seg.pt", "mock": false}}}
```

---

## Wiring the React UI

The frontend calls **relative** `/api/...` URLs, so no CORS or absolute host is
needed: the Vite dev server proxies `/api` (and `/health`) to
`http://localhost:8000` (see `frontend/vite.config.ts`). In
`frontend/.env` keep `VITE_API_BASE_URL=` empty and `VITE_MOCK_MODE=false`.

```bash
# terminal 1 — backend
.venv/bin/uvicorn src.api.main:app --host 0.0.0.0 --port 8000
# terminal 2 — UI
cd frontend && npm install && npm run dev
```

Set `VITE_MOCK_MODE=true` in `frontend/.env` to fall back to the local demo
data in `src/mocks/` without a backend.

---

## Mock flags

Every stage has a mock switch (env var or `.env` entry). **Defaults are `false`
— the real models run unless a flag is turned on explicitly.**

| Env var | Default | What it does when `true` |
|---|---|---|
| `TRACKING_MOCK` | `false` | Synthetic trajectories instead of running YOLO11x tracking |
| `VLM_MOCK` | `false` | Pre-written scene description instead of running Qwen2-VL |
| `RAG_MOCK` | `false` | Three hardcoded VTL sections instead of querying the index |
| `REASONING_MOCK` | `false` | Pre-written liability assessment instead of the Groq LLM |
| `DAMAGE_MOCK` | `false` | Synthetic cost report instead of the damage pipeline |

Useful combinations:

```bash
# no GPU / no API keys — canned model output, real law retrieval from the local index
VLM_MOCK=true TRACKING_MOCK=true REASONING_MOCK=true DAMAGE_MOCK=true RAG_MODE=bm25 \
  .venv/bin/uvicorn src.api.main:app --port 8000
```

> `RAG_MODE=bm25` avoids loading the ~2 GB bge-m3 embedding model. The BM25
> index ships with the repo (`out/children.jsonl`), so retrieval is real.

---

## Configuration

All settings live in `src/api/config.py` (pydantic-settings; env vars or `.env`).

| Var | Default | Used by |
|---|---|---|
| `VLM_MODEL_ID` | `Qwen/Qwen2-VL-7B-Instruct` | VLM stage |
| `VLM_N_FRAMES` | `32` | Frames sampled per VLM pass |
| `TRACKING_MODEL` | `yolo11x.pt` | Tracker |
| `RAG_OUT_DIR` | `out` | RAG index directory |
| `RAG_MODE` | `hybrid` | `hybrid` = dense+BM25, `bm25`, `dense` |
| `RAG_RERANK` | `false` | Cross-encoder re-ranking (downloads a model) |
| `GROQ_API_KEY` | – | Liability reasoning (**required** for real reasoning) |
| `REASONING_MODEL` | `openai/gpt-oss-120b` | Groq model name |
| `DAMAGE_WEIGHTS` / `PARTS_WEIGHTS` | `weights/…` | Damage segmentation weights (not in repo) |
| `PRICES_PATH` | `data/prices.json` | Cost tables (not in repo) |
| `GEMINI_API_KEY` | – | Optional price agent in damage estimation |
| `DATA_DIR` / `DB_PATH` | `out` / `out/accident_intel.db` | Artifacts + SQLite |

`*_MOCK=true` needs no keys; real tracking/VLM need weights + a GPU, real
reasoning needs `GROQ_API_KEY`, real damage needs the weights + price tables.
When a model or key is missing the affected stage falls back and reports why
instead of crashing the request.

---

## Endpoints

### Health
| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Status + per-model mock/real report |

### Accidents
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/accidents` | List accidents (paginated: `page`, `page_size`) |
| `POST` | `/api/accidents` | Create an accident record (JSON) |
| `POST` | `/api/accidents/upload` | **One-shot** upload video + metadata (+ `autostart=true`) — what the UI uses |
| `GET` | `/api/accidents/{id}` | Full record: status, `stageLabel`, tracks, VLM analysis, laws, liability, `videoUrl` |
| `DELETE` | `/api/accidents/{id}` | Delete record + artifacts |
| `POST` | `/api/accidents/{id}/analyze` | Start/re-run the pipeline (background) |
| `POST` | `/api/accidents/{id}/video` | Attach a video to an existing record (multipart) |
| `GET` | `/api/accidents/{id}/video` | Original video stream |
| `GET` | `/api/accidents/{id}/tracked-video` | Annotated video stream |
| `GET` | `/api/accidents/{id}/tracking` | `VehicleTrack[]` (normalised bounding boxes) |
| `GET` | `/api/accidents/{id}/telemetry` | Raw tracker telemetry (speeds, events, candidates) |
| `GET` | `/api/accidents/{id}/trajectories` | Raw trajectory JSON |
| `GET` | `/api/accidents/{id}/vlm` | VLM analysis (summary, timeline, uncertainties) |
| `GET` | `/api/accidents/{id}/description` | Same as `/vlm` legacy alias |
| `GET` | `/api/accidents/{id}/laws` | Retrieved VTL sections (`TrafficLaw[]`) |
| `GET` | `/api/accidents/{id}/report` | Reasoning report (`LiabilityAssessment` + narrative) |
| `GET` | `/api/accidents/{id}/liability` | Same as `/report` legacy alias |

Pipeline stages (surfaced in `status`): `uploaded → tracking → vlm_analysis →
law_retrieval → reasoning → completed` (or `failed`, with `error`).

### Damage assessments
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/damage-assessments` | List assessments |
| `POST` | `/api/damage-assessments/upload` | **One-shot** images + vehicle info → runs the pipeline (what the UI uses) |
| `POST` | `/api/damage-assessments` | Create an empty assessment (JSON) |
| `POST` | `/api/damage-assessments/{id}/images` | Attach images (multipart) |
| `POST` | `/api/damage-assessments/{id}/estimate` | Run the cost pipeline (background) |
| `POST` | `/api/damage-assessments/{id}/corrections` | Apply reviewer corrections to parts |
| `GET` | `/api/damage-assessments/{id}` | Assessment result (parts, repair items, estimate) |
| `GET` | `/api/damage-assessments/{id}/images/{filename}` | Stored image |

### Laws
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/laws?q=…&limit=…` | Retrieve/search sections → `{law, matchScore, matchedFields}[]` |
| `GET` | `/api/laws/search` | Alias of the above |
| `GET` | `/api/laws/catalog` | Every indexed section (browse + filter chips) |
| `GET` | `/api/laws/{section_id}` | One section (e.g. `1140` or `VTL-1140`) |
| `GET` | `/api/laws/{section_id}/full` | Alias with full text only |
