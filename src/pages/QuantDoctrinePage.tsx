import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Alert, Box, Button, Card, CardActionArea, CardContent, Chip, Stack, Typography,
} from '@mui/material';
import { api } from '../services/api';

type Tenet = { id: string; title: string; lab: string; summary: string };

type Doctrine = {
  version: string;
  system: string;
  tenets: Tenet[];
  eligible_for_live_trading: boolean;
  note: string;
};

export default function QuantDoctrinePage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [doctrine, setDoctrine] = useState<Doctrine | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try { setDoctrine(await api.deskDoctrine()); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void load(); }, [load]);

  return (
    <Box sx={{ maxWidth: 1040, mx: 'auto' }}>
      <Typography variant="h4" sx={{ fontWeight: 800, mb: 1, letterSpacing: '-0.03em' }}>
        Doutrina da mesa
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        Os laboratórios não são demos isolados: são o currículo. Cada chamada LLM da ATOM
        carrega a mesma constituição — maldição do vencedor, relógio sequencial, K-Fold
        não é finança, preço não é alvo, vetorização. Isto não é fine-tune de pesos.
      </Typography>
      <Stack direction="row" spacing={1} sx={{ mb: 2 }} alignItems="center" flexWrap="wrap" useFlexGap>
        <Button variant="contained" disabled={loading} onClick={() => void load()}>
          {loading ? 'Carregando…' : 'Recarregar doutrina'}
        </Button>
        {doctrine && (
          <>
            <Chip label={doctrine.version} />
            <Chip
              color="warning"
              label={`eligible_for_live_trading = ${String(doctrine.eligible_for_live_trading)}`}
            />
          </>
        )}
      </Stack>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {doctrine && (
        <>
          <Alert severity="info" sx={{ mb: 2 }}>{doctrine.note}</Alert>
          <Box
            sx={{
              display: 'grid',
              gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' },
              gap: 2,
              mb: 2,
            }}
          >
            {doctrine.tenets.map((tenet) => (
              <Card key={tenet.id} variant="outlined">
                <CardActionArea component={Link} to={tenet.lab} sx={{ height: '100%' }}>
                  <CardContent>
                    <Typography variant="overline" color="text.secondary">{tenet.lab}</Typography>
                    <Typography variant="h6" sx={{ fontWeight: 700 }}>{tenet.title}</Typography>
                    <Typography color="text.secondary" sx={{ mt: 1 }}>{tenet.summary}</Typography>
                  </CardContent>
                </CardActionArea>
              </Card>
            ))}
          </Box>
          <Card>
            <CardContent>
              <Typography variant="h6" sx={{ mb: 1 }}>System prompt carregado em todo complete()</Typography>
              <Typography
                component="pre"
                sx={{
                  whiteSpace: 'pre-wrap',
                  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
                  fontSize: 13,
                  lineHeight: 1.55,
                  m: 0,
                }}
              >
                {doctrine.system}
              </Typography>
            </CardContent>
          </Card>
        </>
      )}
    </Box>
  );
}
