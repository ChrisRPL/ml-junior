import { Box, Chip, Divider, Stack, Typography } from '@mui/material';
import type { ReactNode } from 'react';
import type { ActiveJobRef, OperationRef, ProjectSnapshot } from '@/types/project';
import {
  labelSx,
  monoLineSx,
  rowSx,
  toneBg,
  toneBorder,
  toneFg,
  type Tone,
} from './projectDashboardTokens';

interface ArtifactJobPanelProps {
  snapshot: ProjectSnapshot;
}

interface RowChip {
  label: ReactNode;
  tone: Tone;
  mono?: boolean;
}

interface ArtifactItemModel {
  key: string;
  title: string;
  detail: string;
  kind: string;
  tone: Tone;
}

export default function ArtifactJobPanel({ snapshot }: ArtifactJobPanelProps) {
  const artifactItems = snapshot.evidence_summary.items
    .map(toArtifactItemModel)
    .filter((item): item is ArtifactItemModel => item !== null);

  return (
    <Stack spacing={1.25}>
      <Stack direction="row" spacing={0.75} sx={{ flexWrap: 'wrap', rowGap: 0.75 }}>
        <ToneChip label={`${snapshot.active_jobs.length} active jobs`} tone={snapshot.active_jobs.length > 0 ? 'blue' : 'muted'} />
        <ToneChip label={`${snapshot.operation_refs.length} operation refs`} tone={snapshot.operation_refs.length > 0 ? 'amber' : 'muted'} />
        <ToneChip label={`${artifactItems.length} artifact-like items`} tone={artifactItems.length > 0 ? 'good' : 'muted'} />
        <ToneChip label={humanize(snapshot.evidence_summary.status)} tone={summaryTone(snapshot.evidence_summary.status)} />
      </Stack>

      <MonitorSection title="Active jobs" count={snapshot.active_jobs.length}>
        {snapshot.active_jobs.length > 0 ? (
          <Stack spacing={0}>
            {snapshot.active_jobs.map((job, index) => (
              <JobRow key={`${jobKey(job)}:${index}`} job={job} />
            ))}
          </Stack>
        ) : (
          <Placeholder text="Snapshot has no active jobs." />
        )}
      </MonitorSection>

      <MonitorSection title="Operation refs" count={snapshot.operation_refs.length}>
        {snapshot.operation_refs.length > 0 ? (
          <Box sx={scrollListSx}>
            {snapshot.operation_refs.map((operation, index) => (
              <OperationRow key={`${operation.id}:${index}`} operation={operation} />
            ))}
          </Box>
        ) : (
          <Placeholder text="Snapshot has no operation refs." />
        )}
      </MonitorSection>

      <MonitorSection title="Artifact-like evidence" count={artifactItems.length}>
        {artifactItems.length > 0 ? (
          <Box sx={scrollListSx}>
            {artifactItems.map((item, index) => (
              <ArtifactRow key={`${item.key}:${index}`} item={item} />
            ))}
          </Box>
        ) : (
          <Placeholder text="Snapshot has no artifact-like evidence items." />
        )}
      </MonitorSection>
    </Stack>
  );
}

function MonitorSection({ title, count, children }: { title: string; count: number; children: ReactNode }) {
  return (
    <Box>
      <Divider sx={{ mb: 1 }} />
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1, mb: 0.5 }}>
        <Typography variant="caption" sx={labelSx}>{title}</Typography>
        <ToneChip label={count} tone={count > 0 ? 'blue' : 'muted'} mono />
      </Box>
      {children}
    </Box>
  );
}

function JobRow({ job }: { job: ActiveJobRef }) {
  const status = readString(job, 'status') ?? 'unknown';
  const tool = readString(job, 'tool') ?? 'tool';
  const toolCallId = readString(job, 'tool_call_id');
  const jobId = readString(job, 'job_id');
  const url = readString(job, 'url');
  const updatedAt = readString(job, 'updated_at');
  const createdAt = readString(job, 'created_at');
  const sequence = readNumber(job, 'source_event_sequence');

  return (
    <MonitorRow
      title={tool}
      detail={compactParts([
        jobId ? `job ${shortId(jobId)}` : null,
        toolCallId ? `tool call ${shortId(toolCallId)}` : null,
        sequence !== undefined ? `seq ${sequence}` : null,
        updatedAt ? `updated ${formatDate(updatedAt)}` : createdAt ? `created ${formatDate(createdAt)}` : null,
        url ? `url ${url}` : null,
      ])}
      chips={[
        { label: humanize(status), tone: statusTone(status) },
        { label: readString(job, 'source') ?? 'snapshot', tone: 'muted' },
      ]}
    />
  );
}

