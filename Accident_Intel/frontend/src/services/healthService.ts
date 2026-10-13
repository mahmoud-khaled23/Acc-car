// Backend health / model-status service.
// Used by the Settings page to show which models are actually live.

import { isMockMode, get } from './apiClient';

export interface ModelStatus {
  vlm: { model: string; mock: boolean };
  tracking: { model: string; mock: boolean };
  rag: { mode: string; index: string; rerank: boolean; mock: boolean };
  reasoning: { provider: string; model: string; keyConfigured: boolean; mock: boolean };
  damage: { weights: string; mock: boolean };
}

export interface HealthResponse {
  status: string;
  version: string;
  models: ModelStatus;
}

export async function getHealth(): Promise<HealthResponse | null> {
  if (isMockMode) return null;
  try {
    return await get<HealthResponse>('/health');
  } catch {
    return null; // backend unreachable — the UI just shows "offline"
  }
}
