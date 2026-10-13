# Accident-Intel Frontend

A React + TypeScript single-page application for AI-assisted traffic accident analysis. It lets investigators upload accident footage, view vehicle tracking overlays, read VLM-generated scene descriptions, retrieve relevant traffic laws, and generate liability reports — backed by the project's FastAPI service (real models) with an optional demo-data mode.

---

## Prerequisites

- Node.js ≥ 18
- npm ≥ 9

---

## Setup & Development

```bash
cd frontend
npm install
npm run dev
```

The development server runs at **http://localhost:5173** with hot module reloading.

---

## Build

```bash
npm run build
```

Output is written to `dist/`. Serve with any static file server (e.g. `npx serve dist`).

---

## Environment Variables

Copy `.env.example` to `.env` and adjust values before starting:

```bash
cp .env.example .env
```

| Variable            | Default | Description                                                  |
|---------------------|---------|--------------------------------------------------------------|
| `VITE_API_BASE_URL` | *(empty)* | Base URL of the backend. **Leave empty** to call relative `/api` URLs on the same origin — the Vite dev server proxies them to `http://localhost:8000` (`vite.config.ts`). Works on localhost and behind preview/proxy hosts. |
| `VITE_MOCK_MODE`    | `false` | `true` = local demo data from `src/mocks/`; `false` = the real models via the backend. (`VITE_USE_MOCK` is accepted as a legacy alias.) |

---

## Running against the backend

```bash
# terminal 1 — FastAPI service (project root)
.venv/bin/uvicorn src.api.main:app --host 0.0.0.0 --port 8000

# terminal 2 — UI
cd frontend && npm install && npm run dev
```

See `src/api/README.md` for the backend's own setup, mock flags and endpoint
reference.

## Demo / Mock Mode

With `VITE_MOCK_MODE=true` all data comes from local files under `src/mocks/`
and no network requests are made; a **Demo Data** badge appears on pages that
would otherwise show live results. With `VITE_MOCK_MODE=false` the pages call
the backend, show live pipeline status, and poll while an analysis runs.

---

## Routes

| Path              | Page                   | Description                                  |
|-------------------|------------------------|----------------------------------------------|
| `/dashboard`      | DashboardPage          | Overview stats, recent analyses, quick links |
| `/analysis/new`   | NewAnalysisPage        | 6-step analysis workflow (upload → report)   |
| `/analysis/:id`   | AnalysisDetailsPage    | Tabbed report for a specific accident        |
| `/history`        | AnalysisHistoryPage    | Searchable, filterable analysis history      |
| `/damage`         | DamageEstimatorPage    | 5-step vehicle damage + repair cost estimator|
| `/laws`           | TrafficLawsPage        | Searchable NYC traffic law reference library |
| `/settings`       | SettingsPage           | User preferences stored in localStorage      |
| `/*`              | NotFoundPage           | 404 catch-all                                |

---

## API Endpoint Reference

When `VITE_MOCK_MODE=false`, the frontend calls the following FastAPI endpoints:

| Method | Endpoint                        | Description |
|--------|---------------------------------|-------------|
| POST   | `/api/accidents/upload`         | Upload a video + metadata and start the analysis |
| GET    | `/api/accidents/:id`            | Fetch a single accident record (status, tracks, VLM, laws, liability) |
| GET    | `/api/accidents`                | List accident records (paginated) |
| DELETE | `/api/accidents/:id`            | Delete an accident record and its artifacts |
| GET    | `/api/accidents/:id/*`          | Sub-resources: `tracking`, `telemetry`, `vlm`, `laws`, `report`/`liability`, `video` |
| POST   | `/api/damage-assessments/upload`| Upload images + vehicle info and run the damage pipeline |
| GET    | `/api/damage-assessments`       | List damage assessments |
| POST   | `/api/laws` (or `/search`)      | Retrieve/search traffic laws (query params: `q`, `limit`) |
| GET    | `/api/laws/catalog`             | Every indexed VTL section (browse view + filter chips) |
| GET    | `/health`                       | Backend + model-status report |

---

## Project Structure

```
src/
├── app/           # Router and App entry
├── components/
│   ├── analysis/  # VLMDescription, LegalCitationCard, LiabilityReport, EvidenceCard
│   ├── common/    # PageHeader, DemoBadge, StatusBadge, EmptyState, LoadingState, ErrorState, ConfirmDialog
│   ├── damage/    # DamageAssessment, RepairCostBreakdown
│   ├── layout/    # AppShell, Sidebar, Topbar
│   ├── tracking/  # VehicleList, TrackingOverlay, Timeline
│   ├── ui/        # shadcn-style Radix UI primitives
│   └── upload/    # VideoUploader, VideoPreview, ImageUploader
├── hooks/         # Custom React hooks (useDamageAssessment, etc.)
├── mocks/         # Static demo data (accidentMocks, damageMocks, lawMocks)
├── pages/         # Top-level page components
├── services/      # API + mock service layer
├── styles/        # Global CSS
├── types/         # TypeScript type definitions
└── utils/         # pdfExport and other utilities
```

---

## Tech Stack

| Library              | Version  | Purpose                                   |
|----------------------|----------|-------------------------------------------|
| React                | 18       | UI rendering                              |
| React Router         | v6       | Client-side routing                       |
| TypeScript           | 5        | Type safety                               |
| Vite                 | 5        | Build tool & dev server                   |
| Tailwind CSS         | 3        | Utility-first styling                     |
| Radix UI             | various  | Accessible component primitives           |
| Recharts             | 3        | Data visualization (bar chart, pie chart) |
| jsPDF + html2canvas  | latest   | PDF export                                |
| Lucide React         | latest   | Icon set                                  |
| Axios                | latest   | HTTP client (real mode)                   |
