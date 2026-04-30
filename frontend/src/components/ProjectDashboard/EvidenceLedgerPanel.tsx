import { Box, Chip, Divider, Stack, Typography } from '@mui/material';
import type { ReactNode } from 'react';
import type { ProjectEvidenceSummary, ProjectVerifierCatalogSummary } from '@/types/project';
import {
  labelSx,
  monoLineSx,
  rowSx,
  terminalAssets,
  toneBg,
  toneBorder,
  toneFg,
  type Tone,
} from './projectDashboardTokens';

interface EvidenceLedgerPanelProps {
  summary: ProjectEvidenceSummary;
}

export default function EvidenceLedgerPanel({ summary }: EvidenceLedgerPanelProps) {
  const claimLinkCount = readNumber(summary, 'claim_link_count');
  const evidenceCount = readNumber(summary, 'evidence_count');
  const logCount = readNumber(summary, 'log_count');
  const verifierCount = readNumber(summary, 'verifier_count');
  const verifierStatus = readString(summary, 'verifier_status');
  const verifierCounts = readRecord(summary, 'verifier_counts');
  const verifierTone = verifierStatus ? verifierStatusTone(verifierStatus) : summaryStatusTone(summary.status);

  return (
    <Stack spacing={1.25}>
      <Box sx={{ display: 'flex', gap: 1.25, alignItems: 'center' }}>
        <Box component="img" src={terminalAssets.evidence} alt="" sx={{ width: 58, display: { xs: 'none', sm: 'block' }, opacity: 0.82 }} />
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Stack direction="row" spacing={0.75} sx={{ flexWrap: 'wrap', rowGap: 0.75, mb: 0.75 }}>
            <ToneChip label={`${summary.artifact_count} artifacts`} tone="blue" />
            <ToneChip label={`${summary.metric_count} metrics`} tone="good" />
            <ToneChip label={`${summary.claim_count} claims`} tone={summaryStatusTone(summary.status)} />
            {claimLinkCount !== undefined && <ToneChip label={`${claimLinkCount} links`} tone="amber" />}
          </Stack>
          <Typography variant="body2" sx={{ color: 'var(--muted-text)' }}>
            Evidence: {humanize(summary.status)}{summary.updated_at ? ` / ${formatDate(summary.updated_at)}` : ''}.
          </Typography>
        </Box>
      </Box>

      {(evidenceCount !== undefined || logCount !== undefined || verifierCount !== undefined) && (
        <Stack direction="row" spacing={0.75} sx={{ flexWrap: 'wrap', rowGap: 0.75 }}>
          {evidenceCount !== undefined && <ToneChip label={`${evidenceCount} evidence`} tone="muted" />}
          {logCount !== undefined && <ToneChip label={`${logCount} logs`} tone="muted" />}
          {verifierCount !== undefined && <ToneChip label={`${verifierCount} verifiers`} tone={verifierTone} />}
          {verifierStatus && <ToneChip label={humanize(verifierStatus)} tone={verifierTone} />}
          {verifierCounts && Object.entries(verifierCounts).map(([key, value]) => (
            typeof value === 'number'
              ? <ToneChip key={key} label={`${key}: ${value}`} tone={verifierStatusTone(key)} mono />
              : null
          ))}
        </Stack>
      )}

      {summary.verifier_catalog && (
        <VerifierCatalog catalog={summary.verifier_catalog} />
      )}

      <Divider />

      {summary.items.length > 0 ? (
        <Stack spacing={0}>
          {summary.items.map((item, index) => (
            <EvidenceRow key={`${evidenceItemKey(item)}:${index}`} item={item} />
          ))}
        </Stack>
      ) : (
        <Typography variant="body2" sx={{ color: 'var(--muted-text)', py: 0.25 }}>
          No evidence yet.
        </Typography>
      )}
    </Stack>
  );
}

function VerifierCatalog({ catalog }: { catalog: ProjectVerifierCatalogSummary }) {
  const counts = catalog.counts;
  const mappingPreview = catalog.mapping_rows.slice(0, 3);

  return (
    <Box sx={{ border: '1px solid var(--border)', borderRadius: '8px', p: 1, bgcolor: '#FBFAF6' }}>
      <Typography variant="caption" sx={labelSx}>Verifier catalog</Typography>
      <Stack direction="row" spacing={0.75} sx={{ flexWrap: 'wrap', rowGap: 0.75, mt: 0.75 }}>
        <ToneChip label={`${counts.catalog_check_id_count} catalog`} tone="blue" mono />
        <ToneChip label={`${counts.mapped_catalog_check_id_count} mapped`} tone="good" mono />
        <ToneChip label={`${counts.flow_local_verifier_id_count} local`} tone="amber" mono />
        <ToneChip label={`${counts.unknown_id_count} unknown`} tone={counts.unknown_id_count > 0 ? 'risk' : 'muted'} mono />
      </Stack>
      {catalog.catalog_check_ids.length > 0 && (
        <Typography variant="caption" sx={{ ...monoLineSx, mt: 0.75 }}>
          {catalog.catalog_check_ids.slice(0, 4).join(', ')}
          {catalog.catalog_check_ids.length > 4 ? ` +${catalog.catalog_check_ids.length - 4}` : ''}
        </Typography>
      )}
      {mappingPreview.length > 0 && (
        <Stack spacing={0.25} sx={{ mt: 0.5 }}>
          {mappingPreview.map((row) => (
            <Typography key={`${row.flow_verifier_id}:${row.catalog_check_id}`} variant="caption" sx={monoLineSx}>
              {shortId(row.flow_verifier_id)} {'->'} {shortId(row.catalog_check_id)}
            </Typography>
          ))}
        </Stack>
      )}
    </Box>
  );
}

