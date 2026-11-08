import React, { useState, useEffect } from 'react';
import {
  Box, Button, Dialog, DialogContent, DialogTitle,
  Typography, Chip, IconButton, Slide,
} from '@mui/material';
import { TransitionProps } from '@mui/material/transitions';
import { Warning, Close, Shield } from '@mui/icons-material';

const SESSION_KEY = 'atom_disclaimer_accepted';

const Transition = React.forwardRef(function Transition(
  props: TransitionProps & { children: React.ReactElement },
  ref: React.Ref<unknown>,
) {
  return <Slide direction="up" ref={ref} {...props} />;
});

export default function DisclaimerBanner() {
  const [open, setOpen] = useState(false);
  const [bannerVisible, setBannerVisible] = useState(false);

  useEffect(() => {
    const accepted = localStorage.getItem(SESSION_KEY);
    if (!accepted) {
      const t = setTimeout(() => setOpen(true), 800);
      return () => clearTimeout(t);
    }
    setBannerVisible(true);
  }, []);

  const handleAccept = () => {
    localStorage.setItem(SESSION_KEY, 'true');
    setOpen(false);
    setBannerVisible(true);
  };

  return (
    <>
      <Dialog
        open={open}
        TransitionComponent={Transition}
        keepMounted
        maxWidth="sm"
        fullWidth
        PaperProps={{
          sx: {
            bgcolor: 'background.paper',
            border: '1px solid',
            borderColor: 'divider',
            backgroundImage: 'none',
          },
        }}
      >
        <DialogTitle sx={{ pb: 1, display: 'flex', alignItems: 'center', gap: 1.5 }}>
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: 40,
              height: 40,
              borderRadius: '10px',
              bgcolor: 'var(--atom-accent-muted)',
              border: '1px solid',
              borderColor: 'divider',
              color: 'warning.main',
            }}
          >
            <Warning sx={{ fontSize: 22 }} />
          </Box>
          <Box>
            <Typography variant="subtitle1" sx={{ fontWeight: 700, lineHeight: 1.2 }}>
              Aviso — ATOM Research
            </Typography>
            <Typography variant="caption" color="text.secondary">
              Leia antes de continuar
            </Typography>
          </Box>
        </DialogTitle>

        <DialogContent sx={{ pt: 0 }}>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.7 }}>
              O <strong>ATOM</strong> é um piloto de pesquisa quantitativa. Sinais, preços e “recomendações”
              são cenários teóricos: <strong>não autorizam execução</strong>, não são assessoria e não passam pelo
              protocolo de evidência do Laboratório Quant.
            </Typography>

            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
              <Chip icon={<Shield sx={{ fontSize: 14 }} />} label="Pesquisa, não execução" size="small" />
              <Chip icon={<Warning sx={{ fontSize: 14 }} />} label="Sem corretora" size="small" />
            </Box>

            <Typography variant="caption" color="text.secondary" sx={{ lineHeight: 1.6 }}>
              Resultados de pesquisa não demonstram rentabilidade futura. Opções e derivativos envolvem risco de perda.
              Use as análises como suporte à sua própria decisão.
            </Typography>

            <Button
              id="disclaimer-accept-btn"
              fullWidth
              variant="contained"
              onClick={handleAccept}
              sx={{ py: 1.25, mt: 1 }}
            >
              Li e entendi — continuar
            </Button>
          </Box>
        </DialogContent>
      </Dialog>

      {bannerVisible && (
        <Box
          sx={{
            position: 'fixed',
            bottom: 0,
            left: 0,
            right: 0,
            zIndex: 9999,
            bgcolor: 'color-mix(in srgb, var(--atom-bg-elevated) 92%, transparent)',
            borderTop: '1px solid',
            borderColor: 'divider',
            px: 2,
            py: 0.75,
            display: 'flex',
            alignItems: 'center',
            gap: 1,
            backdropFilter: 'blur(12px)',
          }}
        >
          <Warning sx={{ fontSize: 14, color: 'warning.main', flexShrink: 0 }} />
          <Typography variant="caption" color="text.secondary" sx={{ flexGrow: 1 }}>
            <strong>Aviso:</strong> ATOM é pesquisa quantitativa. Não constitui recomendação de investimento
            (CVM/SEC) e não executa operações na corretora.
          </Typography>
          <IconButton size="small" onClick={() => setBannerVisible(false)} aria-label="Fechar aviso" sx={{ color: 'text.secondary' }}>
            <Close sx={{ fontSize: 14 }} />
          </IconButton>
        </Box>
      )}
    </>
  );
}
