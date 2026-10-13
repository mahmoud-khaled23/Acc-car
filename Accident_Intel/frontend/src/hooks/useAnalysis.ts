// Custom hooks for accident analysis data — wraps accidentService calls.
//
// The backend runs the analysis pipeline as a background task
// (tracking → VLM → laws → reasoning), so `useAnalysisPipeline` polls the
// record while it is in progress and stops as soon as it completes/fails.

import { useState, useEffect, useCallback, useRef } from 'react';
import type { AccidentRecord } from '../types/accident';
import type { PaginatedResponse, AnalysisStatus } from '../types/common';
import {
  getAccidents,
  getAccident,
  getAccidentOrNull,
} from '../services/accidentService';

// ---------------------------------------------------------------------------
// status helpers
// ---------------------------------------------------------------------------

/** Statuses during which the backend is still working. */
export const IN_PROGRESS_STATUSES: AnalysisStatus[] = [
  'uploaded',
  'tracking',
  'vlm_analysis',
  'law_retrieval',
  'reasoning',
];

export function isInProgress(status: AnalysisStatus | undefined): boolean {
  return status ? IN_PROGRESS_STATUSES.includes(status) : false;
}

// ---------------------------------------------------------------------------
// useAccidents — paginated list of all accident records
// ---------------------------------------------------------------------------

export interface UseAccidentsResult {
  accidents: AccidentRecord[];
  total: number;
  totalPages: number;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useAccidents(page: number = 1, pageSize: number = 20): UseAccidentsResult {
  const [data, setData] = useState<PaginatedResponse<AccidentRecord> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState<number>(0);

  const refetch = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    getAccidents(page, pageSize)
      .then((result) => {
        if (!cancelled) {
          setData(result);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load analyses');
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [page, pageSize, tick]);

  return {
    accidents: data?.items ?? [],
    total: data?.total ?? 0,
    totalPages: data?.totalPages ?? 1,
    loading,
    error,
    refetch,
  };
}

// ---------------------------------------------------------------------------
// useAnalysis — single accident record (one-shot fetch)
// ---------------------------------------------------------------------------

export interface UseAnalysisResult {
  accident: AccidentRecord | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useAnalysis(id?: string): UseAnalysisResult {
  const [accident, setAccident] = useState<AccidentRecord | null>(null);
  const [loading, setLoading] = useState<boolean>(Boolean(id));
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState<number>(0);

  const refetch = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!id) {
      setAccident(null);
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    getAccident(id)
      .then((result) => {
        if (!cancelled) {
          setAccident(result);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : `Failed to load analysis ${id}`);
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [id, tick]);

  return { accident, loading, error, refetch };
}

// ---------------------------------------------------------------------------
// useAnalysisPipeline — live accident record while the pipeline runs
// ---------------------------------------------------------------------------

export interface UseAnalysisPipelineResult {
  accident: AccidentRecord | null;
  loading: boolean;
  error: string | null;
  /** True while the backend is still running a stage. */
  running: boolean;
  refetch: () => void;
}

export function useAnalysisPipeline(
  id?: string,
  options: { pollMs?: number; enabled?: boolean } = {},
): UseAnalysisPipelineResult {
  const { pollMs = 3000, enabled = true } = options;
  const [accident, setAccident] = useState<AccidentRecord | null>(null);
  const [loading, setLoading] = useState<boolean>(Boolean(id));
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState<number>(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refetch = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!id || !enabled) {
      setLoading(false);
      return;
    }

    let cancelled = false;

    async function poll() {
      try {
        const record = await getAccidentOrNull(id as string);
        if (cancelled) return;
        if (!record) {
          setError(`Analysis ${id} not found.`);
          setLoading(false);
          return;
        }
        setAccident(record);
        setError(null);
        setLoading(false);

        if (isInProgress(record.status)) {
          timerRef.current = setTimeout(poll, pollMs);
        }
      } catch (err: unknown) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Failed to load analysis');
        setLoading(false);
        // keep polling on transient errors so the UI recovers
        timerRef.current = setTimeout(poll, pollMs);
      }
    }

    void poll();

    return () => {
      cancelled = true;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [id, enabled, pollMs, tick]);

  return {
    accident,
    loading,
    error,
    running: isInProgress(accident?.status),
    refetch,
  };
}
