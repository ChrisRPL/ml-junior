import { Box, Chip, Stack, Typography } from '@mui/material';
import AccountTreeOutlinedIcon from '@mui/icons-material/AccountTreeOutlined';
import ChecklistOutlinedIcon from '@mui/icons-material/ChecklistOutlined';
import FactCheckOutlinedIcon from '@mui/icons-material/FactCheckOutlined';
import InputOutlinedIcon from '@mui/icons-material/InputOutlined';
import Inventory2OutlinedIcon from '@mui/icons-material/Inventory2Outlined';
import SpeedOutlinedIcon from '@mui/icons-material/SpeedOutlined';
import WarningAmberOutlinedIcon from '@mui/icons-material/WarningAmberOutlined';
import type { ReactNode } from 'react';
import type {
  FlowApprovalPointPreview,
  FlowArtifactPreview,
  FlowInputPreview,
  FlowPhasePreview,
  FlowPreviewResponse,
  FlowRequiredOutputPreview,
  FlowRiskyOperationPreview,
  FlowVerifierCheckPreview,
} from '@/lib/flow-preview-api';
import {
  labelSx,
  monoLineSx,
  statusLineSx,
  toneBg,
  toneBorder,
  toneFg,
  type Tone,
} from './projectDashboardTokens';

export default function FlowPreviewDetails({ preview }: { preview: FlowPreviewResponse }) {
  return (
    <Box sx={{ minWidth: 0 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 1.5, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="caption" sx={labelSx}>Preview</Typography>
          <Typography variant="h6" sx={{ fontWeight: 700, lineHeight: 1.16, overflowWrap: 'anywhere' }}>{preview.name}</Typography>
          {preview.description && (
            <Typography variant="body2" sx={{ color: 'var(--muted-text)', mt: 0.5, overflowWrap: 'anywhere' }}>
              {preview.description}
            </Typography>
          )}
          <Typography variant="caption" sx={{ ...monoLineSx, mt: 0.75 }}>{preview.template_source.path}</Typography>
        </Box>
        <Stack direction="row" spacing={0.75} sx={{ flexWrap: 'wrap', rowGap: 0.75 }}>
          <FlowChip label={preview.version} tone="muted" mono />
          <FlowChip label={preview.metadata.runtime_class} tone="blue" />
          <FlowChip label={preview.metadata.category} tone="amber" />
        </Stack>
      </Box>

      <PreviewSection title="Required inputs" icon={<InputOutlinedIcon />}>
        {preview.required_inputs.length > 0
          ? preview.required_inputs.map((input) => <InputRow key={input.id} input={input} />)
          : <Placeholder text="No required inputs." />}
      </PreviewSection>

      <PreviewSection title="Budget limits" icon={<SpeedOutlinedIcon />}>
        <BudgetRows preview={preview} />
      </PreviewSection>

      <PreviewSection title="Phases" icon={<AccountTreeOutlinedIcon />}>
        {preview.phases.map((phase) => <PhaseRow key={phase.id} phase={phase} />)}
      </PreviewSection>

      <PreviewSection title="Approval points" icon={<FactCheckOutlinedIcon />}>
        {preview.approval_points.length > 0
          ? preview.approval_points.map((approval) => <ApprovalPointRow key={approval.id} approval={approval} />)
          : <Placeholder text="No approval points." />}
      </PreviewSection>

      <PreviewSection title="Expected artifacts" icon={<Inventory2OutlinedIcon />}>
        <Stack spacing={0.75}>
          {preview.required_outputs.length > 0 && (
            <OutputGroup title="Required outputs" items={preview.required_outputs} />
          )}
          {preview.artifacts.length > 0 && (
            <ArtifactGroup title="Artifacts" items={preview.artifacts} />
          )}
          {preview.required_outputs.length === 0 && preview.artifacts.length === 0 && <Placeholder text="No expected artifacts." />}
        </Stack>
      </PreviewSection>

      <PreviewSection title="Risky operations" icon={<WarningAmberOutlinedIcon />}>
        {preview.risky_operations.length > 0
          ? preview.risky_operations.map((operation) => <RiskyOperationRow key={operation.id} operation={operation} />)
          : <Placeholder text="No risky operations." />}
      </PreviewSection>

      <PreviewSection title="Verifier checklist" icon={<ChecklistOutlinedIcon />}>
        {preview.verifier_checks.length > 0
          ? preview.verifier_checks.map((check) => <VerifierRow key={check.id} check={check} />)
          : <Placeholder text="No verifier checks." />}
      </PreviewSection>
    </Box>
  );
}

function PreviewSection({ title, icon, children }: { title: string; icon: ReactNode; children: ReactNode }) {
  return (
    <Box sx={{ mt: 1.5, pt: 1.5, borderTop: '1px solid var(--border)' }}>
      <SectionHeading icon={icon} title={title} />
      <Box sx={{ mt: 0.75 }}>{children}</Box>
    </Box>
  );
}

function SectionHeading({ icon, title }: { icon: ReactNode; title: string }) {
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, minWidth: 0 }}>
      <Box sx={{ color: 'text.secondary', display: 'flex', '& svg': { fontSize: 18 } }}>{icon}</Box>
      <Typography variant="subtitle2" sx={{ fontWeight: 700, overflowWrap: 'anywhere' }}>{title}</Typography>
    </Box>
  );
}

