import {
  Avatar,
  Box,
  IconButton,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import MenuIcon from '@mui/icons-material/Menu';
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft';
import DarkModeOutlinedIcon from '@mui/icons-material/DarkModeOutlined';
import LightModeOutlinedIcon from '@mui/icons-material/LightModeOutlined';
import SpaceDashboardOutlinedIcon from '@mui/icons-material/SpaceDashboardOutlined';
import ChatBubbleOutlineIcon from '@mui/icons-material/ChatBubbleOutline';
import type { User } from '@/types/agent';
import type { ThemeMode } from '@/store/layoutStore';

export type MainView = 'dashboard' | 'chat';

interface AppHeaderProps {
  activeTitle?: string | null;
  isLeftSidebarOpen: boolean;
  isMobile: boolean;
  mainView: MainView;
  themeMode: ThemeMode;
  user: User | null;
  onMainViewChange: (view: MainView) => void;
  onToggleLeftSidebar: () => void;
  onToggleTheme: () => void;
}

export default function AppHeader({
  activeTitle,
  isLeftSidebarOpen,
  isMobile,
  mainView,
  themeMode,
  user,
  onMainViewChange,
  onToggleLeftSidebar,
  onToggleTheme,
}: AppHeaderProps) {
  return (
    <Box sx={{
      height: { xs: 52, md: 58 },
      px: { xs: 1, md: 1.75 },
      display: 'flex',
      alignItems: 'center',
      borderBottom: 1,
      borderColor: 'divider',
      bgcolor: 'background.paper',
      zIndex: 1200,
      flexShrink: 0,
      gap: { xs: 0.75, md: 1.25 },
    }}>
      <IconButton onClick={onToggleLeftSidebar} size="small">
        {isLeftSidebarOpen && !isMobile ? <ChevronLeftIcon /> : <MenuIcon />}
      </IconButton>

      <Box sx={{ minWidth: 0, display: 'flex', alignItems: 'center', gap: 0.75 }}>
        <Box
          component="img"
          src="/terminal-cap/logo-terminal-cap-mark.svg"
          alt="ml-junior"
          sx={{ width: { xs: 24, md: 26 }, height: { xs: 24, md: 26 }, flexShrink: 0 }}
        />
        <Typography
          variant="subtitle1"
          sx={{
            fontWeight: 700,
            color: 'var(--text)',
            letterSpacing: 0,
            fontSize: { xs: '0.9rem', md: '1rem' },
            lineHeight: 1,
            whiteSpace: 'nowrap',
          }}
        >
          ml-junior
        </Typography>
      </Box>

      {activeTitle && (
        <Box
          sx={{
            minWidth: 0,
            flex: 1,
            display: 'flex',
            alignItems: 'center',
            gap: 1,
            color: 'text.secondary',
          }}
        >
          <Box sx={{ width: '1px', height: 22, bgcolor: 'divider', flexShrink: 0, display: { xs: 'none', sm: 'block' } }} />
          <Typography
            variant="body2"
            sx={{
              display: { xs: 'none', sm: 'block' },
              flex: 1,
              minWidth: 0,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              fontWeight: 500,
              color: 'text.secondary',
            }}
          >
            {activeTitle}
          </Typography>
        </Box>
      )}

      {!activeTitle && <Box sx={{ flex: 1 }} />}

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
        <ToggleButtonGroup
          exclusive
          size="small"
          value={mainView}
          onChange={(_, value: MainView | null) => {
            if (value) onMainViewChange(value);
          }}
          sx={{
            mr: { xs: 0, sm: 0.75 },
            bgcolor: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: '8px',
            '& .MuiToggleButton-root': {
              px: { xs: 0.75, sm: 1 },
              py: 0.4,
              border: 0,
              borderRadius: '6px',
              color: 'text.secondary',
              minWidth: { xs: 34, sm: 38 },
              '&.Mui-selected': {
                bgcolor: 'var(--accent-yellow-weak)',
                color: 'text.primary',
              },
            },
          }}
        >
          <ToggleButton value="dashboard" aria-label="Project dashboard">
            <SpaceDashboardOutlinedIcon fontSize="small" />
          </ToggleButton>
          <ToggleButton value="chat" aria-label="Chat">
            <ChatBubbleOutlineIcon fontSize="small" />
          </ToggleButton>
        </ToggleButtonGroup>

        <IconButton
          onClick={onToggleTheme}
          size="small"
          sx={{
            color: 'text.secondary',
            '&:hover': { color: 'primary.main' },
          }}
        >
          {themeMode === 'dark' ? <LightModeOutlinedIcon fontSize="small" /> : <DarkModeOutlinedIcon fontSize="small" />}
        </IconButton>

        {user?.picture ? (
          <Avatar
            src={user.picture}
            alt={user.username || 'User'}
            sx={{ width: 28, height: 28, ml: 0.5 }}
          />
        ) : user?.username ? (
          <Avatar
            sx={{
              width: 28,
              height: 28,
              ml: 0.5,
              bgcolor: 'primary.main',
              fontSize: '0.75rem',
              fontWeight: 700,
            }}
          >
            {user.username[0].toUpperCase()}
          </Avatar>
        ) : null}
      </Box>
    </Box>
  );
}
