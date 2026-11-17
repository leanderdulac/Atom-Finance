import { useEffect, useState } from 'react';
import { Alert, Box, Card, CardContent, Chip, Stack, Typography } from '@mui/material';
import { api, type OracleSpot } from '../services/api';

/** Live quote provenance: price, per-source age, staleness and disagreement.
 *  Auxiliary by design: it never blocks the operation when the oracle is down. */
export default function OracleSpotCard({ ticker }: { ticker: string }) {
  const [quote, setQuote] = useState<OracleSpot | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    setQuote(null);
    setFailed(false);
    api.oracleSpot(ticker)
      .then((q) => { if (active) setQuote(q); })
      .catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [ticker]);

  if (failed || !quote) return null;
  if (!quote.usable || quote.price == null) {
    return (
      <Alert severity="warning" sx={{ mt: 2 }}>
        Oráculo sem cotação para {quote.symbol}. {(quote.blockers || []).join(' ')}
      </Alert>
    );
  }
  return (
    <Card variant="outlined" sx={{ mt: 2 }}>
      <CardContent>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
          <Typography variant="subtitle2">Oráculo · {quote.symbol}</Typography>
          <Chip size="small" label={quote.price.toLocaleString('pt-BR', { minimumFractionDigits: 2 })} />
          {quote.sources.map((s) => (
            <Chip
              key={s.provider}
              size="small"
              variant="outlined"
              color={s.ok && !s.stale ? 'default' : 'warning'}
              label={s.ok
                ? `${s.provider} · ${s.age_unknown ? 'idade?' : `${s.age_s}s`}${s.stale ? ' · velha' : ''}`
                : `${s.provider} · falha`}
            />
          ))}
        </Stack>
        {(quote.disagreement_bps ?? 0) > 50 && (
          <Alert severity="warning" sx={{ mt: 1 }}>
            Fontes divergem {(quote.disagreement_bps ?? 0).toLocaleString('pt-BR')} bps — arbitrar com desconfiança.
          </Alert>
        )}
        {quote.blockers.length > 0 && (
          <Box component="ul" sx={{ pl: 2, mb: 0, mt: 1 }}>
            {quote.blockers.map((b) => (
              <li key={b}><Typography variant="caption" color="text.secondary">{b}</Typography></li>
            ))}
          </Box>
        )}
      </CardContent>
    </Card>
  );
}
