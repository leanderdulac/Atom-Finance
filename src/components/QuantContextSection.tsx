import React from 'react';
import { Alert, Box, Card, CardContent, Grid, Typography } from '@mui/material';

export interface QuantContextItem {
  title: string;
  text: string;
}

interface QuantContextSectionProps {
  conceptsTitle: string;
  notesTitle?: string;
  concepts: QuantContextItem[];
  notes: string[];
}

export default function QuantContextSection({
  conceptsTitle,
  notesTitle = 'Development notes',
  concepts,
  notes,
}: QuantContextSectionProps) {
  return (
    <Grid container spacing={2.5} sx={{ mt: 0.5 }}>
      <Grid size={{ xs: 12, md: 7 }}>
        <Card>
          <CardContent>
            <Typography variant="h6" gutterBottom>
              {conceptsTitle}
            </Typography>
            <Grid container spacing={2}>
              {concepts.map((item) => (
                <Grid key={item.title} size={{ xs: 12, sm: 4 }}>
                  <Box sx={{ p: 2, border: 1, borderColor: 'divider', borderRadius: 2, height: '100%' }}>
                    <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
                      {item.title}
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.7 }}>
                      {item.text}
                    </Typography>
                  </Box>
                </Grid>
              ))}
            </Grid>
          </CardContent>
        </Card>
      </Grid>
      <Grid size={{ xs: 12, md: 5 }}>
        <Card>
          <CardContent>
            <Typography variant="h6" gutterBottom>
              {notesTitle}
            </Typography>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
              {notes.map((item) => (
                <Alert key={item} severity="info">
                  {item}
                </Alert>
              ))}
            </Box>
          </CardContent>
        </Card>
      </Grid>
    </Grid>
  );
}
