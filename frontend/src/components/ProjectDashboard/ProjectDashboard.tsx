import {
  Alert,
  Box,
  Chip,
  Link,
  Stack,
  Typography,
} from '@mui/material';
import type { ReactNode } from 'react';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import FactCheckOutlinedIcon from '@mui/icons-material/FactCheckOutlined';
import HourglassBottomOutlinedIcon from '@mui/icons-material/HourglassBottomOutlined';
import MemoryOutlinedIcon from '@mui/icons-material/MemoryOutlined';
import PendingActionsOutlinedIcon from '@mui/icons-material/PendingActionsOutlined';
import PlayArrowOutlinedIcon from '@mui/icons-material/PlayArrowOutlined';
import ReportProblemOutlinedIcon from '@mui/icons-material/ReportProblemOutlined';
import TaskAltOutlinedIcon from '@mui/icons-material/TaskAltOutlined';
import type {
  ActiveJobRef,
  HumanRequestRef,
  OperationRef,
  PendingApprovalRef,
  ProjectBlocker,
  ProjectPlanItem,
  ProjectSnapshot,
} from '@/types/project';
import type { SessionMeta } from '@/types/agent';
import EvidenceLedgerPanel from './EvidenceLedgerPanel';
import FlowCatalogPanel from './FlowCatalogPanel';
import {
  alertSx,
  dashboardGridSx,
  emptySx,
  eyebrowSx,
  headerSx,
  labelSx,
  metricSx,
  monoLineSx,
  overviewGridSx,
  panelSx,
  phaseTone,
  rowSx,
  statusLineSx,
  statusTone,
  terminalAssets,
  titleSx,
  toneBg,
  toneBorder,
  toneFg,
  type Tone,
} from './projectDashboardTokens';

interface ProjectDashboardProps {
  snapshot: ProjectSnapshot | null;
  activeSession: SessionMeta | null;
}

