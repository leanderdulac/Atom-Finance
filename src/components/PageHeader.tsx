import { Box, Chip, Stack, Typography } from '@mui/material';
import type { ReactNode } from 'react';

interface PageHeaderProps {
  kicker?: string;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}

export default function PageHeader({ kicker, title, description, actions }: PageHeaderProps) {
  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: { xs: 'column', md: 'row' },
        alignItems: { md: 'flex-end' },
        justifyContent: 'space-between',
        gap: 2,
        pb: 1,
        mb: 1,
        borderBottom: '1px solid',
        borderColor: 'divider',
      }}
    >
      <Box sx={{ minWidth: 0 }}>
        {kicker && (
          <Chip
            label={kicker}
            size="small"
            sx={{ mb: 1.5, height: 22, fontSize: '0.68rem', letterSpacing: '0.04em' }}
          />
        )}
        <Typography variant="h4" component="h1" sx={{ mb: 0.5 }}>
          {title}
        </Typography>
        {description && (
          <Typography color="text.secondary" sx={{ maxWidth: 640 }}>
            {description}
          </Typography>
        )}
      </Box>
      {actions && (
        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
          {actions}
        </Stack>
      )}
    </Box>
  );
}
