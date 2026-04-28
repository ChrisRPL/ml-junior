import { createTheme, type ThemeOptions } from '@mui/material/styles';

// ── Shared tokens ────────────────────────────────────────────────
const sharedTypography: ThemeOptions['typography'] = {
  fontFamily: '"Space Grotesk", "Avenir Next", "Trebuchet MS", sans-serif',
  fontSize: 15,
  button: {
    fontFamily: '"Space Grotesk", "Avenir Next", "Trebuchet MS", sans-serif',
    textTransform: 'none' as const,
    fontWeight: 600,
  },
};

const sharedComponents: ThemeOptions['components'] = {
  MuiButton: {
    styleOverrides: {
      root: {
        borderRadius: '8px',
        fontWeight: 600,
        transition: 'transform 0.06s ease, background 0.12s ease, box-shadow 0.12s ease',
        '&:hover': { transform: 'translateY(-1px)' },
      },
    },
  },
  MuiPaper: {
    styleOverrides: {
      root: { backgroundImage: 'none' },
    },
  },
};

const sharedShape: ThemeOptions['shape'] = { borderRadius: 8 };

// ── Dark palette ─────────────────────────────────────────────────
const darkVars = {
  '--bg': '#141420',
  '--panel': '#1C1C27',
  '--surface': '#23232E',
  '--text': '#FAFAF8',
  '--muted-text': '#B3AFA7',
  '--accent-yellow': '#D4933A',
  '--accent-yellow-weak': 'rgba(212,147,58,0.16)',
  '--accent-blue': '#3A72C8',
  '--accent-green': '#2F9B73',
  '--accent-red': '#C85644',
  '--shadow-1': '0 6px 18px rgba(20,20,32,0.45)',
  '--radius-lg': '8px',
  '--radius-md': '8px',
  '--focus': '0 0 0 3px rgba(212,147,58,0.18)',
  '--border': 'rgba(250,250,248,0.08)',
  '--border-hover': 'rgba(250,250,248,0.18)',
  '--code-bg': 'rgba(0,0,0,0.5)',
  '--tool-bg': 'rgba(0,0,0,0.3)',
  '--tool-border': 'rgba(250,250,248,0.08)',
  '--hover-bg': 'rgba(250,250,248,0.06)',
  '--composer-bg': 'rgba(250,250,248,0.03)',
  '--msg-gradient': 'linear-gradient(180deg, rgba(255,255,255,0.015), transparent)',
  '--body-gradient': 'linear-gradient(180deg, #141420, #10101A)',
  '--scrollbar-thumb': '#746F68',
  '--success-icon': '#D4933A',
  '--error-icon': '#C85644',
  '--clickable-text': 'rgba(255, 255, 255, 0.9)',
  '--clickable-underline': 'rgba(255,255,255,0.3)',
  '--code-panel-bg': '#10101A',
  '--tab-active-bg': 'rgba(255,255,255,0.08)',
  '--tab-active-border': 'rgba(255,255,255,0.1)',
  '--tab-hover-bg': 'rgba(255,255,255,0.05)',
  '--tab-close-hover': 'rgba(255,255,255,0.1)',
  '--plan-bg': 'rgba(0,0,0,0.2)',
} as const;

// ── Light palette ────────────────────────────────────────────────
const lightVars = {
  '--bg': '#E8E6E0',
  '--panel': '#FAFAF8',
  '--surface': '#F2F0EA',
  '--text': '#141420',
  '--muted-text': '#746F68',
  '--accent-yellow': '#D4933A',
  '--accent-yellow-weak': '#FDF0DC',
  '--accent-blue': '#3A72C8',
  '--accent-green': '#2F9B73',
  '--accent-red': '#C85644',
  '--shadow-1': '0 4px 12px rgba(20,20,32,0.08)',
  '--radius-lg': '8px',
  '--radius-md': '8px',
  '--focus': '0 0 0 3px rgba(212,147,58,0.18)',
  '--border': 'rgba(0,0,0,0.08)',
  '--border-hover': 'rgba(0,0,0,0.15)',
  '--code-bg': 'rgba(0,0,0,0.04)',
  '--tool-bg': 'rgba(0,0,0,0.03)',
  '--tool-border': 'rgba(0,0,0,0.08)',
  '--hover-bg': 'rgba(0,0,0,0.04)',
  '--composer-bg': 'rgba(0,0,0,0.02)',
  '--msg-gradient': 'linear-gradient(180deg, rgba(0,0,0,0.01), transparent)',
  '--body-gradient': 'linear-gradient(180deg, #E8E6E0, #FAFAF8)',
  '--scrollbar-thumb': '#B3AFA7',
  '--success-icon': '#D4933A',
  '--error-icon': '#C85644',
  '--clickable-text': 'rgba(0, 0, 0, 0.85)',
  '--clickable-underline': 'rgba(0,0,0,0.25)',
  '--code-panel-bg': '#FAFAF8',
  '--tab-active-bg': 'rgba(0,0,0,0.06)',
  '--tab-active-border': 'rgba(0,0,0,0.1)',
  '--tab-hover-bg': 'rgba(0,0,0,0.04)',
  '--tab-close-hover': 'rgba(0,0,0,0.08)',
  '--plan-bg': 'rgba(0,0,0,0.03)',
} as const;

