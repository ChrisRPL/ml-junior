import AssignmentOutlinedIcon from '@mui/icons-material/AssignmentOutlined';
import BlockOutlinedIcon from '@mui/icons-material/BlockOutlined';
import FactCheckOutlinedIcon from '@mui/icons-material/FactCheckOutlined';
import FlagOutlinedIcon from '@mui/icons-material/FlagOutlined';
import HourglassEmptyOutlinedIcon from '@mui/icons-material/HourglassEmptyOutlined';
import Inventory2OutlinedIcon from '@mui/icons-material/Inventory2Outlined';
import RouteOutlinedIcon from '@mui/icons-material/RouteOutlined';
import TrackChangesOutlinedIcon from '@mui/icons-material/TrackChangesOutlined';
import { Box, Chip, Stack, Typography } from '@mui/material';
import type { ReactNode } from 'react';
import type {
  ActiveJobRef,
  HumanRequestRef,
  PendingApprovalRef,
  ProjectBlocker,
  ProjectPlanItem,
  ProjectSnapshot,
} from '@/types/project';
import {
  labelSx,
  monoLineSx,
  panelSx,
  phaseTone,
  statusTone,
  toneBg,
  toneBorder,
  toneFg,
  type Tone,
} from './projectDashboardTokens';

interface HandoffNotebookPanelProps {
  snapshot: ProjectSnapshot;
}

interface NextAction {
  title: string;
  detail: string;
  tone: Tone;
}

interface PlanStats {
  completed: number;
  inProgress: number;
  pending: number;
  other: number;
}

