// Accident analysis service — talks to the FastAPI backend that wraps the
// project's real models (Qwen2-VL, YOLO+BoT-SORT, VTL RAG, Groq reasoning).
// In mock mode (VITE_MOCK_MODE=true) the same functions return local demo data
// so the UI can be developed without a GPU or API keys.

import type {
  AccidentRecord,
  VehicleTrack,
  VLMAnalysis,
  LiabilityAssessment,
} from '../types/accident';
import type { TrafficLaw } from '../types/law';
import type { PaginatedResponse } from '../types/common';
import {
  MOCK_ACCIDENTS,
  tracks001,
  vlmAnalysis001,
  liabilityAssessment001,
} from '../mocks/accidentMocks';
import { MOCK_TRAFFIC_LAWS } from '../mocks/lawMocks';
import { isMockMode, mockDelay, get, getOrNull, post, postForm, del } from './apiClient';

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/** List accident analyses with pagination */
export async function getAccidents(
  page: number = 1,
  pageSize: number = 20,
): Promise<PaginatedResponse<AccidentRecord>> {
  if (isMockMode) {
    await mockDelay(500);
    const start = (page - 1) * pageSize;
    const items = MOCK_ACCIDENTS.slice(start, start + pageSize);
    return {
      items,
      total: MOCK_ACCIDENTS.length,
      page,
      pageSize,
      totalPages: Math.ceil(MOCK_ACCIDENTS.length / pageSize),
    };
  }
  return get<PaginatedResponse<AccidentRecord>>('/api/accidents', {
    page,
    page_size: pageSize,
  });
}

/** Fetch a single accident record by ID */
export async function getAccident(id: string): Promise<AccidentRecord> {
  if (isMockMode) {
    await mockDelay(400);
    const record = MOCK_ACCIDENTS.find((a) => a.id === id);
    if (!record) throw new Error(`Accident ${id} not found`);
    return record;
  }
  return get<AccidentRecord>(`/api/accidents/${id}`);
}

/** Fetch an accident by ID, returning null when it does not exist (404). */
export async function getAccidentOrNull(id: string): Promise<AccidentRecord | null> {
  if (isMockMode) {
    await mockDelay(300);
    return MOCK_ACCIDENTS.find((a) => a.id === id) ?? null;
  }
  return getOrNull<AccidentRecord>(`/api/accidents/${id}`);
}

/**
 * Upload a video and start a new analysis.
 *
 * The backend creates the record, stores the video and (autostart) kicks off
 * the pipeline: tracking → VLM → law retrieval → reasoning.
 */
export async function uploadVideo(
  file: File,
  metadata: {
    location?: string;
    incidentDate?: string;
    description?: string;
    notes?: string;
  },
  autostart: boolean = true,
): Promise<AccidentRecord> {
  if (isMockMode) {
    await mockDelay(800);
    const newRecord: AccidentRecord = {
      ...MOCK_ACCIDENTS[0],
      id: `mock-${String(Date.now()).slice(-6)}`,
      videoFilename: file.name,
      uploadDate: new Date().toISOString(),
      location: metadata.location,
      incidentDate: metadata.incidentDate,
      description: metadata.description,
      notes: metadata.notes,
      status: 'completed',
      isDemoData: true,
    };
    return newRecord;
  }
  const formData = new FormData();
  formData.append('file', file);
  formData.append('location', metadata.location ?? '');
  formData.append('incident_date', metadata.incidentDate ?? '');
  formData.append('description', metadata.description ?? '');
  formData.append('notes', metadata.notes ?? '');
  formData.append('autostart', String(autostart));
  return postForm<AccidentRecord>('/api/accidents/upload', formData);
}

/** Re-run / start the analysis pipeline for an existing accident. */
export async function startAnalysis(id: string): Promise<{ status: string; message: string }> {
  if (isMockMode) {
    await mockDelay(300);
    return { status: 'processing', message: 'Mock analysis started' };
  }
  return post<{ status: string; message: string }>(`/api/accidents/${id}/analyze`);
}

/** Get vehicle tracking data (UI shape, normalised bounding boxes). */
export async function getTrackingData(id: string): Promise<VehicleTrack[]> {
  if (isMockMode) {
    await mockDelay(600);
    const record = MOCK_ACCIDENTS.find((a) => a.id === id);
    return record?.tracks ?? tracks001;
  }
  const tracks = await getOrNull<VehicleTrack[]>(`/api/accidents/${id}/tracking`);
  return tracks ?? [];
}

/** Get the tracker's telemetry bundle (speeds, events, collision candidates). */
export async function getTelemetry(id: string): Promise<Record<string, unknown> | null> {
  if (isMockMode) {
    await mockDelay(200);
    return null;
  }
  return getOrNull<Record<string, unknown>>(`/api/accidents/${id}/telemetry`);
}

/** Get the VLM (vision-language model) analysis. */
export async function getVLMAnalysis(id: string): Promise<VLMAnalysis | null> {
  if (isMockMode) {
    await mockDelay(700);
    const record = MOCK_ACCIDENTS.find((a) => a.id === id);
    return record?.vlmAnalysis ?? vlmAnalysis001;
  }
  return getOrNull<VLMAnalysis>(`/api/accidents/${id}/vlm`);
}

/** Get the NYC VTL sections retrieved for this accident. */
export async function getRetrievedLaws(id: string): Promise<TrafficLaw[]> {
  if (isMockMode) {
    await mockDelay(500);
    return MOCK_TRAFFIC_LAWS.slice(0, 4);
  }
  const laws = await getOrNull<TrafficLaw[]>(`/api/accidents/${id}/laws`);
  return laws ?? [];
}

/** Get the liability assessment produced by the reasoning model. */
export async function getLiabilityAssessment(id: string): Promise<LiabilityAssessment | null> {
  if (isMockMode) {
    await mockDelay(800);
    const record = MOCK_ACCIDENTS.find((a) => a.id === id);
    return record?.liabilityAssessment ?? liabilityAssessment001;
  }
  return getOrNull<LiabilityAssessment>(`/api/accidents/${id}/liability`);
}

/** Delete an accident record and its artifacts. */
export async function deleteAccident(id: string): Promise<void> {
  if (isMockMode) {
    await mockDelay(300);
    return;
  }
  await del<void>(`/api/accidents/${id}`);
}

/** Absolute backend URL for a stored artifact (video, annotated video). */
export function artifactUrl(relativePath?: string | null): string | undefined {
  if (!relativePath) return undefined;
  if (/^https?:\/\//.test(relativePath)) return relativePath;
  const base = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '';
  return `${base}${relativePath}`;
}
