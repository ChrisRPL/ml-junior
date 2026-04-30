import {
  Box,
  Chip,
  Stack,
  Typography,
} from '@mui/material';
import type { ReactNode } from 'react';
import type { ProjectBudgetSnapshot } from '@/types/project';
import {
  labelSx,
  monoLineSx,
  toneBg,
  toneBorder,
  toneFg,
  type Tone,
} from './projectDashboardTokens';

interface BudgetTrackingPanelProps {
  budget: ProjectBudgetSnapshot;
}

const TOTAL_FIELDS = ['limit', 'used', 'remaining', 'limit_count', 'usage_count', 'status'] as const;
const ITEM_FIELDS = [
  'amount',
  'quantity',
  'count',
  'limit',
  'used',
  'remaining',
  'limit_count',
  'usage_count',
  'unit',
  'currency',
  'status',
  'source',
  'tool_call_id',
  'job_id',
  'created_at',
  'updated_at',
] as const;

export default function BudgetTrackingPanel({ budget }: BudgetTrackingPanelProps) {
  const totals = recordRows(budget.totals);
  const items = recordRows(budget.items);
  const remaining = typeof budget.limit === 'number' && typeof budget.used === 'number'
    ? budget.limit - budget.used
    : null;
  const summaryRows = [
    { label: 'Limit', value: formatAmount(budget.limit, budget.currency) },
    { label: 'Used', value: formatAmount(budget.used, budget.currency) },
    { label: 'Remaining', value: formatAmount(remaining, budget.currency) },
    { label: 'Limit rows', value: formatScalar(budget.limit_count) },
    { label: 'Usage rows', value: formatScalar(budget.usage_count) },
  ].filter((row) => row.value !== 'none');

  return (
    <Stack spacing={1.25}>
      <Box
        sx={{
          display: 'flex',
          alignItems: { xs: 'flex-start', sm: 'center' },
          justifyContent: 'space-between',
          flexDirection: { xs: 'column', sm: 'row' },
          gap: 1,
          minWidth: 0,
        }}
      >
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="body2" sx={{ fontWeight: 700 }}>
            {budget.status === 'placeholder' ? 'Budget not tracked' : 'Budget detail'}
          </Typography>
          <Typography variant="caption" sx={monoLineSx}>
            {formatSource(budget.source)}
            {budget.updated_at ? ` / ${formatDate(budget.updated_at)}` : ''}
          </Typography>
        </Box>
        <ToneChip label={humanize(budget.status)} tone={budgetTone(budget.status)} />
      </Box>

      {summaryRows.length > 0 ? (
        <Box sx={compactGridSx}>
          {summaryRows.map((row) => (
            <MetricTile key={row.label} label={row.label} value={row.value} />
          ))}
        </Box>
      ) : (
        <Placeholder text="No budget limits or usage reported." />
      )}

      <BudgetSection title="Totals" empty="No budget totals reported.">
        {totals.map((row, index) => (
          <BudgetTotalRow key={rowKey(row, index)} row={row} index={index} currency={budget.currency} />
        ))}
      </BudgetSection>

      <BudgetSection title="Ledger items" empty="No budget ledger items reported.">
        {items.map((row, index) => (
          <BudgetItemRow key={rowKey(row, index)} row={row} index={index} currency={budget.currency} />
        ))}
      </BudgetSection>
    </Stack>
  );
}

function BudgetSection({ title, empty, children }: { title: string; empty: string; children: ReactNode[] }) {
  return (
    <Box>
      <Typography variant="caption" sx={labelSx}>{title}</Typography>
      {children.length > 0 ? (
        <Stack spacing={0.75} sx={{ mt: 0.5 }}>{children}</Stack>
      ) : (
        <Placeholder text={empty} />
      )}
    </Box>
  );
}

function BudgetTotalRow({ row, index, currency }: { row: Record<string, unknown>; index: number; currency: string | null }) {
  const resource = readString(row.resource) ?? `total ${index + 1}`;
  const unit = readString(row.unit);
  const fields = fieldEntries(row, TOTAL_FIELDS, ['resource', 'unit'], currency);

  return (
    <Box sx={budgetRowSx}>
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="body2" sx={{ fontWeight: 700, overflowWrap: 'anywhere' }}>{resource}</Typography>
        {unit && <Typography variant="caption" sx={monoLineSx}>{unit}</Typography>}
      </Box>
      <FieldGrid fields={fields} />
    </Box>
  );
}