export default function ProjectDashboard({ snapshot, activeSession }: ProjectDashboardProps) {
  if (!activeSession) {
    return (
      <DashboardFrame>
        <EmptyProject title="No session selected" detail="Select a session to inspect project state." />
      </DashboardFrame>
    );
  }

  if (!snapshot) {
    return (
      <DashboardFrame>
        <Header
          status="idle"
          title={activeSession.title}
          subtitle={`Session ${shortId(activeSession.id)}`}
          updatedAt={activeSession.createdAt}
        />
        <EmptyProject
          title="Session-only project"
          detail="Project rows will appear when session events are available."
        />
        <Box sx={{ mt: 1.5 }}>
          <FlowCatalogPanel />
        </Box>
      </DashboardFrame>
    );
  }

  const warnings = snapshot.compatibility.warnings ?? [];
  const stale = snapshot.compatibility.stale || snapshot.resume.stale_snapshot || snapshot.status === 'stale';

  return (
    <DashboardFrame>
      <Header
        status={snapshot.status}
        title={snapshot.objective.text ?? activeSession.title}
        subtitle={`Project ${shortId(snapshot.project_id)} / session ${shortId(snapshot.session_id)}`}
        updatedAt={snapshot.updated_at ?? activeSession.createdAt}
      />

      {(stale || warnings.length > 0) && (
        <Alert
          severity={stale ? 'warning' : 'info'}
          icon={<ReportProblemOutlinedIcon fontSize="small" />}
          sx={alertSx}
        >
          <Typography variant="body2" sx={{ fontWeight: 700, mb: 0.25 }}>
            {stale ? 'Project state is stale' : 'Project notes'}
          </Typography>
          <Typography variant="caption" sx={{ color: 'var(--muted-text)' }}>
            {[...new Set(warnings.concat(stale ? ['stale_snapshot'] : []))].join(', ')}
          </Typography>
        </Alert>
      )}

      <Box sx={overviewGridSx}>
        <Metric title="Current phase" value={snapshot.phase.label} detail={humanize(snapshot.phase.status)} tone={phaseTone(snapshot.phase.status)} />
        <Metric title="Approvals" value={snapshot.pending_approvals.length} detail={snapshot.status === 'waiting_approval' ? 'blocked' : 'pending'} tone={snapshot.pending_approvals.length > 0 ? 'amber' : 'muted'} />
        <Metric title="Active jobs/tools" value={snapshot.active_jobs.length + runningOperations(snapshot.operation_refs).length} detail="running" tone={snapshot.active_jobs.length > 0 ? 'blue' : 'muted'} />
        <Metric title="Resume" value={snapshot.resume.can_resume ? 'ready' : 'not yet'} detail={`seq ${snapshot.resume.event_sequence}`} tone={snapshot.resume.can_resume ? 'good' : 'muted'} mono />
      </Box>

      <Box sx={{ mb: 2 }}>
        <FlowCatalogPanel />
      </Box>

      <Box sx={dashboardGridSx}>
        <Stack spacing={1.5}>
          <Panel title="Plan" icon={<PendingActionsOutlinedIcon />}>
            {snapshot.plan.length > 0 ? (
              <Stack spacing={0}>
                {snapshot.plan.map((item) => <PlanRow key={item.id} item={item} />)}
              </Stack>
            ) : (
              <Placeholder text="Waiting for plan events." />
            )}
          </Panel>

          <Panel title="Blockers and waits" icon={<ErrorOutlineIcon />}>
            <Stack spacing={0}>
              {snapshot.blockers.length > 0
                ? snapshot.blockers.map((blocker) => <BlockerRow key={blocker.id} blocker={blocker} />)
                : <Placeholder text="No active blockers." />}
              {snapshot.human_requests.length > 0
                ? snapshot.human_requests.map((request) => <HumanWaitRow key={request.request_id} request={request} />)
                : <Placeholder text="No human waits." compact />}
            </Stack>
          </Panel>

          <Panel title="Jobs and tools" icon={<MemoryOutlinedIcon />}>
            <Stack spacing={0}>
              {snapshot.active_jobs.length > 0
                ? snapshot.active_jobs.map((job) => <JobRow key={`${job.tool_call_id}:${job.job_id ?? job.status}`} job={job} />)
                : <Placeholder text="No active jobs." />}
              {snapshot.operation_refs.length > 0
                ? snapshot.operation_refs.slice(0, 5).map((operation) => <OperationRow key={operation.id} operation={operation} />)
                : <Placeholder text="No recent tools." compact />}
            </Stack>
          </Panel>
        </Stack>

        <Stack spacing={1.5}>
          <Panel title="Pending approvals" icon={<FactCheckOutlinedIcon />}>
            {snapshot.pending_approvals.length > 0 ? (
              <Stack spacing={0}>
                {snapshot.pending_approvals.map((approval) => <ApprovalRow key={approval.tool_call_id} approval={approval} />)}
              </Stack>
            ) : (
              <Placeholder text="No approvals pending." />
            )}
          </Panel>

          <Panel title="Evidence and artifacts" icon={<TaskAltOutlinedIcon />}>
            <EvidenceLedgerPanel summary={snapshot.evidence_summary} />
          </Panel>

          <Panel title="Budget and tracking" icon={<PlayArrowOutlinedIcon />}>
            <Stack spacing={0.75}>
              <StatusLine label="Budget" value={formatBudget(snapshot)} tone={snapshot.budget.status === 'exhausted' ? 'risk' : 'muted'} />
              <StatusLine label="Source" value={formatSource(snapshot.budget.source)} tone="muted" />
              {snapshot.live_tracking_refs.map((ref, index) => (
                <StatusLine
                  key={ref.id ?? `${ref.provider}:${index}`}
                  label={ref.provider}
                  value={ref.enabled ? humanize(ref.status) : 'not active'}
                  tone={ref.enabled ? 'blue' : 'muted'}
                />
              ))}
              <StatusLine label="Coverage" value={snapshot.compatibility.missing_producers.length > 0 ? 'partial' : 'complete'} tone="muted" />
            </Stack>
          </Panel>

          <Panel title="Resume state" icon={<HourglassBottomOutlinedIcon />}>
            <Stack spacing={0.75}>
              <StatusLine label="Resume" value={snapshot.resume.can_resume ? 'ready' : 'not available'} tone={snapshot.resume.can_resume ? 'good' : 'muted'} />
              <StatusLine label="Reason" value={humanize(snapshot.resume.reason)} tone="muted" />
              <StatusLine label="Restored" value={snapshot.resume.restored_from_snapshot ? 'durable' : 'live'} tone="blue" />
              <StatusLine label="Last event" value={snapshot.resume.last_durable_event_id ?? 'none'} tone="muted" mono />
            </Stack>
          </Panel>
        </Stack>
      </Box>
    </DashboardFrame>
  );
}

function DashboardFrame({ children }: { children: ReactNode }) {
  return (
    <Box
      sx={{
        minHeight: '100%',
        p: { xs: 1.25, sm: 2, lg: 3 },
        bgcolor: 'var(--bg)',
        color: 'var(--text)',
      }}
    >
      <Box sx={{ maxWidth: 1440, mx: 'auto' }}>{children}</Box>
    </Box>
  );
}

function Header({ status, title, subtitle, updatedAt }: { status: string; title: string; subtitle: string; updatedAt: string | null }) {
  return (
    <Box sx={headerSx}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, minWidth: 0 }}>
        <Box component="img" src={terminalAssets.mark} alt="" sx={{ width: 34, height: 34, flexShrink: 0 }} />
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="caption" sx={eyebrowSx}>Project dashboard</Typography>
          <Typography variant="h4" sx={titleSx}>{title}</Typography>
          <Typography variant="body2" sx={{ color: 'var(--muted-text)', fontFamily: '"JetBrains Mono", monospace' }}>
            {subtitle}
          </Typography>
        </Box>
      </Box>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 1 }}>
        <ToneChip label={humanize(status)} tone={statusTone(status)} />
        <ToneChip label={updatedAt ? formatDate(updatedAt) : 'not hydrated'} tone="muted" />
      </Stack>
    </Box>
  );
}