function OperationRow({ operation }: { operation: OperationRef }) {
  const updatedAt = readString(operation, 'updated_at');
  const createdAt = readString(operation, 'created_at');
  const sequence = readNumber(operation, 'source_event_sequence');
  const dataKeys = operation.data ? Object.keys(operation.data) : [];

  return (
    <MonitorRow
      title={`${operation.type}${operation.tool ? ` / ${operation.tool}` : ''}`}
      detail={compactParts([
        `id ${shortId(operation.id)}`,
        operation.tool_call_id ? `tool call ${shortId(operation.tool_call_id)}` : null,
        operation.job_id ? `job ${shortId(operation.job_id)}` : null,
        operation.idempotency_key ? `idempotency ${shortId(operation.idempotency_key)}` : null,
        sequence !== undefined ? `seq ${sequence}` : null,
        updatedAt ? `updated ${formatDate(updatedAt)}` : createdAt ? `created ${formatDate(createdAt)}` : null,
        dataKeys.length > 0 ? `data ${dataKeys.slice(0, 4).join(', ')}` : null,
      ])}
      chips={[{ label: humanize(operation.status), tone: statusTone(operation.status) }]}
    />
  );
}

function ArtifactRow({ item }: { item: ArtifactItemModel }) {
  return (
    <MonitorRow
      title={item.title}
      detail={item.detail}
      chips={[{ label: item.kind, tone: item.tone, mono: true }]}
    />
  );
}

function MonitorRow({ title, detail, chips }: { title: string; detail: string; chips: RowChip[] }) {
  return (
    <Box
      sx={{
        ...rowSx,
        gridTemplateColumns: { xs: '1fr', sm: 'minmax(0, 1fr) minmax(0, auto)' },
        alignItems: 'start',
      }}
    >
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="body2" sx={{ fontWeight: 600, overflowWrap: 'anywhere' }}>{title}</Typography>
        {detail && <Typography variant="caption" sx={monoLineSx}>{detail}</Typography>}
      </Box>
      <Stack
        direction="row"
        spacing={0.5}
        sx={{
          justifyContent: { xs: 'flex-start', sm: 'flex-end' },
          flexWrap: 'wrap',
          rowGap: 0.5,
          minWidth: 0,
        }}
      >
        {chips.map((chip, index) => (
          <ToneChip key={index} label={chip.label} tone={chip.tone} mono={chip.mono} />
        ))}
      </Stack>
    </Box>
  );
}

function Placeholder({ text }: { text: string }) {
  return (
    <Typography variant="body2" sx={{ color: 'var(--muted-text)', py: 0.25 }}>
      {text}
    </Typography>
  );
}

function toArtifactItemModel(item: unknown, index: number): ArtifactItemModel | null {
  if (!isRecord(item)) return null;

  const artifactId = readString(item, 'artifact_id');
  if (artifactId) {
    return {
      key: artifactId,
      title: firstString(item, ['label', 'title', 'type', 'artifact_id']) ?? 'Artifact',
      detail: compactDetails(item, ['artifact_id', 'source_job_id', 'source_tool_call_id', 'source', 'path', 'uri', 'digest', 'privacy_class', 'created_at']),
      kind: 'artifact',
      tone: 'blue',
    };
  }

  const metricId = readString(item, 'metric_id');
  if (metricId) {
    const value = formatScalar(item.value);
    const unit = readString(item, 'unit');
    const title = firstString(item, ['name', 'label', 'title', 'metric_id']) ?? 'Metric';
    return {
      key: metricId,
      title: value ? `${title}: ${value}${unit ? ` ${unit}` : ''}` : title,
      detail: compactDetails(item, ['metric_id', 'source', 'step', 'recorded_at']),
      kind: 'metric',
      tone: 'good',
    };
  }

  const logId = readString(item, 'log_id');
  if (logId) {
    return {
      key: logId,
      title: firstString(item, ['label', 'title', 'source', 'log_id']) ?? 'Log',
      detail: compactDetails(item, ['log_id', 'source', 'uri']),
      kind: 'log',
      tone: 'muted',
    };
  }

  if (!hasArtifactLikeFields(item)) return null;

  const key = firstString(item, ['id', 'evidence_id', 'uri', 'path', 'digest']) ?? `artifact-like-${index}`;
  return {
    key,
    title: firstString(item, ['title', 'label', 'name', 'summary', 'id']) ?? 'Evidence item',
    detail: compactDetails(item, ['id', 'evidence_id', 'source_job_id', 'source_tool_call_id', 'source', 'path', 'uri', 'digest', 'created_at', 'updated_at']),
    kind: firstString(item, ['kind', 'type', 'source']) ?? 'item',
    tone: 'amber',
  };
}

