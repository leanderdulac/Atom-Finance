import React from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
import { Box, Typography } from '@mui/material';

interface GBMChartProps {
  data: {
    time: number[];
    paths: number[][];
    mean: number[];
    p5: number[];
    p95: number[];
    S0: number;
  };
  height?: number;
}

export default function GBMChart({ data, height = 320 }: GBMChartProps) {
  if (!data?.time?.length) return null;

  // Build chart data: one object per time step with mean, p5, p95 and up to 30 sample paths
  const nSamples = Math.min(data.paths?.length || 0, 30);
  const chartData = data.time.map((t, i) => {
    const point: Record<string, number> = {
      t: Math.round(t * 252), // trading days
      mean: data.mean[i],
      p5: data.p5[i],
      p95: data.p95[i],
    };
    for (let j = 0; j < nSamples; j++) {
      point[`p${j}`] = data.paths[j][i];
    }
    return point;
  });

  const colors = Array.from({ length: nSamples }, (_, i) =>
    `hsl(${(i * 13 + 200) % 360}, 60%, 55%)`
  );

  return (
    <Box>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
        GBM Monte Carlo — {data.paths?.length} paths · mean (white) · 90% band (blue shading)
      </Typography>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={chartData} margin={{ top: 4, right: 16, bottom: 4, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
          <XAxis dataKey="t" tick={{ fill: '#9ca3af', fontSize: 11 }} label={{ value: 'Days', position: 'insideBottom', fill: '#6b7280', fontSize: 11 }} />
          <YAxis tick={{ fill: '#9ca3af', fontSize: 11 }} tickFormatter={(v) => `$${v.toFixed(0)}`} />
          <Tooltip
            contentStyle={{ background: '#1e1e2e', border: '1px solid #374151', borderRadius: 8 }}
            labelStyle={{ color: '#9ca3af' }}
            formatter={(v: any) => [`$${Number(v).toFixed(2)}`]}
            labelFormatter={(l) => `Day ${l}`}
          />
          <ReferenceLine y={data.S0} stroke="#6b7280" strokeDasharray="4 4" />

          {/* Sample paths — thin and semi-transparent */}
          {Array.from({ length: nSamples }, (_, j) => (
            <Line key={j} type="monotone" dataKey={`p${j}`} dot={false}
              stroke={colors[j]} strokeWidth={0.8} strokeOpacity={0.35} isAnimationActive={false} />
          ))}

          {/* Confidence bands */}
          <Line type="monotone" dataKey="p95" dot={false} stroke="#3b82f6" strokeWidth={1.5}
            strokeDasharray="4 2" strokeOpacity={0.7} isAnimationActive={false} />
          <Line type="monotone" dataKey="p5" dot={false} stroke="#3b82f6" strokeWidth={1.5}
            strokeDasharray="4 2" strokeOpacity={0.7} isAnimationActive={false} />

          {/* Mean path — prominent */}
          <Line type="monotone" dataKey="mean" dot={false} stroke="#f8fafc"
            strokeWidth={2.5} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </Box>
  );
}
