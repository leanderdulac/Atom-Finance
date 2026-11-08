import { Box, CircularProgress, Typography } from '@mui/material';

export default function LoadingState({ label = 'Carregando…' }: { label?: string }) {
  return (
    <Box
      role="status"
      aria-live="polite"
      sx={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 2,
        minHeight: 240,
        color: 'text.secondary',
      }}
    >
      <CircularProgress size={28} thickness={4} />
      <Typography variant="body2">{label}</Typography>
    </Box>
  );
}