function hasArtifactLikeFields(item: Record<string, unknown>): boolean {
  return ['path', 'uri', 'digest', 'source_job_id', 'source_tool_call_id'].some((field) => readString(item, field));
}

function compactDetails(item: Record<string, unknown>, fields: string[]) {
  return fields
    .map((field) => {
      const value = formatScalar(item[field]);
      if (!value) return null;
      const display = field.endsWith('_id') || field === 'id' ? shortId(value) : value;
      return `${humanize(field)} ${display}`;
    })
    .filter((part): part is string => part !== null)
    .join(' / ');
}

function compactParts(parts: Array<string | null>) {
  return parts.filter((part): part is string => part !== null && part.length > 0).join(' / ');
}

function firstString(item: Record<string, unknown>, fields: string[]) {
  for (const field of fields) {
    const value = readString(item, field);
    if (value) return value;
  }
  return undefined;
}

function readString(value: unknown, key: string) {
  if (!isRecord(value)) return undefined;
  const field = value[key];
  return typeof field === 'string' && field.trim().length > 0 ? field : undefined;
}

function readNumber(value: unknown, key: string) {
  if (!isRecord(value)) return undefined;
  const field = value[key];
  return typeof field === 'number' && Number.isFinite(field) ? field : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function formatScalar(value: unknown) {
  if (typeof value === 'string' && value.trim().length > 0) return value;
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return undefined;
}

function jobKey(job: ActiveJobRef) {
  return readString(job, 'job_id') ?? readString(job, 'tool_call_id') ?? readString(job, 'status') ?? 'job';
}

function statusTone(status: string): Tone {
  const normalized = status.toLowerCase();
  if (['completed', 'complete', 'done', 'succeeded', 'success'].includes(normalized)) return 'good';
  if (['running', 'processing', 'active'].includes(normalized)) return 'blue';
  if (['pending', 'queued', 'deferred', 'waiting'].includes(normalized)) return 'amber';
  if (['failed', 'error', 'cancelled', 'canceled', 'rejected'].includes(normalized)) return 'risk';
  return 'muted';
}

function summaryTone(status: string): Tone {
  if (['available', 'active', 'verified'].includes(status)) return 'good';
  if (['failed', 'error'].includes(status)) return 'risk';
  if (['placeholder', 'unknown'].includes(status)) return 'muted';
  return 'amber';
}

function ToneChip({ label, tone, mono }: { label: ReactNode; tone: Tone; mono?: boolean }) {
  return (
    <Chip
      label={label}
      size="small"
      sx={{
        borderRadius: '6px',
        bgcolor: toneBg(tone),
        color: toneFg(tone),
        border: `1px solid ${toneBorder(tone)}`,
        fontWeight: 600,
        fontSize: '0.72rem',
        fontFamily: mono ? '"JetBrains Mono", monospace' : undefined,
        minWidth: 0,
        maxWidth: '100%',
        '& .MuiChip-label': { overflow: 'hidden', textOverflow: 'ellipsis' },
      }}
    />
  );
}

function shortId(value: string) {
  return value.length > 22 ? `${value.slice(0, 10)}...${value.slice(-8)}` : value;
}

function humanize(value: string) {
  return value.replace(/[_-]/g, ' ');
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

const scrollListSx = {
  maxHeight: 236,
  overflowY: 'auto',
  pr: 0.25,
};
