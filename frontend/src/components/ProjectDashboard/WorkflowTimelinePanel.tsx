import AccountTreeOutlinedIcon from '@mui/icons-material/AccountTreeOutlined';
import { Box, Chip, Stack, Typography } from '@mui/material';
import type { ReactNode } from 'react';
import type { ProjectBlocker, ProjectPhaseSnapshot, ProjectSnapshot } from '@/types/project';
import {
  monoLineSx,
  panelSx,
  phaseTone,
  toneBg,
  toneBorder,
  toneFg,
  type Tone,
} from './projectDashboardTokens';

interface WorkflowTimelinePanelProps {
  snapshot: ProjectSnapshot;
}

interface RowChip {
  label: ReactNode;
  tone: Tone;
  mono?: boolean;
}

interface TimelineEntry {
  key: string;
  title: string;
  detail: string;
  tone: Tone;
  chips: RowChip[];
}

interface PhaseGateBlockerFields {
  type?: unknown;
  phase_id?: unknown;
  gate_status?: unknown;
  requested_status?: unknown;
  to_status?: unknown;
  missing_outputs?: unknown;
  pending_verifiers?: unknown;
  failed_verifiers?: unknown;
  source_event_sequence?: number | null;
  updated_at?: string | null;
}

type PhaseGateBlocker = ProjectBlocker & PhaseGateBlockerFields;

export default function WorkflowTimelinePanel({ snapshot }: WorkflowTimelinePanelProps) {
  const phaseEntry = isWorkflowPhase(snapshot.phase)
    ? phaseToTimelineEntry(snapshot.phase)
    : null;
  const gateEntries = snapshot.blockers
    .filter(isPhaseGateBlocker)
    .map(gateBlockerToTimelineEntry);
  const entries = phaseEntry ? [phaseEntry, ...gateEntries] : gateEntries;

  return (
    <Box sx={panelSx}>
      <Box sx={timelineHeaderSx}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
          <Box sx={{ color: 'text.secondary', display: 'flex', '& svg': { fontSize: 18 } }}>
            <AccountTreeOutlinedIcon />
          </Box>
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>Workflow timeline</Typography>
            <Typography variant="caption" sx={monoLineSx}>
              snapshot seq {snapshot.last_event_sequence}
            </Typography>
          </Box>
        </Box>
        <Stack direction="row" spacing={0.75} sx={{ flexWrap: 'wrap', rowGap: 0.75, justifyContent: { xs: 'flex-start', sm: 'flex-end' } }}>
          <ToneChip
            label={entries.length > 0 ? humanize(snapshot.phase.status) : 'no phase events'}
            tone={entries.length > 0 ? phaseTone(snapshot.phase.status) : 'muted'}
          />
          {gateEntries.length > 0 && <ToneChip label={`${gateEntries.length} gate waits`} tone="amber" mono />}
        </Stack>
      </Box>

      {entries.length > 0 ? (
        <Box sx={{ mt: 0.5 }}>
          {entries.map((entry) => <TimelineRow key={entry.key} entry={entry} />)}
        </Box>
      ) : (
        <EmptyTimeline phase={snapshot.phase} />
      )}
    </Box>
  );
}

function TimelineRow({ entry }: { entry: TimelineEntry }) {
  return (
    <Box sx={timelineRowSx}>
      <Box sx={{ display: 'flex', justifyContent: 'center', pt: 0.35 }}>
        <Box sx={{ width: 9, height: 9, borderRadius: '50%', bgcolor: toneFg(entry.tone), boxShadow: `0 0 0 3px ${toneBg(entry.tone)}` }} />
      </Box>
      <Box sx={timelineContentSx}>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="body2" sx={{ fontWeight: 700, overflowWrap: 'anywhere' }}>{entry.title}</Typography>
          {entry.detail && <Typography variant="caption" sx={monoLineSx}>{entry.detail}</Typography>}
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
          {entry.chips.map((chip, index) => (
            <ToneChip key={index} label={chip.label} tone={chip.tone} mono={chip.mono} />
          ))}
        </Stack>
      </Box>
    </Box>
  );
}

function EmptyTimeline({ phase }: { phase: ProjectPhaseSnapshot }) {
  return (
    <Box sx={emptyTimelineSx}>
      <Typography variant="subtitle2" sx={{ color: 'var(--text)', fontWeight: 700 }}>
        No phase events recorded.
      </Typography>
      <Typography variant="body2" sx={{ color: 'var(--muted-text)', overflowWrap: 'anywhere' }}>
        Current phase is compatibility-derived: {phase.label} / {humanize(phase.status)}.
      </Typography>
      <Typography variant="caption" sx={monoLineSx}>{phase.id}</Typography>
    </Box>
  );
}

