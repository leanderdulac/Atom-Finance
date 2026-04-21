import React from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, Cell } from 'recharts';
import { Box, Typography } from '@mui/material';

interface VaRDistributionChartProps {
  returns: number[];
  varThreshold: number; // negative number, e.g. -0.032
  confidence?: number;
  height?: number;
}

export default function VaRDistributionChart({ returns, varThreshold, confidence = 0.95, height = 260 }: VaRDistributionChartProps) {
  if (!returns?.length) return null;

  // Build histogram
  const min = Math.min(...returns);
  const max = Math.max(...returns);
  const nBins = 50;
  const binWidth = (max - min) / nBins;
  const bins: { x: number; count: number; pct: string }[] = [];

  for (let i = 0; i < nBins; i++) {
    const lo = min + i * binWidth;
    const hi = lo + binWidth;
    const count = returns.filter((r) => r >= lo && r < hi).length;
    bins.push({ x: parseFloat((lo + binWidth / 2).toFixed(4)), count, pct: ((lo + hi) / 2 * 100).toFixed(2) });
  }

  return (
    <Box>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
        Return Distribution — VaR({(confidence * 100).toFixed(0)}%) threshold: {(varThreshold * 100).toFixed(2)}%
      </Typography>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={bins} margin={{ top: 4, right: 8, bottom: 4, left: 8 }} barCategoryGap={0}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
          <XAxis dataKey="pct" tick={{ fill: '#9ca3af', fontSize: 10 }}
            tickFormatter={(v) => `${v}%`} interval={9} />
          <YAxis tick={{ fill: '#9ca3af', fontSize: 11 }} />
          <Tooltip
            contentStyle={{ background: '#1e1e2e', border: '1px solid #374151', borderRadius: 8 }}
            labelStyle={{ color: '#9ca3af' }}
            formatter={(v: any) => [v, 'Observations']}
            labelFormatter={(l) => `Return ≈ ${l}%`}
          />
          <ReferenceLine x={(varThreshold * 100).toFixed(2)} stroke="#ef4444" strokeWidth={2}
            label={{ value: `VaR`, position: 'insideTopRight', fill: '#ef4444', fontSize: 11 }} />
          <Bar dataKey="count" isAnimationActive={false} radius={[1, 1, 0, 0]}>
            {bins.map((b, i) => (
              <Cell key={i} fill={b.x <= varThreshold ? '#ef444480' : '#6366f180'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </Box>
  );
}
