import React from 'react';
import { Box, Chip, Typography } from '@mui/material';

interface ProviderChipsProps {
  value: string;
  onChange: (provider: string) => void;
}

const PROVIDERS = [
  { value: 'auto', label: 'Auto' },
  { value: 'brapi', label: 'brapi (B3)' },
  { value: 'openbb', label: 'OpenBB' },
  { value: 'yfinance', label: 'Yahoo' },
  { value: 'synthetic', label: 'Synthetic' },
];

export default function ProviderChips({ value, onChange }: ProviderChipsProps) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
        Market Provider
      </Typography>
      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
        {PROVIDERS.map((provider) => (
          <Chip
            key={provider.value}
            label={provider.label}
            color={value === provider.value ? 'primary' : 'default'}
            variant={value === provider.value ? 'filled' : 'outlined'}
            onClick={() => onChange(provider.value)}
            sx={{ fontWeight: value === provider.value ? 700 : 500 }}
          />
        ))}
      </Box>
    </Box>
  );
}