function BudgetItemRow({ row, index, currency }: { row: Record<string, unknown>; index: number; currency: string | null }) {
  const type = readString(row.type) ?? 'item';
  const resource = readString(row.resource) ?? readString(row.description) ?? `${type} ${index + 1}`;
  const fields = fieldEntries(row, ITEM_FIELDS, ['type', 'resource', 'description'], currency);

  return (
    <Box sx={budgetRowSx}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, minWidth: 0, flexWrap: 'wrap' }}>
        <ToneChip label={humanize(type)} tone={type === 'usage' ? 'blue' : type === 'limit' ? 'amber' : 'muted'} />
        <Typography variant="body2" sx={{ fontWeight: 700, overflowWrap: 'anywhere', minWidth: 0 }}>{resource}</Typography>
      </Box>
      <FieldGrid fields={fields} />
    </Box>
  );
}

function MetricTile({ label, value }: { label: string; value: string }) {
  return (
    <Box
      sx={{
        border: '1px solid var(--border)',
        borderRadius: '6px',
        p: 0.9,
        minWidth: 0,
        bgcolor: '#FCFBF8',
      }}
    >
      <Typography variant="caption" sx={labelSx}>{label}</Typography>
      <Typography variant="body2" sx={{ fontWeight: 700, overflowWrap: 'anywhere' }}>{value}</Typography>
    </Box>
  );
}

function FieldGrid({ fields }: { fields: FieldEntry[] }) {
  if (fields.length === 0) {
    return <Placeholder text="No row details." compact />;
  }

  return (
    <Box sx={compactGridSx}>
      {fields.map((field) => (
        <Box key={field.key} sx={{ minWidth: 0 }}>
          <Typography variant="caption" sx={labelSx}>{humanize(field.key)}</Typography>
          <Typography variant="caption" sx={field.mono ? monoLineSx : { display: 'block', overflowWrap: 'anywhere' }}>
            {field.value}
          </Typography>
        </Box>
      ))}
    </Box>
  );
}

function Placeholder({ text, compact = false }: { text: string; compact?: boolean }) {
  return (
    <Typography variant="body2" sx={{ color: 'var(--muted-text)', py: compact ? 0.25 : 0.75 }}>
      {text}
    </Typography>
  );
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

type FieldEntry = {
  key: string;
  value: string;
  mono?: boolean;
};

function fieldEntries(
  row: Record<string, unknown>,
  preferred: readonly string[],
  hidden: string[],
  currency: string | null,
): FieldEntry[] {
  const hiddenKeys = new Set(hidden);
  const keys = [
    ...preferred,
    ...Object.keys(row).filter((key) => !preferred.includes(key)),
  ];
  const seen = new Set<string>();

  return keys.flatMap((key) => {
    if (seen.has(key) || hiddenKeys.has(key)) return [];
    seen.add(key);
    const value = row[key];
    if (!isScalar(value)) return [];
    return [{
      key,
      value: formatFieldValue(key, value, currency),
      mono: key.endsWith('_id') || key.endsWith('_at'),
    }];
  });
}

function formatFieldValue(key: string, value: string | number | boolean | null, currency: string | null): string {
  if (['limit', 'used', 'remaining', 'amount', 'cost'].includes(key)) {
    return typeof value === 'number' ? formatAmount(value, currency) : formatScalar(value);
  }
  return formatScalar(value);
}

function recordRows(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

function rowKey(row: Record<string, unknown>, index: number): string {
  return readString(row.id) ?? readString(row.ledger_id) ?? readString(row.event_id) ?? `${index}`;
}

function formatAmount(value: number | null | undefined, currency: string | null): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'none';
  return currency ? `${formatNumber(value)} ${currency}` : formatNumber(value);
}

function formatScalar(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'none';
  if (typeof value === 'number') return Number.isFinite(value) ? formatNumber(value) : 'none';
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  if (typeof value === 'string') return value;
  return 'none';
}

function formatNumber(value: number): string {
  return Number.isInteger(value)
    ? value.toLocaleString()
    : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function formatDate(value: string) {
  return new Date(value).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function formatSource(source: string) {
  return source === 'placeholder' ? 'not tracked' : humanize(source);
}

function humanize(value: string) {
  return value.replace(/[_-]/g, ' ');
}

function budgetTone(status: string): Tone {
  if (status === 'exhausted') return 'risk';
  if (status === 'active') return 'blue';
  return 'muted';
}

function readString(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 ? value : undefined;
}

function isScalar(value: unknown): value is string | number | boolean | null {
  return value === null || ['string', 'number', 'boolean'].includes(typeof value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

const compactGridSx = {
  display: 'grid',
  gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', sm: 'repeat(auto-fit, minmax(118px, 1fr))' },
  gap: 0.75,
  minWidth: 0,
};

const budgetRowSx = {
  border: '1px solid var(--border)',
  borderRadius: '6px',
  p: 1,
  minWidth: 0,
  display: 'grid',
  gap: 0.85,
};
