import { Box, Button, Typography } from '@mui/material';
import type { ReactNode } from 'react';

interface EmptyStateProps {
  title: string;
  description: ReactNode;
  actionLabel?: string;
  onAction?: () => void;
  icon?: ReactNode;
}

export default function EmptyState({ title, description, actionLabel, onAction, icon }: EmptyStateProps) {
  return (
    <Box
      role="status"
      sx={{
        textAlign: 'center',
        px: { xs: 2, md: 6 },
        py: { xs: 5, md: 7 },
        border: '1px dashed',
        borderColor: 'divider',
        borderRadius: 'var(--atom-radius-lg)',
        background:
          'linear-gradient(180deg, color-mix(in srgb, var(--atom-surface) 70%, transparent), transparent)',
      }}
    >
      {icon && (
        <Box sx={{ mb: 2, color: 'primary.main', display: 'flex', justifyContent: 'center' }}>{icon}</Box>
      )}
      <Typography variant="h6" sx={{ mb: 1 }}>
        {title}
      </Typography>
      <Typography color="text.secondary" sx={{ maxWidth: 520, mx: 'auto', mb: actionLabel ? 3 : 0 }}>
        {description}
      </Typography>
      {actionLabel && onAction && (
        <Button variant="contained" onClick={onAction}>
          {actionLabel}
        </Button>
      )}
    </Box>
  );
}
