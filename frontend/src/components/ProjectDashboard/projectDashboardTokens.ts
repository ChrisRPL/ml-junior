export type Tone = 'amber' | 'blue' | 'good' | 'risk' | 'muted';

export const terminalAssets = {
  mark: '/terminal-cap/logo-terminal-cap-mark.svg',
  pattern: '/terminal-cap/pattern-workbench.svg',
  evidence: '/terminal-cap/empty-state-evidence.svg',
  experiment: '/terminal-cap/empty-state-experiment.svg',
};

export function statusTone(status: string): Tone {
  if (['completed'].includes(status)) return 'good';
  if (['processing'].includes(status)) return 'blue';
  if (['waiting_approval', 'blocked', 'interrupted'].includes(status)) return 'amber';
  if (['error', 'stale'].includes(status)) return 'risk';
  return 'muted';
}

export function phaseTone(status: string): Tone {
  if (status === 'complete') return 'good';
  if (status === 'active') return 'blue';
  if (status === 'blocked') return 'amber';
  if (status === 'failed') return 'risk';
  return 'muted';
}

export function toneBg(tone: Tone) {
  return ({ amber: '#FDF0DC', blue: '#E6EEFA', good: '#E7F5EF', risk: '#FCE8E4', muted: '#F2F0EA' } as const)[tone];
}

export function toneFg(tone: Tone) {
  return ({ amber: '#8A581B', blue: '#24569D', good: '#1E6C50', risk: '#973A2E', muted: '#746F68' } as const)[tone];
}

export function toneBorder(tone: Tone) {
  return ({ amber: '#F1D1A4', blue: '#C7D8F4', good: '#BEE3D2', risk: '#F1C1B8', muted: '#E6E4DF' } as const)[tone];
}

export const headerSx = {
  mb: 2,
  p: { xs: 1.5, sm: 2 },
  border: '1px solid #DCD7CE',
  borderRadius: '8px',
  bgcolor: 'rgba(250, 250, 248, 0.92)',
  display: 'flex',
  gap: 2,
  justifyContent: 'space-between',
  alignItems: { xs: 'flex-start', md: 'center' },
  flexDirection: { xs: 'column', md: 'row' },
};

export const alertSx = {
  mb: 2,
  borderRadius: '8px',
  border: '1px solid #F1D1A4',
  bgcolor: '#FDF0DC',
  color: '#141420',
};

export const overviewGridSx = {
  display: 'grid',
  gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))', lg: 'repeat(4, minmax(0, 1fr))' },
  gap: 1.5,
  mb: 1.5,
};

export const dashboardGridSx = {
  display: 'grid',
  gridTemplateColumns: { xs: '1fr', lg: 'repeat(2, minmax(0, 1fr))', xl: 'repeat(3, minmax(0, 1fr))' },
  gap: 1.5,
  alignItems: 'start',
};

export const panelSx = {
  border: '1px solid #DCD7CE',
  borderRadius: '8px',
  bgcolor: 'rgba(250, 250, 248, 0.94)',
  p: { xs: 1.5, sm: 2 },
  minWidth: 0,
};

export const metricSx = {
  ...panelSx,
  display: 'flex',
  flexDirection: 'column',
  gap: 0.75,
};

export const rowSx = {
  display: 'grid',
  gridTemplateColumns: 'minmax(0, 1fr) auto',
  gap: 1,
  alignItems: 'center',
  border: '1px solid #E6E4DF',
  borderRadius: '6px',
  p: 1,
  bgcolor: '#FFFFFF',
};

export const statusLineSx = {
  display: 'flex',
  gap: 1,
  alignItems: 'center',
  justifyContent: 'space-between',
  minWidth: 0,
};

export const emptySx = {
  minHeight: 360,
  border: '1px solid #DCD7CE',
  borderRadius: '8px',
  bgcolor: 'rgba(250, 250, 248, 0.94)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  gap: { xs: 1.5, sm: 3 },
  flexDirection: { xs: 'column', sm: 'row' },
  textAlign: { xs: 'center', sm: 'left' },
  p: 3,
};

export const eyebrowSx = {
  color: '#8A581B',
  fontWeight: 900,
  letterSpacing: '0.08em',
  lineHeight: 1,
};

export const titleSx = {
  fontWeight: 900,
  fontSize: { xs: '1.45rem', sm: '2rem' },
  lineHeight: 1.05,
  overflowWrap: 'anywhere',
};

export const labelSx = {
  color: 'var(--muted-text)',
  fontWeight: 800,
  textTransform: 'uppercase',
  letterSpacing: '0.08em',
};

export const monoLineSx = {
  display: 'block',
  color: 'var(--muted-text)',
  fontFamily: '"JetBrains Mono", monospace',
  overflowWrap: 'anywhere',
};