function InputRow({ input }: { input: FlowInputPreview }) {
  return (
    <InfoRow
      title={input.id}
      detail={input.description ?? formatDefault(input.default)}
      chips={[
        { label: input.type, tone: 'blue', mono: true },
        { label: input.required ? 'required' : 'optional', tone: input.required ? 'amber' : 'muted' },
      ]}
    />
  );
}

function BudgetRows({ preview }: { preview: FlowPreviewResponse }) {
  const rows = [
    ['GPU hours', formatLimit(preview.budgets.max_gpu_hours, 'h')],
    ['Runs', formatLimit(preview.budgets.max_runs, 'runs')],
    ['Wall clock', formatLimit(preview.budgets.max_wall_clock_hours, 'h')],
    ['LLM spend', preview.budgets.max_llm_usd === null ? 'not set' : `$${preview.budgets.max_llm_usd}`],
  ] as const;

  return (
    <Stack spacing={0.5}>
      {rows.map(([label, value]) => (
        <Box key={label} sx={statusLineSx}>
          <Typography variant="caption" sx={labelSx}>{label}</Typography>
          <FlowChip label={value} tone={value === 'not set' ? 'muted' : 'amber'} mono />
        </Box>
      ))}
    </Stack>
  );
}

function PhaseRow({ phase }: { phase: FlowPhasePreview }) {
  return (
    <Box sx={itemRowSx}>
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="body2" sx={{ fontWeight: 700, overflowWrap: 'anywhere' }}>{phase.order}. {phase.name}</Typography>
        <Typography variant="body2" sx={{ color: 'var(--muted-text)', mt: 0.25, overflowWrap: 'anywhere' }}>{phase.objective}</Typography>
        <Typography variant="caption" sx={monoLineSx}>{phase.id}</Typography>
      </Box>
      <Stack direction="row" spacing={0.75} sx={{ justifyContent: { xs: 'flex-start', sm: 'flex-end' }, flexWrap: 'wrap', rowGap: 0.75 }}>
        <FlowChip label={phase.status} tone="muted" mono />
        <FlowChip label={`${phase.required_outputs.length} outputs`} tone="blue" />
        <FlowChip label={`${phase.approval_points.length} approvals`} tone={phase.approval_points.length > 0 ? 'risk' : 'muted'} />
        <FlowChip label={`${phase.verifiers.length} checks`} tone="good" />
      </Stack>
    </Box>
  );
}

function ApprovalPointRow({ approval }: { approval: FlowApprovalPointPreview }) {
  return (
    <InfoRow
      title={`${approval.action}: ${approval.target}`}
      detail={approval.description ?? approval.id}
      monoDetail={approval.description ? approval.id : undefined}
      chips={[
        { label: approval.risk, tone: riskTone(approval.risk) },
        { label: phaseLabel(approval.phase_ids), tone: 'muted', mono: true },
      ]}
    />
  );
}

function OutputGroup({ title, items }: { title: string; items: FlowRequiredOutputPreview[] }) {
  return (
    <Box>
      <Typography variant="caption" sx={labelSx}>{title}</Typography>
      {items.map((item) => (
        <InfoRow
          key={item.id}
          title={item.id}
          detail={item.description ?? item.type}
          chips={[
            { label: item.type, tone: 'blue', mono: true },
            { label: item.required ? 'required' : 'optional', tone: item.required ? 'amber' : 'muted' },
            { label: phaseLabel(item.phase_ids), tone: 'muted', mono: true },
          ]}
        />
      ))}
    </Box>
  );
}

