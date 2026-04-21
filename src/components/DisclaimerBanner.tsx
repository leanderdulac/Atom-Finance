import React, { useState, useEffect } from 'react';
import {
  Box, Button, Dialog, DialogContent, DialogTitle,
  Typography, Chip, IconButton, Slide,
} from '@mui/material';
import { TransitionProps } from '@mui/material/transitions';
import { Warning, Close, Shield, TrendingUp } from '@mui/icons-material';

const SESSION_KEY = 'atom_disclaimer_accepted';

const Transition = React.forwardRef(function Transition(
  props: TransitionProps & { children: React.ReactElement<any, any> },
  ref: React.Ref<unknown>,
) {
  return <Slide direction="up" ref={ref} {...props} />;
});

export default function DisclaimerBanner() {
  const [open, setOpen] = useState(false);
  const [bannerVisible, setBannerVisible] = useState(false);

  useEffect(() => {
    const accepted = sessionStorage.getItem(SESSION_KEY);
    if (!accepted) {
      // Small delay for better UX
      const t = setTimeout(() => setOpen(true), 800);
      return () => clearTimeout(t);
    } else {
      setBannerVisible(true);
    }
  }, []);

  const handleAccept = () => {
    sessionStorage.setItem(SESSION_KEY, 'true');
    setOpen(false);
    setBannerVisible(true);
  };

  return (
    <>
      {/* ─── First-visit modal ─── */}
      <Dialog
        open={open}
        TransitionComponent={Transition}
        keepMounted
        maxWidth="sm"
        fullWidth
        PaperProps={{
          sx: {
            bgcolor: 'rgba(10, 15, 30, 0.98)',
            border: '1px solid rgba(251, 191, 36, 0.4)',
            borderRadius: 3,
            backdropFilter: 'blur(20px)',
          },
        }}
      >
        <DialogTitle sx={{ pb: 1, display: 'flex', alignItems: 'center', gap: 1.5 }}>
          <Box sx={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            width: 40, height: 40, borderRadius: '50%',
            bgcolor: 'rgba(251, 191, 36, 0.15)',
            border: '1px solid rgba(251, 191, 36, 0.4)',
          }}>
            <Warning sx={{ color: '#fbbf24', fontSize: 22 }} />
          </Box>
          <Box>
            <Typography variant="subtitle1" sx={{ fontWeight: 800, lineHeight: 1 }}>
              Aviso Importante — ATOM Platform
            </Typography>
            <Typography variant="caption" color="text.secondary">
              Leia antes de continuar
            </Typography>
          </Box>
        </DialogTitle>

        <DialogContent sx={{ pt: 0 }}>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <Box sx={{ p: 2, bgcolor: 'rgba(251,191,36,0.05)', borderRadius: 2, border: '1px solid rgba(251,191,36,0.2)' }}>
              <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.7 }}>
                O <strong>ATOM</strong> é uma plataforma de análise quantitativa para fins educacionais e informativos.
                Os relatórios, sinais, modelos de risco e recomendações gerados <strong>não constituem recomendações de investimento</strong>,
                assessoria financeira, ou oferta de valores mobiliários.
              </Typography>
            </Box>

            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
              <Chip icon={<Shield sx={{ fontSize: 14 }} />} label="Ferramenta Educacional" size="small" sx={{ bgcolor: 'rgba(99,102,241,0.15)', color: '#818cf8' }} />
              <Chip icon={<TrendingUp sx={{ fontSize: 14 }} />} label="Modelos Estatísticos" size="small" sx={{ bgcolor: 'rgba(34,197,94,0.15)', color: '#4ade80' }} />
              <Chip icon={<Warning sx={{ fontSize: 14 }} />} label="Não Regulamentado CVM" size="small" sx={{ bgcolor: 'rgba(251,191,36,0.15)', color: '#fbbf24' }} />
            </Box>

            <Typography variant="caption" color="text.secondary" sx={{ lineHeight: 1.6 }}>
              Resultados passados não garantem resultados futuros. Opções e derivativos envolvem alto risco de perda.
              Utilize as análises como suporte à sua própria decisão, sempre consultando um profissional certificado (AAI/CFP) para
              estratégias de investimento personalizado.
            </Typography>

            <Button
              id="disclaimer-accept-btn"
              fullWidth
              variant="contained"
              onClick={handleAccept}
              sx={{
                py: 1.5, fontWeight: 800,
                background: 'linear-gradient(135deg, #6366f1, #818cf8)',
                boxShadow: '0 4px 20px rgba(99,102,241,0.4)',
                mt: 1,
              }}
            >
              Li e Entendi — Acessar Plataforma
            </Button>
          </Box>
        </DialogContent>
      </Dialog>

      {/* ─── Sticky mini-banner after acceptance ─── */}
      {bannerVisible && (
        <Box sx={{
          position: 'fixed',
          bottom: 0, left: 0, right: 0,
          zIndex: 9999,
          bgcolor: 'rgba(10, 15, 30, 0.95)',
          borderTop: '1px solid rgba(251, 191, 36, 0.25)',
          px: 2, py: 0.75,
          display: 'flex', alignItems: 'center', gap: 1,
          backdropFilter: 'blur(10px)',
        }}>
          <Warning sx={{ fontSize: 14, color: '#fbbf24', flexShrink: 0 }} />
          <Typography variant="caption" color="text.secondary" sx={{ flexGrow: 1 }}>
            <strong style={{ color: '#fbbf24' }}>Aviso:</strong>{' '}
            ATOM é uma ferramenta de análise quantitativa baseada em IA. Não constitui recomendação de investimento registrada (CVM/SEC).
            Use com responsabilidade.
          </Typography>
          <IconButton size="small" onClick={() => setBannerVisible(false)} sx={{ color: 'text.disabled' }}>
            <Close sx={{ fontSize: 14 }} />
          </IconButton>
        </Box>
      )}
    </>
  );
}
