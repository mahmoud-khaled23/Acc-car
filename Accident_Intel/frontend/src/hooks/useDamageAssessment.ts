// Custom hooks for damage assessment data — wraps damageService calls.
//
// Damage estimation runs in a backend background task, so `useDamagePolling`
// keeps fetching an assessment until it reaches a terminal state.

import { useState, useEffect, useCallback } from 'react';
import type { DamageAssessmentRecord } from '../types/damage';
import {
  getDamageAssessments,
  getDamageAssessmentOrNull,
} from '../services/damageService';

// ---------------------------------------------------------------------------
// useDamageAssessments — list of all damage assessment records
// ---------------------------------------------------------------------------

export interface UseDamageAssessmentsResult {
  assessments: DamageAssessmentRecord[];
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useDamageAssessments(): UseDamageAssessmentsResult {
  const [assessments, setAssessments] = useState<DamageAssessmentRecord[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState<number>(0);

  const refetch = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    getDamageAssessments()
      .then((result) => {
        if (!cancelled) {
          setAssessments(result);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load damage assessments');
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [tick]);

  return { assessments, loading, error, refetch };
}

// ---------------------------------------------------------------------------
// useDamageAssessment — single assessment by ID
// ---------------------------------------------------------------------------

export interface UseDamageAssessmentResult {
  assessment: DamageAssessmentRecord | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useDamageAssessment(id?: string): UseDamageAssessmentResult {
  const [assessment, setAssessment] = useState<DamageAssessmentRecord | null>(null);
  const [loading, setLoading] = useState<boolean>(Boolean(id));
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState<number>(0);

  const refetch = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!id) {
      setAssessment(null);
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    getDamageAssessmentOrNull(id)
      .then((result) => {
        if (cancelled) return;
        if (!result) {
          setError(`Damage assessment ${id} not found.`);
        } else {
          setAssessment(result);
        }
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : `Failed to load damage assessment ${id}`,
          );
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [id, tick]);

  return { assessment, loading, error, refetch };
}

// ---------------------------------------------------------------------------
// useDamagePolling — poll an assessment until it is completed/failed
// ---------------------------------------------------------------------------

export interface UseDamagePollingResult {
  assessment: DamageAssessmentRecord | null;
  /** True while the backend is still estimating. */
  running: boolean;
  error: string | null;
}

export function useDamagePolling(
  id?: string,
  options: { pollMs?: number } = {},
): UseDamagePollingResult {
  const { pollMs = 2500 } = options;
  const [assessment, setAssessment] = useState<DamageAssessmentRecord | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function poll() {
      try {
        const record = await getDamageAssessmentOrNull(id as string);
        if (cancelled) return;
        if (!record) {
          setError('Assessment not found.');
          return;
        }
        setAssessment(record);
        setError(record.error ?? null);
        const status = String(record.status ?? '');
        if (status !== 'completed' && status !== 'failed') {
          timer = setTimeout(poll, pollMs);
        }
      } catch (err: unknown) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Failed to load the assessment');
        timer = setTimeout(poll, pollMs);
      }
    }

    void poll();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [id, pollMs]);

  const status = String(assessment?.status ?? '');
  return {
    assessment,
    running: Boolean(id) && status !== '' && status !== 'completed' && status !== 'failed',
    error,
  };
}
