// Traffic law service — searches the project's VTL RAG index through the
// backend (keyword anchors + dense/BM25 hybrid retrieval). Mock mode returns
// the local demo laws.

import type { TrafficLaw, LawSearchResult } from '../types/law';
import { MOCK_TRAFFIC_LAWS } from '../mocks/lawMocks';
import { isMockMode, mockDelay, get } from './apiClient';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface LawSearchFilters {
  jurisdiction?: string;
  topic?: string;
  section?: string;
}

// ---------------------------------------------------------------------------
// Mock helpers
// ---------------------------------------------------------------------------

function mockSearch(query: string, filters: LawSearchFilters): LawSearchResult[] {
  const lower = query.toLowerCase();
  const filtered = MOCK_TRAFFIC_LAWS.filter((law) => {
    const matchesQuery =
      !query ||
      law.title.toLowerCase().includes(lower) ||
      law.section.toLowerCase().includes(lower) ||
      law.excerpt.toLowerCase().includes(lower) ||
      law.fullText.toLowerCase().includes(lower);

    const matchesJurisdiction =
      !filters.jurisdiction ||
      law.jurisdiction.toLowerCase().includes(filters.jurisdiction.toLowerCase());

    const matchesTopic =
      !filters.topic || law.topics.some((t) => t.toLowerCase().includes(filters.topic!.toLowerCase()));

    const matchesSection =
      !filters.section || law.section.toLowerCase().includes(filters.section.toLowerCase());

    return matchesQuery && matchesJurisdiction && matchesTopic && matchesSection;
  });

  return filtered.map((law) => ({
    law,
    matchScore: law.relevanceScore ?? 0.5,
    matchedFields: query
      ? (['title', 'section', 'excerpt', 'fullText'] as const).filter((field) =>
          (law[field] as string).toLowerCase().includes(lower),
        )
      : [],
  }));
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/** Search traffic laws by query string, with optional filters */
export async function searchLaws(
  query: string = '',
  filters: LawSearchFilters = {},
): Promise<LawSearchResult[]> {
  if (isMockMode) {
    await mockDelay(300);
    return mockSearch(query, filters);
  }

  const q = query.trim();

  // Browsing (no query): list the whole indexed corpus, newest first, and
  // apply the chips locally — same behaviour as the demo data had.
  if (!q) {
    let laws = await get<TrafficLaw[]>('/api/laws/catalog');
    if (filters.jurisdiction) {
      const jur = filters.jurisdiction.toLowerCase();
      laws = laws.filter((l) => l.jurisdiction.toLowerCase().includes(jur));
    }
    if (filters.topic) {
      laws = laws.filter((l) => l.topics.includes(filters.topic as string));
    }
    return laws.map((law) => ({ law, matchScore: 1, matchedFields: [] }));
  }

  const results = await get<LawSearchResult[]>('/api/laws', {
    q,
    ...(filters.jurisdiction ? { jurisdiction: filters.jurisdiction } : {}),
    ...(filters.topic ? { topic: filters.topic } : {}),
    limit: 20,
  });

  // Section-level filters are applied client-side (retrieval scores whole
  // sections, not the chip values).
  return results.filter((r) => {
    if (filters.jurisdiction && r.law.jurisdiction !== filters.jurisdiction) return false;
    if (filters.topic && !r.law.topics.includes(filters.topic)) return false;
    return true;
  });
}

/**
 * List every section in the prepared VTL index (used by the Traffic Laws page
 * to browse the corpus and build its jurisdiction/topic filters).
 */
export async function listLawSections(): Promise<TrafficLaw[]> {
  if (isMockMode) {
    await mockDelay(200);
    return MOCK_TRAFFIC_LAWS;
  }
  return get<TrafficLaw[]>('/api/laws/catalog');
}

/** Fetch a single traffic law by ID (e.g. "1140" or "VTL-1140"). */
export async function getLaw(id: string): Promise<TrafficLaw> {
  if (isMockMode) {
    await mockDelay(300);
    const law = MOCK_TRAFFIC_LAWS.find((l) => l.id === id);
    if (!law) throw new Error(`Law ${id} not found`);
    return law;
  }
  return get<TrafficLaw>(`/api/laws/${encodeURIComponent(id)}`);
}