function ArtifactGroup({ title, items }: { title: string; items: FlowArtifactPreview[] }) {
  return (
    <Box>
      <Typography variant="caption" sx={labelSx}>{title}</Typography>
      {items.map((item) => (
        <InfoRow
          key={item.id}
          title={item.id}
          detail={item.description ?? item.type}
          chips={[
            { label: item.type, tone: 'blue', mono: true },
            { label: item.required ? 'required' : 'optional', tone: item.required ? 'amber' : 'muted' },
          ]}
        />
      ))}
    </Box>
  );
}

function RiskyOperationRow({ operation }: { operation: FlowRiskyOperationPreview }) {
  return (
    <InfoRow
      title={`${operation.action}: ${operation.target}`}
      detail={operation.description ?? operation.id}
      monoDetail={operation.description ? operation.id : undefined}
      chips={[
        { label: operation.risk, tone: riskTone(operation.risk) },
        { label: phaseLabel(operation.phase_ids), tone: 'muted', mono: true },
      ]}
    />
  );
}

function VerifierRow({ check }: { check: FlowVerifierCheckPreview }) {
  return (
    <InfoRow
      title={check.description}
      detail={check.id}
      monoDetail={check.type}
      chips={[
        { label: check.required ? 'required' : 'optional', tone: check.required ? 'good' : 'muted' },
        { label: phaseLabel(check.phase_ids), tone: 'muted', mono: true },
      ]}
    />
  );
}

function InfoRow({
  title,
  detail,
  monoDetail,
  chips,
}: {
  title: string;
  detail: string;
  monoDetail?: string;
  chips: { label: ReactNode; tone: Tone; mono?: boolean }[];
}) {
  return (
    <Box sx={itemRowSx}>
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="body2" sx={{ fontWeight: 650, overflowWrap: 'anywhere' }}>{title}</Typography>
        <Typography variant="body2" sx={{ color: 'var(--muted-text)', overflowWrap: 'anywhere' }}>{detail}</Typography>
        {monoDetail && <Typography variant="caption" sx={monoLineSx}>{monoDetail}</Typography>}
      </Box>
      <Stack direction="row" spacing={0.75} sx={{ justifyContent: { xs: 'flex-start', sm: 'flex-end' }, flexWrap: 'wrap', rowGap: 0.75 }}>
        {chips.map((chip, index) => <FlowChip key={index} {...chip} />)}
      </Stack>
    </Box>
  );
}

function FlowChip({ label, tone, mono }: { label: ReactNode; tone: Tone; mono?: boolean }) {
  return (
    <Chip
      label={label}
      size="small"
      sx={{
        borderRadius: '6px',
        bgcolor: toneBg(tone),
        color: toneFg(tone),
        border: `1px solid ${toneBorder(tone)}`,
        fontWeight: 650,
        fontSize: '0.7rem',
        fontFamily: mono ? '"JetBrains Mono", monospace' : undefined,
        maxWidth: '100%',
        '& .MuiChip-label': { overflow: 'hidden', textOverflow: 'ellipsis' },
      }}
    />
  );
}

function Placeholder({ text }: { text: string }) {
  return <Typography variant="body2" sx={{ color: 'var(--muted-text)' }}>{text}</Typography>;
}

function riskTone(risk: string): Tone {
  if (['high', 'critical'].includes(risk.toLowerCase())) return 'risk';
  if (['medium', 'moderate'].includes(risk.toLowerCase())) return 'amber';
  if (risk.toLowerCase() === 'low') return 'good';
  return 'muted';
}

function phaseLabel(phaseIds: string[]) {
  if (phaseIds.length === 0) return 'no phase';
  if (phaseIds.length === 1) return phaseIds[0];
  return `${phaseIds.length} phases`;
}

function formatLimit(value: number | null, suffix: string) {
  return value === null ? 'not set' : `${value} ${suffix}`;
}

function formatDefault(value: unknown) {
  if (value === null) return 'No default value.';
  if (typeof value === 'string') return `Default: ${value}`;
  if (typeof value === 'number' || typeof value === 'boolean') return `Default: ${String(value)}`;
  return 'Default object provided.';
}

const itemRowSx = {
  display: 'grid',
  gridTemplateColumns: { xs: '1fr', sm: 'minmax(0, 1fr) minmax(180px, auto)' },
  gap: 1,
  alignItems: 'start',
  py: 0.9,
  borderBottom: '1px solid var(--border)',
  '&:last-of-type': { borderBottom: 0 },
};