function EmptyProject({ title, detail }: { title: string; detail: string }) {
  return (
    <Box sx={emptySx}>
      <Box component="img" src={terminalAssets.experiment} alt="" sx={{ width: { xs: 96, sm: 118 }, opacity: 0.86 }} />
      <Box>
        <Typography variant="h5" sx={{ fontWeight: 700, mb: 0.5 }}>{title}</Typography>
        <Typography variant="body2" sx={{ color: 'var(--muted-text)', maxWidth: 540 }}>{detail}</Typography>
      </Box>
    </Box>
  );
}

function Panel({ title, icon, children }: { title: string; icon: ReactNode; children: ReactNode }) {
  return (
    <Box sx={panelSx}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
        <Box sx={{ color: 'text.secondary', display: 'flex', '& svg': { fontSize: 18 } }}>{icon}</Box>
        <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>{title}</Typography>
      </Box>
      {children}
    </Box>
  );
}

function Metric({ title, value, detail, tone, mono }: { title: string; value: React.ReactNode; detail: string; tone: Tone; mono?: boolean }) {
  return (
    <Box sx={metricSx}>
      <Typography variant="caption" sx={labelSx}>{title}</Typography>
      <Typography sx={{ fontSize: '1.22rem', fontWeight: 700, lineHeight: 1.15, fontFamily: mono ? '"JetBrains Mono", monospace' : undefined }}>
        {value}
      </Typography>
      <ToneChip label={detail} tone={tone} />
    </Box>
  );
}

function PlanRow({ item }: { item: ProjectPlanItem }) {
  return <Row title={item.content || item.id} meta={humanize(item.status)} tone={item.status === 'completed' ? 'good' : item.status === 'in_progress' ? 'blue' : 'muted'} />;
}

function BlockerRow({ blocker }: { blocker: ProjectBlocker }) {
  return <Row title={blocker.message} meta={humanize(blocker.kind)} tone={blocker.resolved_at ? 'good' : 'risk'} />;
}

function HumanWaitRow({ request }: { request: HumanRequestRef }) {
  return <Row title={request.summary ?? request.request_id} meta={`${humanize(request.status)}${request.channel ? ` / ${request.channel}` : ''}`} tone="amber" mono />;
}

function ApprovalRow({ approval }: { approval: PendingApprovalRef }) {
  return <Row title={approval.reason ?? `Approval required for ${approval.tool ?? 'tool'}`} meta={`${approval.tool_call_id}${approval.risk ? ` / ${approval.risk}` : ''}`} tone="amber" mono />;
}

function JobRow({ job }: { job: ActiveJobRef }) {
  return (
    <Row
      title={job.tool ?? 'tool'}
      meta={job.url ? <Link href={job.url} target="_blank" rel="noreferrer">{job.status}</Link> : job.status}
      tone={job.tool === 'hf_jobs' ? 'blue' : 'amber'}
      id={job.job_id ?? job.tool_call_id}
      mono
    />
  );
}

function OperationRow({ operation }: { operation: OperationRef }) {
  return <Row title={`${operation.type}: ${operation.tool ?? operation.id}`} meta={operation.status} tone={operation.status === 'failed' ? 'risk' : operation.status === 'succeeded' ? 'good' : 'muted'} id={operation.id} mono />;
}

function Row({ title, meta, tone, id, mono }: { title: string; meta: ReactNode; tone: Tone; id?: string; mono?: boolean }) {
  return (
    <Box sx={rowSx}>
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="body2" sx={{ fontWeight: 600, overflowWrap: 'anywhere' }}>{title}</Typography>
        {id && <Typography variant="caption" sx={monoLineSx}>{shortId(id)}</Typography>}
      </Box>
      <ToneChip label={meta} tone={tone} mono={mono} />
    </Box>
  );
}

function Placeholder({ text, compact = false }: { text: string; compact?: boolean }) {
  return (
    <Typography variant="body2" sx={{ color: 'var(--muted-text)', py: compact ? 0.25 : 1 }}>
      {text}
    </Typography>
  );
}

function StatusLine({ label, value, tone, mono }: { label: string; value: string; tone: Tone; mono?: boolean }) {
  return (
    <Box sx={statusLineSx}>
      <Typography variant="caption" sx={labelSx}>{label}</Typography>
      <ToneChip label={value} tone={tone} mono={mono} />
    </Box>
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

function runningOperations(operations: OperationRef[]) {
  return operations.filter((operation) => ['running', 'pending', 'deferred'].includes(operation.status));
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

function formatBudget(snapshot: ProjectSnapshot) {
  const { budget } = snapshot;
  if (budget.status === 'placeholder') return 'not tracked';
  if (budget.limit === null && budget.used === null) return humanize(budget.status);
  const currency = budget.currency ?? 'units';
  return `${budget.used ?? 0}/${budget.limit ?? '?'} ${currency}`;
}

function formatSource(source: string) {
  return source === 'placeholder' ? 'not tracked' : humanize(source);
}
