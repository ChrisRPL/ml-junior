import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  Divider,
  Stack,
  Typography,
} from '@mui/material';
import GppMaybeOutlinedIcon from '@mui/icons-material/GppMaybeOutlined';
import ListAltOutlinedIcon from '@mui/icons-material/ListAltOutlined';
import type { ReactNode } from 'react';
import { useEffect, useState } from 'react';
import {
  fetchFlowCatalog,
  fetchFlowPreview,
  type FlowCatalogItem,
  type FlowPreviewApiFailureResult,
  type FlowPreviewResponse,
} from '@/lib/flow-preview-api';
import { apiFetch } from '@/utils/api';
import {
  eyebrowSx,
  monoLineSx,
  panelSx,
  toneBg,
  toneBorder,
  toneFg,
  type Tone,
} from './projectDashboardTokens';
import FlowPreviewDetails from './FlowPreviewDetails';

type CatalogState =
  | { kind: 'loading' }
  | { kind: 'ready'; items: FlowCatalogItem[] }
  | { kind: 'empty' }
  | { kind: 'error'; failure: FlowPreviewApiFailureResult };

type PreviewState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'ready'; preview: FlowPreviewResponse }
  | { kind: 'error'; failure: FlowPreviewApiFailureResult };

export default function FlowCatalogPanel() {
  const [catalogState, setCatalogState] = useState<CatalogState>({ kind: 'loading' });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [previewState, setPreviewState] = useState<PreviewState>({ kind: 'idle' });

  useEffect(() => {
    let cancelled = false;
    setCatalogState({ kind: 'loading' });

    fetchFlowCatalog(apiFetch).then((result) => {
      if (cancelled) return;
      if (!result.ok) {
        setSelectedId(null);
        setPreviewState({ kind: 'idle' });
        setCatalogState({ kind: 'error', failure: result });
        return;
      }
      if (result.catalog.length === 0) {
        setSelectedId(null);
        setPreviewState({ kind: 'idle' });
        setCatalogState({ kind: 'empty' });
        return;
      }
      setCatalogState({ kind: 'ready', items: result.catalog });
      setSelectedId((current) => (
        current && result.catalog.some((item) => item.id === current)
          ? current
          : result.catalog[0]?.id ?? null
      ));
    });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setPreviewState({ kind: 'idle' });
      return;
    }

    let cancelled = false;
    setPreviewState({ kind: 'loading' });
    fetchFlowPreview(selectedId, apiFetch).then((result) => {
      if (cancelled) return;
      setPreviewState(result.ok ? { kind: 'ready', preview: result.preview } : { kind: 'error', failure: result });
    });

    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const catalogItems = catalogState.kind === 'ready' ? catalogState.items : [];
  const selectedItem = catalogItems.find((item) => item.id === selectedId) ?? null;

  return (
    <Box sx={panelSx}>
      <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 1.5, mb: 1.5, flexWrap: 'wrap' }}>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="caption" sx={eyebrowSx}>Flow catalog</Typography>
          <Typography variant="h6" sx={{ fontWeight: 700, lineHeight: 1.15 }}>Built-in flow previews</Typography>
          <Typography variant="body2" sx={{ color: 'var(--muted-text)', mt: 0.25 }}>
            Read-only templates from backend workflow definitions.
          </Typography>
        </Box>
        <Stack direction="row" spacing={0.75} sx={{ flexWrap: 'wrap', rowGap: 0.75 }}>
          <FlowChip label="read only" tone="good" />
          <FlowChip label="backend sourced" tone="blue" />
        </Stack>
      </Box>

      {catalogState.kind === 'loading' && <PanelState title="Loading flow catalog" detail="Fetching /api/flows." loading />}
      {catalogState.kind === 'empty' && <PanelState title="No flows available" detail="The backend returned an empty flow catalog." />}
      {catalogState.kind === 'error' && <FailureState failure={catalogState.failure} endpoint="/api/flows" />}
      {catalogState.kind === 'ready' && (
        <Box sx={catalogLayoutSx}>
          <CatalogList items={catalogState.items} selectedId={selectedId} onSelect={setSelectedId} />
          <PreviewPane state={previewState} selectedItem={selectedItem} />
        </Box>
      )}
    </Box>
  );
}