function phaseToTimelineEntry(phase: ProjectPhaseSnapshot): TimelineEntry {
  const timestampDetail = compactParts([
    phase.started_at ? `started ${formatDate(phase.started_at)}` : null,
    phase.updated_at ? `updated ${formatDate(phase.updated_at)}` : null,
  ]);

  return {
    key: `phase:${phase.id}:${phase.status}:${phase.updated_at ?? phase.started_at ?? 'none'}`,
    title: phase.label,
    detail: compactParts([phase.id, timestampDetail]),
    tone: phaseTone(phase.status),
    chips: [
      { label: humanize(phase.status), tone: phaseTone(phase.status) },
      { label: 'projected phase', tone: 'muted' },
    ],
  };
}

function gateBlockerToTimelineEntry(blocker: PhaseGateBlocker, index: number): TimelineEntry {
  const gateStatus = readString(blocker, 'gate_status') ?? 'blocked';
  const requestedStatus = readString(blocker, 'requested_status');
  const toStatus = readString(blocker, 'to_status');
  const phaseId = readString(blocker, 'phase_id');
  const missingOutputs = readStringArray(blocker.missing_outputs);
  const pendingVerifiers = readStringArray(blocker.pending_verifiers);
  const failedVerifiers = readStringArray(blocker.failed_verifiers);
  const sequence = typeof blocker.source_event_sequence === 'number' ? blocker.source_event_sequence : null;

  return {
    key: `phase-gate:${phaseId ?? index}:${sequence ?? index}`,
    title: `Gate ${humanize(gateStatus)}`,
    detail: compactParts([
      phaseId ? `phase ${phaseId}` : null,
      requestedStatus ? `requested ${humanize(requestedStatus)}` : null,
      toStatus ? `to ${humanize(toStatus)}` : null,
      sequence ? `seq ${sequence}` : null,
      blocker.updated_at ? `updated ${formatDate(blocker.updated_at)}` : null,
    ]),
    tone: gateTone(gateStatus),
    chips: [
      { label: humanize(gateStatus), tone: gateTone(gateStatus) },
      ...(missingOutputs.length > 0 ? [{ label: `${missingOutputs.length} missing outputs`, tone: 'amber' as const }] : []),
      ...(pendingVerifiers.length > 0 ? [{ label: `${pendingVerifiers.length} pending checks`, tone: 'amber' as const }] : []),
      ...(failedVerifiers.length > 0 ? [{ label: `${failedVerifiers.length} failed checks`, tone: 'risk' as const }] : []),
    ],
  };
}

function isWorkflowPhase(phase: ProjectPhaseSnapshot) {
  return !COMPATIBILITY_PHASE_IDS.has(phase.id);
}

function isPhaseGateBlocker(blocker: ProjectBlocker): blocker is PhaseGateBlocker {
  return readString(blocker, 'type') === 'phase_gate';
}

function readString(value: unknown, key: string) {
  if (!isRecord(value)) return undefined;
  const field = value[key];
  return typeof field === 'string' && field.trim().length > 0 ? field : undefined;
}

function readStringArray(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function gateTone(status: string): Tone {
  const normalized = status.toLowerCase();
  if (['satisfied', 'complete', 'completed', 'verified'].includes(normalized)) return 'good';
  if (['failed', 'error'].includes(normalized)) return 'risk';
  if (['blocked', 'verifier_pending', 'missing_outputs', 'pending'].includes(normalized)) return 'amber';
  return 'muted';
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

function compactParts(parts: Array<string | null | undefined>) {
  return parts.filter((part): part is string => Boolean(part)).join(' / ');
}

function humanize(value: string) {
  return value.replace(/[_-]/g, ' ');
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

const timelineHeaderSx = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: { xs: 'flex-start', sm: 'center' },
  gap: 1.25,
  flexDirection: { xs: 'column', sm: 'row' },
  mb: 1.1,
};

const timelineRowSx = {
  display: 'grid',
  gridTemplateColumns: '18px minmax(0, 1fr)',
  gap: 1,
  position: 'relative',
  minWidth: 0,
  py: 0.8,
  borderBottom: '1px solid var(--border)',
  '&:not(:last-of-type)::before': {
    content: '""',
    position: 'absolute',
    left: '8px',
    top: 24,
    bottom: 0,
    width: '1px',
    bgcolor: 'var(--border)',
  },
  '&:last-of-type': {
    borderBottom: 0,
    pb: 0.2,
  },
};

const timelineContentSx = {
  display: 'grid',
  gridTemplateColumns: { xs: '1fr', sm: 'minmax(0, 1fr) minmax(0, auto)' },
  gap: 1,
  alignItems: 'start',
  minWidth: 0,
};

const emptyTimelineSx = {
  minHeight: 118,
  border: '1px dashed var(--border)',
  borderRadius: '8px',
  display: 'flex',
  flexDirection: 'column',
  justifyContent: 'center',
  gap: 0.45,
  p: { xs: 1.25, sm: 1.5 },
  bgcolor: 'var(--surface)',
};

const COMPATIBILITY_PHASE_IDS = new Set([
  'compatibility-session',
  'delivery',
  'execution',
  'human-approval',
  'planning',
]);