export default function HandoffNotebookPanel({ snapshot }: HandoffNotebookPanelProps) {
  const activeBlockers = snapshot.blockers.filter((blocker) => !blocker.resolved_at);
  const pendingApprovals = snapshot.pending_approvals.filter(isPendingApproval);
  const pendingHumanRequests = snapshot.human_requests.filter((request) => request.status === 'requested');
  const inProgressPlan = snapshot.plan.find((item) => item.status === 'in_progress');
  const pendingPlan = snapshot.plan.find((item) => item.status === 'pending');
  const planStats = countPlan(snapshot.plan);
  const nextAction = deriveNextAction(
    snapshot,
    activeBlockers,
    pendingApprovals,
    pendingHumanRequests,
    inProgressPlan,
    pendingPlan,
  );
  const stale = snapshot.compatibility.stale || snapshot.resume.stale_snapshot || snapshot.status === 'stale';

  return (
    <Box sx={panelSx}>
      <Box
        sx={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: { xs: 'flex-start', sm: 'center' },
          gap: 1.25,
          flexDirection: { xs: 'column', sm: 'row' },
          mb: 1.25,
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
          <Box sx={{ color: 'text.secondary', display: 'flex', '& svg': { fontSize: 18 } }}>
            <AssignmentOutlinedIcon />
          </Box>
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>Handoff notebook</Typography>
            <Typography variant="caption" sx={monoLineSx}>
              snapshot v{snapshot.snapshot_version} / seq {snapshot.last_event_sequence}
            </Typography>
          </Box>
        </Box>
        <Stack direction="row" spacing={0.75} sx={{ flexWrap: 'wrap', rowGap: 0.75 }}>
          <ToneChip label={humanize(snapshot.status)} tone={statusTone(snapshot.status)} />
          <ToneChip label={stale ? 'stale' : 'live'} tone={stale ? 'risk' : 'muted'} />
          <ToneChip label={snapshot.updated_at ? formatDate(snapshot.updated_at) : 'not hydrated'} tone="muted" />
        </Stack>
      </Box>

      <Box sx={notebookGridSx}>
        <NotebookSection title="Status" icon={<FlagOutlinedIcon />} tone={statusTone(snapshot.status)}>
          <NotebookRow label="Status" value={humanize(snapshot.status)} tone={statusTone(snapshot.status)} />
          <NotebookRow label="Phase" value={snapshot.phase.label} detail={humanize(snapshot.phase.status)} tone={phaseTone(snapshot.phase.status)} />
          <NotebookRow label="Updated" value={snapshot.updated_at ? formatDate(snapshot.updated_at) : 'not hydrated'} tone="muted" />
        </NotebookSection>

        <NotebookSection title="Objective" icon={<TrackChangesOutlinedIcon />} tone={snapshot.objective.text ? 'blue' : 'muted'}>
          {snapshot.objective.text ? (
            <Typography variant="body2" sx={{ fontWeight: 600, overflowWrap: 'anywhere' }}>
              {snapshot.objective.text}
            </Typography>
          ) : (
            <Placeholder text="No objective in snapshot." />
          )}
          <MetaLine
            parts={[
              `source ${formatSource(snapshot.objective.source)}`,
              snapshot.objective.updated_at ? `updated ${formatDate(snapshot.objective.updated_at)}` : null,
            ]}
          />
        </NotebookSection>

        <NotebookSection title="Plan" icon={<RouteOutlinedIcon />} tone={planStats.inProgress > 0 ? 'blue' : 'muted'}>
          <Stack direction="row" spacing={0.75} sx={{ flexWrap: 'wrap', rowGap: 0.75, mb: 0.75 }}>
            <ToneChip label={`${snapshot.plan.length} total`} tone={snapshot.plan.length > 0 ? 'blue' : 'muted'} mono />
            <ToneChip label={`${planStats.inProgress} active`} tone={planStats.inProgress > 0 ? 'blue' : 'muted'} mono />
            <ToneChip label={`${planStats.pending} pending`} tone={planStats.pending > 0 ? 'amber' : 'muted'} mono />
            <ToneChip label={`${planStats.completed} done`} tone={planStats.completed > 0 ? 'good' : 'muted'} mono />
            {planStats.other > 0 && <ToneChip label={`${planStats.other} other`} tone="muted" mono />}
          </Stack>
          {inProgressPlan ? (
            <CompactItem title={inProgressPlan.content || inProgressPlan.id} detail="in progress" tone="blue" />
          ) : pendingPlan ? (
            <CompactItem title={pendingPlan.content || pendingPlan.id} detail="next pending" tone="muted" />
          ) : snapshot.plan.length > 0 ? (
            <Placeholder text="No active or pending plan item in snapshot." />
          ) : (
            <Placeholder text="No plan items in snapshot." />
          )}
        </NotebookSection>

        <NotebookSection title="Blockers" icon={<BlockOutlinedIcon />} tone={activeBlockers.length > 0 ? 'risk' : 'muted'}>
          <NotebookRow label="Active" value={`${activeBlockers.length}`} detail={`${snapshot.blockers.length} total`} tone={activeBlockers.length > 0 ? 'risk' : 'muted'} mono />
          {activeBlockers.length > 0 ? (
            <Stack spacing={0}>
              {activeBlockers.slice(0, 2).map((blocker) => (
                <CompactItem key={blocker.id} title={blocker.message} detail={humanize(blocker.kind)} tone="risk" />
              ))}
              {activeBlockers.length > 2 && <Placeholder text={`+${activeBlockers.length - 2} more active blockers in snapshot.`} />}
            </Stack>
          ) : (
            <Placeholder text="No active blockers in snapshot." />
          )}
        </NotebookSection>

        <NotebookSection title="Evidence" icon={<FactCheckOutlinedIcon />} tone={evidenceTone(snapshot.evidence_summary.status)}>
          <NotebookRow label="Status" value={humanize(snapshot.evidence_summary.status)} tone={evidenceTone(snapshot.evidence_summary.status)} />
          <NotebookRow label="Claims" value={`${snapshot.evidence_summary.claim_count}`} detail={`${snapshot.evidence_summary.metric_count} metrics`} tone={snapshot.evidence_summary.claim_count > 0 ? 'good' : 'muted'} mono />
          <NotebookRow label="Artifacts" value={`${snapshot.evidence_summary.artifact_count}`} detail={`${snapshot.evidence_summary.items.length} evidence items`} tone={snapshot.evidence_summary.artifact_count > 0 ? 'blue' : 'muted'} mono />
        </NotebookSection>

        <NotebookSection title="Jobs/artifacts" icon={<Inventory2OutlinedIcon />} tone={snapshot.active_jobs.length > 0 ? 'blue' : 'muted'}>
          <NotebookRow label="Active jobs" value={`${snapshot.active_jobs.length}`} detail={firstJobDetail(snapshot.active_jobs[0])} tone={snapshot.active_jobs.length > 0 ? 'blue' : 'muted'} mono />
          <NotebookRow label="Operations" value={`${snapshot.operation_refs.length}`} detail={snapshot.operation_refs[0] ? `${humanize(snapshot.operation_refs[0].status)} / ${snapshot.operation_refs[0].type}` : undefined} tone={snapshot.operation_refs.length > 0 ? 'amber' : 'muted'} mono />
          <NotebookRow label="Artifacts" value={`${snapshot.evidence_summary.artifact_count}`} detail="from evidence summary" tone={snapshot.evidence_summary.artifact_count > 0 ? 'blue' : 'muted'} mono />
        </NotebookSection>

        <NotebookSection title="Human waits" icon={<HourglassEmptyOutlinedIcon />} tone={pendingHumanRequests.length + pendingApprovals.length > 0 ? 'amber' : 'muted'}>
          <NotebookRow label="Requests" value={`${pendingHumanRequests.length}`} detail={`${snapshot.human_requests.length} total`} tone={pendingHumanRequests.length > 0 ? 'amber' : 'muted'} mono />
          <NotebookRow label="Approvals" value={`${pendingApprovals.length}`} detail={`${snapshot.pending_approvals.length} total`} tone={pendingApprovals.length > 0 ? 'amber' : 'muted'} mono />
          {pendingHumanRequests[0] ? (
            <CompactItem title={humanRequestTitle(pendingHumanRequests[0])} detail={humanize(pendingHumanRequests[0].status)} tone="amber" />
          ) : pendingApprovals[0] ? (
            <CompactItem title={approvalTitle(pendingApprovals[0])} detail="pending approval" tone="amber" />
          ) : (
            <Placeholder text="No human waits in snapshot." />
          )}
        </NotebookSection>

        <NotebookSection title="Next action" icon={<TrackChangesOutlinedIcon />} tone={nextAction.tone}>
          <Typography variant="body2" sx={{ fontWeight: 700, overflowWrap: 'anywhere' }}>
            {nextAction.title}
          </Typography>
          <Typography variant="caption" sx={monoLineSx}>
            {nextAction.detail}
          </Typography>
        </NotebookSection>
      </Box>
    </Box>
  );
}

function NotebookSection({ title, icon, tone, children }: { title: string; icon: ReactNode; tone: Tone; children: ReactNode }) {
  return (
    <Box sx={sectionSx}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 1, mb: 0.75 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, minWidth: 0 }}>
          <Box sx={{ color: toneFg(tone), display: 'flex', '& svg': { fontSize: 17 } }}>{icon}</Box>
          <Typography variant="caption" sx={labelSx}>{title}</Typography>
        </Box>
        <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: toneFg(tone), flexShrink: 0 }} />
      </Box>
      {children}
    </Box>
  );
}

