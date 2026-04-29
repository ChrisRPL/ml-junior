import { logger } from '@/utils/logger';

const STORAGE_KEY = 'ml-junior-sse-event-cursors';
const MAX_SESSIONS = 100;

type CursorMap = Record<string, number>;

function isValidSequence(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 1;
}

function readAll(): CursorMap {
  try {
    if (typeof localStorage === 'undefined') return {};
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};

    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      return {};
    }

    const cursors: CursorMap = {};
    for (const [sessionId, value] of Object.entries(parsed)) {
      if (isValidSequence(value)) {
        cursors[sessionId] = value;
      }
    }
    return cursors;
  } catch {
    return {};
  }
}

function writeAll(map: CursorMap): void {
  try {
    if (typeof localStorage === 'undefined') return;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(map));
  } catch (error) {
    logger.warn('Failed to persist SSE event cursor:', error);
  }
}

export function loadEventSequenceCursor(sessionId: string): number | null {
  const sequence = readAll()[sessionId];
  return isValidSequence(sequence) ? sequence : null;
}

export function saveEventSequenceCursor(sessionId: string, sequence: number): void {
  if (!isValidSequence(sequence)) return;

  const map = readAll();
  const current = map[sessionId] ?? 0;
  if (sequence <= current) return;

  map[sessionId] = sequence;

  const keys = Object.keys(map);
  if (keys.length > MAX_SESSIONS) {
    const toRemove = keys.slice(0, keys.length - MAX_SESSIONS);
    for (const key of toRemove) delete map[key];
  }

  writeAll(map);
}

export function clearEventSequenceCursor(sessionId: string): void {
  const map = readAll();
  if (!(sessionId in map)) return;
  delete map[sessionId];
  writeAll(map);
}

export function buildEventStreamPath(sessionId: string): string {
  const cursor = loadEventSequenceCursor(sessionId);
  if (cursor === null) return `/api/events/${sessionId}`;
  return `/api/events/${sessionId}?after_sequence=${encodeURIComponent(String(cursor))}`;
}
