import React from 'react';
import { Box, Typography } from '@mui/material';

interface CorrelationHeatmapProps {
  matrix: number[][];
  labels: string[];
  size?: number;
}

function corrColor(v: number): string {
  if (v >= 0) {
    const t = v;
    const r = Math.round(62 * (1 - t) + 62 * t);
    const g = Math.round(70 * (1 - t) + 224 * t);
    const b = Math.round(80 * (1 - t) + 197 * t);
    return `rgb(${r},${g},${b})`;
  }
  const t = -v;
  const r = Math.round(62 * (1 - t) + 240 * t);
  const g = Math.round(70 * (1 - t) + 113 * t);
  const b = Math.round(80 * (1 - t) + 120 * t);
  return `rgb(${r},${g},${b})`;
}

export default function CorrelationHeatmap({ matrix, labels, size = 52 }: CorrelationHeatmapProps) {
  if (!matrix?.length || !labels?.length) return null;
  const n = labels.length;
  const labelPad = 68;
  const svgW = labelPad + n * size + 4;
  const svgH = labelPad + n * size + 4;

  return (
    <Box sx={{ overflowX: 'auto' }}>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
        Asset Correlation Matrix — blue = negative, purple = positive
      </Typography>
      <svg width={svgW} height={svgH} style={{ fontFamily: 'monospace' }}>
        {/* Column labels */}
        {labels.map((lbl, j) => (
          <text key={j} x={labelPad + j * size + size / 2} y={labelPad - 6}
            textAnchor="middle" fontSize={11} fill="var(--atom-text-muted)"
            transform={`rotate(-35, ${labelPad + j * size + size / 2}, ${labelPad - 6})`}>
            {lbl}
          </text>
        ))}
        {/* Row labels */}
        {labels.map((lbl, i) => (
          <text key={i} x={labelPad - 6} y={labelPad + i * size + size / 2 + 4}
            textAnchor="end" fontSize={11} fill="var(--atom-text-muted)">
            {lbl}
          </text>
        ))}
        {/* Cells */}
        {matrix.map((row, i) =>
          row.map((val, j) => (
            <g key={`${i}-${j}`}>
              <rect
                x={labelPad + j * size} y={labelPad + i * size}
                width={size - 2} height={size - 2}
                fill={corrColor(val)} rx={3}
              />
              <text
                x={labelPad + j * size + size / 2}
                y={labelPad + i * size + size / 2 + 4}
                textAnchor="middle" fontSize={10}
                fill={Math.abs(val) > 0.4 ? 'var(--atom-text)' : 'var(--atom-text-muted)'}
                fontWeight={i === j ? 700 : 400}
              >
                {val.toFixed(2)}
              </text>
            </g>
          ))
        )}
      </svg>
    </Box>
  );
}
