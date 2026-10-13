// Damage assessment service — talks to the FastAPI backend that wraps the
// project's Car_damage_cost pipeline (YOLO-seg damage/parts models + cost
// engine). Mock mode returns local demo data.

import type { DamageAssessmentRecord, VehicleInfo, DamagePart } from '../types/damage';
import { MOCK_DAMAGE_ASSESSMENTS } from '../mocks/damageMocks';
import { isMockMode, mockDelay, get, getOrNull, postForm, post } from './apiClient';

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/** List all damage assessments */
export async function getDamageAssessments(): Promise<DamageAssessmentRecord[]> {
  if (isMockMode) {
    await mockDelay(400);
    return MOCK_DAMAGE_ASSESSMENTS;
  }
  return get<DamageAssessmentRecord[]>('/api/damage-assessments');
}

/** Fetch a single damage assessment by ID */
export async function getDamageAssessment(id: string): Promise<DamageAssessmentRecord> {
  if (isMockMode) {
    await mockDelay(400);
    const record = MOCK_DAMAGE_ASSESSMENTS.find((d) => d.id === id);
    if (!record) throw new Error(`Damage assessment ${id} not found`);
    return record;
  }
  return get<DamageAssessmentRecord>(`/api/damage-assessments/${id}`);
}

/** Fetch a single assessment, returning null when it no longer exists. */
export async function getDamageAssessmentOrNull(
  id: string,
): Promise<DamageAssessmentRecord | null> {
  if (isMockMode) {
    await mockDelay(200);
    return MOCK_DAMAGE_ASSESSMENTS.find((d) => d.id === id) ?? null;
  }
  return getOrNull<DamageAssessmentRecord>(`/api/damage-assessments/${id}`);
}

/**
 * Upload damage images + vehicle info and start the assessment.
 *
 * The backend runs the segmentation and cost pipeline in the background, so
 * the returned record is usually in ``queued``/``processing`` state — poll
 * ``getDamageAssessment`` (see ``useDamageAssessmentPolling``) until it is
 * ``completed`` or ``failed``.
 */
export async function uploadDamageImages(
  files: File[],
  vehicleInfo: VehicleInfo,
  options: { tier?: string; currency?: string } = {},
): Promise<DamageAssessmentRecord> {
  if (isMockMode) {
    await mockDelay(900);
    const base = MOCK_DAMAGE_ASSESSMENTS[0];
    return {
      ...base,
      id: `mock-${String(Date.now()).slice(-6)}`,
      sessionId: `session-${String(Date.now()).slice(-6)}`,
      vehicleInfo,
      imageUrls: files.map((f) => URL.createObjectURL(f)),
      assessmentDate: new Date().toISOString(),
      status: 'completed',
      isDemoData: true,
    } as DamageAssessmentRecord;
  }

  const formData = new FormData();
  files.forEach((file) => formData.append('images', file));
  formData.append('make', vehicleInfo.make);
  formData.append('model', vehicleInfo.model);
  formData.append('year', String(vehicleInfo.year));
  formData.append('color', vehicleInfo.color ?? '');
  if (vehicleInfo.mileage !== undefined) formData.append('mileage', String(vehicleInfo.mileage));
  if (vehicleInfo.vin) formData.append('vin', vehicleInfo.vin);
  if (vehicleInfo.repairLocation) formData.append('repair_location', vehicleInfo.repairLocation);
  formData.append('tier', options.tier ?? 'mid');
  formData.append('currency', options.currency ?? 'EGP');

  return postForm<DamageAssessmentRecord>('/api/damage-assessments/upload', formData);
}

/** Trigger the (background) estimation for an assessment that already has images. */
export async function startDamageEstimate(id: string): Promise<{ status: string }> {
  if (isMockMode) {
    await mockDelay(200);
    return { status: 'processing' };
  }
  return post<{ status: string }>(`/api/damage-assessments/${id}/estimate`);
}

/** Apply user-supplied corrections to an existing damage assessment. */
export async function updateDamageCorrections(
  id: string,
  corrections: Partial<DamagePart>[],
): Promise<DamageAssessmentRecord> {
  if (isMockMode) {
    await mockDelay(400);
    const record = MOCK_DAMAGE_ASSESSMENTS.find((d) => d.id === id);
    if (!record) throw new Error(`Damage assessment ${id} not found`);
    const updatedParts: DamagePart[] = record.damagedParts.map((part) => {
      const correction = corrections.find((c) => c.id === part.id);
      return correction ? { ...part, ...correction, source: 'user' as const } : part;
    });
    return { ...record, damagedParts: updatedParts };
  }
  return post<DamageAssessmentRecord>(`/api/damage-assessments/${id}/corrections`, corrections);
}
