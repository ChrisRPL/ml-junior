import type { AgentEvent } from '@/types/events';
import { logger } from '@/utils/logger';
import { loadEventSequenceCursor, saveEventSequenceCursor } from '@/lib/sse-event-cursors';

function parseSequence(value: unknown): number | null {
  if (typeof value === 'number' && Number.isSafeInteger(value) && value >= 1) {
    return value;
  }
  if (typeof value !== 'string') return null;

  const normalized = value.trim();
  if (!/^\d+$/.test(normalized)) return null;

  const sequence = Number(normalized);
  return Number.isSafeInteger(sequence) && sequence >= 1 ? sequence : null;
}

export function getAgentEventSequence(event: AgentEvent): number | null {
  return (
    parseSequence(event.sequence) ??
    parseSequence(event.cursor) ??
    parseSequence(event.sse_id)
  );
}

function parseSSEData(data: string, sseId: string | undefined): AgentEvent | null {
  try {
    const parsed: unknown = JSON.parse(data);
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      return null;
    }

    const event = parsed as AgentEvent;
    if (typeof event.event_type !== 'string') return null;

    const sequence = parseSequence(event.sequence) ?? parseSequence(sseId);
    return {
      ...event,
      ...(sseId !== undefined && {
        id: event.id ?? sseId,
        sse_id: sseId,
        cursor: sseId,
      }),
      ...(sequence !== null && { sequence }),
    };
  } catch {
    logger.warn('SSE parse error:', data);
    return null;
  }
}

export function createSSEParserStream(): TransformStream<string, AgentEvent> {
  let buffer = '';
  let eventId: string | undefined;
  let dataLines: string[] = [];

  const flushEvent = (controller: TransformStreamDefaultController<AgentEvent>) => {
    if (dataLines.length === 0) {
      eventId = undefined;
      return;
    }

    const event = parseSSEData(dataLines.join('\n'), eventId);
    if (event) controller.enqueue(event);

    eventId = undefined;
    dataLines = [];
  };

  const processLine = (
    rawLine: string,
    controller: TransformStreamDefaultController<AgentEvent>,
  ) => {
    const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine;

    if (line === '') {
      flushEvent(controller);
      return;
    }
    if (line.startsWith(':')) return;

    const separatorIndex = line.indexOf(':');
    const field = separatorIndex === -1 ? line : line.slice(0, separatorIndex);
    const rawValue = separatorIndex === -1 ? '' : line.slice(separatorIndex + 1);
    const value = rawValue.startsWith(' ') ? rawValue.slice(1) : rawValue;

    if (field === 'data') {
      dataLines.push(value);
    } else if (field === 'id') {
      eventId = value;
    }
  };

  return new TransformStream<string, AgentEvent>({
    transform(chunk, controller) {
      buffer += chunk;
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';

      for (const line of lines) {
        processLine(line, controller);
      }
    },
    flush(controller) {
      if (buffer.length > 0) {
        processLine(buffer, controller);
      }
      flushEvent(controller);
    },
  });
}

export function createEventCursorFilterStream(sessionId: string): TransformStream<AgentEvent, AgentEvent> {
  let lastSequence = loadEventSequenceCursor(sessionId) ?? 0;

  return new TransformStream<AgentEvent, AgentEvent>({
    transform(event, controller) {
      const sequence = getAgentEventSequence(event);
      if (sequence === null) {
        controller.enqueue(event);
        return;
      }

      lastSequence = Math.max(lastSequence, loadEventSequenceCursor(sessionId) ?? 0);
      if (sequence <= lastSequence) return;

      lastSequence = sequence;
      saveEventSequenceCursor(sessionId, sequence);
      controller.enqueue({ ...event, sequence });
    },
  });
}