function NotebookRow({ label, value, detail, tone, mono }: { label: string; value: string; detail?: string; tone: Tone; mono?: boolean }) {
  return (
    <Box sx={notebookRowSx}>
      <Typography variant="caption" sx={labelSx}>{label}</Typography>
      <Box sx={{ minWidth: 0, textAlign: 'right' }}>
        <ToneChip label={value} tone={tone} mono={mono} />
        {detail && <Typography variant="caption" sx={{ ...monoLineSx, mt: 0.25 }}>{detail}</Typography>}
      </Box>
    </Box>
  );
}

function CompactItem({ title, detail, tone }: { title: string; detail: string; tone: Tone }) {
  return (
    <Box sx={{ py: 0.45, borderTop: '1px solid var(--border)' }}>
      <Typography variant="body2" sx={{ fontWeight: 600, overflowWrap: 'anywhere' }}>{title}</Typography>
      <ToneChip label={detail} tone={tone} />
    </Box>
  );
}

function MetaLine({ parts }: { parts: Array<string | null> }) {
  const value = parts.filter(Boolean).join(' / ');
  if (!value) return null;

  return (
    <Typography variant="caption" sx={{ ...monoLineSx, mt: 0.5 }}>
      {value}
    </Typography>
  );
}

function Placeholder({ text }: { text: string }) {
  return (
    <Typography variant="body2" sx={{ color: 'var(--muted-text)', py: 0.35 }}>
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

function countPlan(plan: ProjectPlanItem[]): PlanStats {
  return plan.reduce<PlanStats>(
    (counts, item) => {
      if (item.status === 'completed') return { ...counts, completed: counts.completed + 1 };
      if (item.status === 'in_progress') return { ...counts, inProgress: counts.inProgress + 1 };
      if (item.status === 'pending') return { ...counts, pending: counts.pending + 1 };
      return { ...counts, other: counts.other + 1 };
    },
    { completed: 0, inProgress: 0, pending: 0, other: 0 },
  );
}

function deriveNextAction(
  snapshot: ProjectSnapshot,
  activeBlockers: ProjectBlocker[],
  pendingApprovals: PendingApprovalRef[],
  pendingHumanRequests: HumanRequestRef[],
  inProgressPlan: ProjectPlanItem | undefined,
  pendingPlan: ProjectPlanItem | undefined,
): NextAction {
  if (snapshot.compatibility.stale || snapshot.resume.stale_snapshot || snapshot.status === 'stale') {
    return {
      title: 'Snapshot marked stale',
      detail: 'Use a fresh project snapshot before handoff.',
      tone: 'risk',
    };
  }

  if (activeBlockers[0]) {
    return {
      title: 'Resolve active blocker',
      detail: activeBlockers[0].message,
      tone: 'risk',
    };
  }

  if (pendingApprovals[0]) {
    return {
      title: 'Approval pending',
      detail: approvalTitle(pendingApprovals[0]),
      tone: 'amber',
    };
  }

  if (pendingHumanRequests[0]) {
    return {
      title: 'Human response needed',
      detail: humanRequestTitle(pendingHumanRequests[0]),
      tone: 'amber',
    };
  }

  if (snapshot.active_jobs[0]) {
    return {
      title: 'Monitor active job',
      detail: firstJobDetail(snapshot.active_jobs[0]) ?? snapshot.active_jobs[0].tool_call_id,
      tone: 'blue',
    };
  }

  if (inProgressPlan) {
    return {
      title: 'Continue plan item',
      detail: inProgressPlan.content || inProgressPlan.id,
      tone: 'blue',
    };
  }

  if (pendingPlan) {
    return {
      title: 'Start pending plan item',
      detail: pendingPlan.content || pendingPlan.id,
      tone: 'muted',
    };
  }

  if (snapshot.evidence_summary.status === 'failed') {
    return {
      title: 'Evidence summary failed',
      detail: `${snapshot.evidence_summary.claim_count} claims / ${snapshot.evidence_summary.artifact_count} artifacts`,
      tone: 'risk',
    };
  }

  if (snapshot.status === 'completed') {
    return {
      title: 'No next action',
      detail: 'Project status is completed.',
      tone: 'good',
    };
  }

  return {
    title: 'No next action in snapshot',
    detail: 'No active blocker, wait, job, or pending plan item is present.',
    tone: 'muted',
  };
}

function isPendingApproval(approval: PendingApprovalRef) {
  return !approval.status || approval.status === 'pending';
}

function firstJobDetail(job: ActiveJobRef | undefined) {
  if (!job) return undefined;
  return compactParts([
    job.tool ?? 'tool',
    job.job_id ? `job ${shortId(job.job_id)}` : null,
    `status ${humanize(job.status)}`,
  ]);
}

function approvalTitle(approval: PendingApprovalRef) {
  return approval.reason ?? compactParts([approval.tool ?? 'tool', shortId(approval.tool_call_id)]);
}

function humanRequestTitle(request: HumanRequestRef) {
  return request.summary ?? compactParts([request.channel ?? null, shortId(request.request_id)]);
}

function evidenceTone(status: string): Tone {
  if (['verified', 'active'].includes(status)) return 'good';
  if (['failed', 'error'].includes(status)) return 'risk';
  return 'muted';
}

function formatSource(source: string) {
  return source === 'placeholder' ? 'not tracked' : humanize(source);
}

function formatDate(value: string) {
  return new Date(value).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function compactParts(parts: Array<string | null | undefined>) {
  return parts.filter((part): part is string => Boolean(part)).join(' / ');
}

function shortId(value: string) {
  return value.length > 22 ? `${value.slice(0, 10)}...${value.slice(-8)}` : value;
}

function humanize(value: string) {
  return value.replace(/[_-]/g, ' ');
}

const notebookGridSx = {
  display: 'grid',
  gridTemplateColumns: { xs: '1fr', md: 'repeat(2, minmax(0, 1fr))' },
  borderTop: '1px solid var(--border)',
  borderLeft: { md: '1px solid var(--border)' },
};

const sectionSx = {
  minWidth: 0,
  p: { xs: 1, sm: 1.15 },
  borderRight: { md: '1px solid var(--border)' },
  borderBottom: '1px solid var(--border)',
};

const notebookRowSx = {
  display: 'grid',
  gridTemplateColumns: 'minmax(86px, 0.75fr) minmax(0, 1.25fr)',
  gap: 1,
  alignItems: 'start',
  minWidth: 0,
  py: 0.35,
};