// ── Shared CSS baseline (scrollbar, code, brand-logo) ────────────
function makeCssBaseline(vars: Record<string, string>) {
  return {
    styleOverrides: {
      ':root': vars,
      body: {
        background: 'var(--body-gradient)',
        color: 'var(--text)',
        scrollbarWidth: 'thin' as const,
        '&::-webkit-scrollbar': { width: '8px', height: '8px' },
        '&::-webkit-scrollbar-thumb': {
          backgroundColor: 'var(--scrollbar-thumb)',
          borderRadius: '2px',
        },
        '&::-webkit-scrollbar-track': { backgroundColor: 'transparent' },
      },
      'code, pre': {
        fontFamily: '"JetBrains Mono", "SFMono-Regular", Consolas, monospace',
      },
      '.brand-logo': {
        position: 'relative' as const,
        padding: '6px',
        borderRadius: '8px',
        '&::after': {
          content: '""',
          position: 'absolute' as const,
          inset: '-6px',
          borderRadius: '10px',
          background: 'var(--accent-yellow-weak)',
          zIndex: -1,
          pointerEvents: 'none' as const,
        },
      },
    },
  };
}

function makeDrawer() {
  return {
    styleOverrides: {
      paper: {
        backgroundColor: 'var(--panel)',
        borderRight: '1px solid var(--border)',
      },
    },
  };
}

function makeTextField() {
  return {
    styleOverrides: {
      root: {
        '& .MuiOutlinedInput-root': {
          borderRadius: 'var(--radius-md)',
          '& fieldset': { borderColor: 'var(--border)' },
          '&:hover fieldset': { borderColor: 'var(--border-hover)' },
          '&.Mui-focused fieldset': {
            borderColor: 'var(--accent-yellow)',
            borderWidth: '1px',
            boxShadow: 'var(--focus)',
          },
        },
      },
    },
  };
}

// ── Theme builders ───────────────────────────────────────────────
export const darkTheme = createTheme({
  palette: {
    mode: 'dark',
    primary: { main: '#D4933A', light: '#E7AF61', dark: '#9A651F', contrastText: '#141420' },
    secondary: { main: '#3A72C8' },
    background: { default: '#141420', paper: '#1C1C27' },
    text: { primary: '#FAFAF8', secondary: '#B3AFA7' },
    divider: 'rgba(250,250,248,0.08)',
    success: { main: '#2F9B73' },
    error: { main: '#C85644' },
    warning: { main: '#D4933A' },
    info: { main: '#3A72C8' },
  },
  typography: sharedTypography,
  components: {
    ...sharedComponents,
    MuiCssBaseline: makeCssBaseline(darkVars),
    MuiDrawer: makeDrawer(),
    MuiTextField: makeTextField(),
  },
  shape: sharedShape,
});

export const lightTheme = createTheme({
  palette: {
    mode: 'light',
    primary: { main: '#D4933A', light: '#E7AF61', dark: '#9A651F', contrastText: '#141420' },
    secondary: { main: '#3A72C8' },
    background: { default: '#E8E6E0', paper: '#FAFAF8' },
    text: { primary: '#141420', secondary: '#746F68' },
    divider: '#E6E4DF',
    success: { main: '#2F9B73' },
    error: { main: '#C85644' },
    warning: { main: '#D4933A' },
    info: { main: '#3A72C8' },
  },
  typography: sharedTypography,
  components: {
    ...sharedComponents,
    MuiCssBaseline: makeCssBaseline(lightVars),
    MuiDrawer: makeDrawer(),
    MuiTextField: makeTextField(),
  },
  shape: sharedShape,
});

// Keep default export for backwards compat
export default darkTheme;