function CatalogList({
  items,
  selectedId,
  onSelect,
}: {
  items: FlowCatalogItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <Box sx={{ minWidth: 0 }}>
      <SectionHeading icon={<ListAltOutlinedIcon />} title="Catalog" meta={`${items.length} templates`} />
      <Box sx={{ borderTop: '1px solid var(--border)' }}>
        {items.map((item) => {
          const selected = item.id === selectedId;
          return (
            <Box
              key={item.id}
              component="button"
              type="button"
              aria-pressed={selected}
              onClick={() => onSelect(item.id)}
              sx={{
                width: '100%',
                appearance: 'none',
                border: 0,
                borderBottom: '1px solid var(--border)',
                borderLeft: selected ? '3px solid var(--accent-yellow)' : '3px solid transparent',
                bgcolor: selected ? 'var(--accent-yellow-weak)' : 'transparent',
                color: 'var(--text)',
                cursor: 'pointer',
                textAlign: 'left',
                p: 1,
                transition: 'background 0.12s ease, border-color 0.12s ease',
                '&:hover': { bgcolor: 'var(--hover-bg)' },
                '&:focus-visible': { outline: 'none', boxShadow: 'var(--focus)' },
              }}
            >
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 1, alignItems: 'flex-start' }}>
                <Box sx={{ minWidth: 0 }}>
                  <Typography variant="body2" sx={{ fontWeight: 700, overflowWrap: 'anywhere' }}>{item.name}</Typography>
                  <Typography variant="caption" sx={monoLineSx}>{item.id}</Typography>
                </Box>
                <FlowChip label={item.metadata.category} tone="amber" />
              </Box>
              {item.description && (
                <Typography variant="body2" sx={{ color: 'var(--muted-text)', mt: 0.75, overflowWrap: 'anywhere' }}>
                  {item.description}
                </Typography>
              )}
              <Stack direction="row" spacing={0.75} sx={{ flexWrap: 'wrap', rowGap: 0.75, mt: 1 }}>
                <FlowChip label={`${item.phase_count} phases`} tone="blue" />
                <FlowChip label={`${item.required_inputs.length} inputs`} tone={item.required_inputs.length > 0 ? 'amber' : 'muted'} />
                <FlowChip label={`${item.approval_point_count} approvals`} tone={item.approval_point_count > 0 ? 'risk' : 'muted'} />
                <FlowChip label={`${item.verifier_count} checks`} tone="good" />
              </Stack>
            </Box>
          );
        })}
      </Box>
    </Box>
  );
}

function PreviewPane({ state, selectedItem }: { state: PreviewState; selectedItem: FlowCatalogItem | null }) {
  if (!selectedItem) {
    return <PanelState title="Select a flow" detail="Choose a template from the catalog to inspect its preview." />;
  }
  if (state.kind === 'loading') {
    return <PanelState title="Loading preview" detail={`Fetching /api/flows/${selectedItem.id}/preview.`} loading />;
  }
  if (state.kind === 'error') {
    return <FailureState failure={state.failure} endpoint={`/api/flows/${selectedItem.id}/preview`} />;
  }
  if (state.kind !== 'ready') {
    return <PanelState title="Preview pending" detail="Waiting for a selected flow template." />;
  }

  return <FlowPreviewDetails preview={state.preview} />;
}

function SectionHeading({ icon, title, meta }: { icon: ReactNode; title: string; meta?: string }) {
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1, minWidth: 0 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, minWidth: 0 }}>
        <Box sx={{ color: 'text.secondary', display: 'flex', '& svg': { fontSize: 18 } }}>{icon}</Box>
        <Typography variant="subtitle2" sx={{ fontWeight: 700, overflowWrap: 'anywhere' }}>{title}</Typography>
      </Box>
      {meta && <FlowChip label={meta} tone="muted" mono />}
    </Box>
  );
}

function PanelState({ title, detail, loading = false }: { title: string; detail: string; loading?: boolean }) {
  return (
    <Box sx={{ minHeight: 180, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 1.25, textAlign: 'center', flexDirection: 'column', color: 'var(--muted-text)' }}>
      {loading && <CircularProgress size={22} color="inherit" />}
      <Typography variant="subtitle2" sx={{ color: 'var(--text)', fontWeight: 700 }}>{title}</Typography>
      <Typography variant="body2" sx={{ maxWidth: 460 }}>{detail}</Typography>
    </Box>
  );
}

function FailureState({ failure, endpoint }: { failure: FlowPreviewApiFailureResult; endpoint: string }) {
  const copy = failureCopy(failure);
  return (
    <Alert severity={copy.severity} icon={<GppMaybeOutlinedIcon fontSize="small" />} sx={{ borderRadius: '8px', bgcolor: 'var(--panel)', color: 'var(--text)', border: '1px solid var(--border)' }}>
      <Typography variant="body2" sx={{ fontWeight: 700 }}>{copy.title}</Typography>
      <Typography variant="body2" sx={{ color: 'var(--muted-text)' }}>{copy.detail}</Typography>
      <Divider sx={{ my: 0.75 }} />
      <Typography variant="caption" sx={monoLineSx}>
        {endpoint} / {failure.warning}{failure.status ? ` / HTTP ${failure.status}` : ''}
      </Typography>
    </Alert>
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

function failureCopy(failure: FlowPreviewApiFailureResult): { title: string; detail: string; severity: 'warning' | 'error' } {
  if (failure.warning.endsWith('backend_unavailable')) {
    return {
      title: 'Backend unavailable',
      detail: 'The dashboard could not reach the read-only flow endpoint.',
      severity: 'warning',
    };
  }
  if (failure.warning.endsWith('malformed')) {
    return {
      title: 'Malformed flow response',
      detail: 'The endpoint returned a shape the dashboard will not render.',
      severity: 'error',
    };
  }
  return {
    title: 'Flow endpoint error',
    detail: 'The backend rejected the read-only flow request.',
    severity: 'warning',
  };
}

const catalogLayoutSx = {
  display: 'grid',
  gridTemplateColumns: { xs: '1fr', xl: 'minmax(260px, 0.52fr) minmax(0, 1.48fr)' },
  gap: { xs: 1.5, md: 2 },
  alignItems: 'start',
};