function EvidenceRow({ item }: { item: unknown }) {
  const model = formatEvidenceItem(item);
  return (
    <Box sx={rowSx}>
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="body2" sx={{ fontWeight: 600, overflowWrap: 'anywhere' }}>{model.title}</Typography>
        {model.detail && <Typography variant="caption" sx={monoLineSx}>{model.detail}</Typography>}
      </Box>
      <ToneChip label={model.kind} tone={model.tone} mono />
    </Box>
  );
}

function formatEvidenceItem(item: unknown): { kind: string; title: string; detail: string; tone: Tone } {
  if (!isRecord(item)) {
    return {
      kind: 'item',
      title: formatScalar(item) ?? 'Unsupported evidence item',
      detail: 'primitive summary item',
      tone: 'muted',
    };
  }

  if (readString(item, 'artifact_id')) {
    return {
      kind: 'artifact',
      title: firstString(item, ['label', 'type', 'artifact_id']) ?? 'Artifact',
      detail: compactDetails(item, ['artifact_id', 'source', 'source_job_id', 'privacy_class', 'created_at']),
      tone: 'blue',
    };
  }

  if (readString(item, 'metric_id') && !readString(item, 'evidence_id')) {
    const name = readString(item, 'name') ?? 'Metric';
    const value = formatScalar(item.value);
    const unit = readString(item, 'unit');
    return {
      kind: 'metric',
      title: value ? `${name}: ${value}${unit ? ` ${unit}` : ''}` : name,
      detail: compactDetails(item, ['metric_id', 'source', 'step', 'recorded_at']),
      tone: 'good',
    };
  }

  if (readString(item, 'log_id')) {
    return {
      kind: 'log',
      title: firstString(item, ['label', 'source', 'log_id']) ?? 'Log',
      detail: compactDetails(item, ['log_id', 'source', 'uri']),
      tone: 'muted',
    };
  }

  if (readString(item, 'link_id')) {
    const relation = readString(item, 'relation') ?? 'links';
    const strength = readString(item, 'strength');
    return {
      kind: 'claim link',
      title: `${humanize(relation)}${strength ? ` / ${humanize(strength)}` : ''}`,
      detail: compactDetails(item, ['link_id', 'claim_id', 'evidence_id', 'created_at']),
      tone: 'amber',
    };
  }

  if (readString(item, 'verdict_id')) {
    const verdict = readString(item, 'verdict') ?? 'verifier';
    return {
      kind: 'verifier',
      title: readString(item, 'summary') ?? humanize(verdict),
      detail: compactDetails(item, ['verdict_id', 'verifier_id', 'scope', 'created_at']),
      tone: verifierStatusTone(verdict),
    };
  }

  if (readString(item, 'evidence_id')) {
    return {
      kind: firstString(item, ['kind', 'source']) ?? 'evidence',
      title: firstString(item, ['title', 'summary', 'evidence_id']) ?? 'Evidence',
      detail: compactDetails(item, ['evidence_id', 'source', 'metric_id', 'privacy_class', 'created_at']),
      tone: 'amber',
    };
  }

  return {
    kind: firstString(item, ['kind', 'type', 'source']) ?? 'item',
    title: firstString(item, ['title', 'label', 'name', 'summary', 'id']) ?? 'Unsupported evidence shape',
    detail: compactDetails(item, ['id', 'source', 'status', 'created_at', 'updated_at']),
    tone: 'muted',
  };
}

function compactDetails(item: Record<string, unknown>, fields: string[]) {
  return fields
    .map((field) => {
      const value = formatScalar(item[field]);
      if (!value) return null;
      const display = field.endsWith('_id') || field === 'id' ? shortId(value) : value;
      return `${humanize(field)} ${display}`;
    })
    .filter(Boolean)
    .join(' / ');
}

function evidenceItemKey(item: unknown) {
  if (!isRecord(item)) return String(item);
  return firstString(item, ['verdict_id', 'link_id', 'evidence_id', 'artifact_id', 'metric_id', 'log_id', 'id']) ?? 'item';
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
  return isRecord(value) && typeof value[key] === 'number' && Number.isFinite(value[key]) ? value[key] : undefined;
}

function readRecord(value: unknown, key: string): Record<string, unknown> | undefined {
  return isRecord(value) && isRecord(value[key]) ? value[key] : undefined;
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

function summaryStatusTone(status: string): Tone {
  if (['verified', 'passed', 'available', 'active'].includes(status)) return 'good';
  if (['failed', 'error'].includes(status)) return 'risk';
  if (['inconclusive', 'unknown'].includes(status)) return 'amber';
  return 'muted';
}

function verifierStatusTone(status: string): Tone {
  if (status === 'passed' || status === 'verified') return 'good';
  if (status === 'failed') return 'risk';
  if (status === 'inconclusive' || status === 'unknown') return 'amber';
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

function shortId(value: string) {
  return value.length > 22 ? `${value.slice(0, 10)}...${value.slice(-8)}` : value;
}

function humanize(value: string) {
  return value.replace(/[_-]/g, ' ');
}

function formatDate(value: string) {
  return new Date(value).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}
