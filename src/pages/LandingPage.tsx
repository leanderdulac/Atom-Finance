import { useNavigate } from 'react-router-dom';
import {
  Box, Button, Card, CardContent, Chip, Container, Stack, Typography,
} from '@mui/material';
import {
  AccountTree, AutoGraph, Layers, Science, ShowChart, Timeline, WarningAmber,
} from '@mui/icons-material';

const families = [
  {
    kicker: '01',
    icon: <Timeline fontSize="small" />,
    title: 'Stat arb e cointegração',
    paper: 'Engle–Granger · Johansen',
    text: 'Pares e painéis com residual, z expanding e fill em t+1. Cointegração descreve uma relação estatística — não autoriza uma posição.',
  },
  {
    kicker: '02',
    icon: <AutoGraph fontSize="small" />,
    title: 'Market making Avellaneda–Stoikov',
    paper: 'Avellaneda & Stoikov 2008',
    text: 'Preço de reserva e spread ótimo com inventário. Demonstração de microestrutura, sem book real e sem envio de ordens.',
  },
  {
    kicker: '03',
    icon: <ShowChart fontSize="small" />,
    title: 'Heston e derivativos',
    paper: 'Heston 1993',
    text: 'Preço europeu pela função característica, calibração de smile e mesa de opções. Pesquisa sobre o modelo, não execução na corretora.',
  },
  {
    kicker: '04',
    icon: <WarningAmber fontSize="small" />,
    title: 'Regimes',
    paper: 'Estado, não print',
    text: 'Isolar o regime e redimensionar a pesquisa. Flatten no paper no último mark. Nunca no broker.',
  },
  {
    kicker: '05',
    icon: <Science fontSize="small" />,
    title: 'EVT e cisne negro',
    paper: 'Hill · GPD',
    text: 'Cauda, Hill e perdas extremas sobre a série que você carrega. Um score alto descreve a amostra — não prevê o próximo crash.',
  },
];

const layers = [
  { n: '01', title: 'Premissas e dados', text: 'Hipótese escrita, fonte, custos, hashes. Nada entra no cálculo sem rastreio.' },
  { n: '02', title: 'Famílias de modelos', text: 'Implementações from-scratch das famílias acima, cada uma com o que quebrou.' },
  { n: '03', title: 'Harness de evidência', text: 'Walk-forward purgado, baselines, custos e o relógio sequencial. Backtest é pesquisa, não prova.' },
  { n: '04', title: 'Diário e paper-trading', text: 'Registrar falhas, decidir investigar ou descartar, acompanhar planos à mão.' },
  { n: '05', title: 'Sem execução ao vivo', text: 'eligible_for_live_trading é sempre falso. ATOM não envia ordens.' },
];

function AtomMark({ size = 28 }: { size?: number }) {
  return (
    <Box
      component="img"
      src="/atom.svg"
      alt=""
      sx={{
        width: size,
        height: size,
        filter: 'drop-shadow(0 0 12px var(--atom-accent-glow))',
      }}
    />
  );
}

export default function LandingPage() {
  const navigate = useNavigate();

  return (
    <Box
      sx={{
        minHeight: '100vh',
        bgcolor: 'background.default',
        color: 'text.primary',
        position: 'relative',
        overflow: 'clip',
        backgroundImage: `
          radial-gradient(ellipse 80% 50% at 50% -10%, var(--atom-accent-muted), transparent 60%),
          linear-gradient(var(--atom-grid) 1px, transparent 1px),
          linear-gradient(90deg, var(--atom-grid) 1px, transparent 1px)
        `,
        backgroundSize: 'auto, 48px 48px, 48px 48px',
      }}
    >
      <Box
        component="header"
        sx={{
          position: 'sticky',
          top: 0,
          zIndex: 20,
          backdropFilter: 'blur(16px)',
          bgcolor: 'color-mix(in srgb, var(--atom-bg) 78%, transparent)',
          borderBottom: '1px solid',
          borderColor: 'divider',
        }}
      >
        <Container maxWidth="lg">
          <Stack direction="row" alignItems="center" spacing={2} sx={{ py: 1.5, flexWrap: 'nowrap' }}>
            <Stack direction="row" alignItems="center" spacing={1.25} sx={{ minWidth: 0 }}>
              <AtomMark />
              <Typography variant="h6" sx={{ fontWeight: 700, letterSpacing: '-0.03em' }}>
                ATOM
              </Typography>
              <Typography
                variant="caption"
                sx={{
                  color: 'text.secondary',
                  letterSpacing: '0.16em',
                  textTransform: 'uppercase',
                  fontWeight: 600,
                  display: { xs: 'none', sm: 'block' },
                }}
              >
                Research
              </Typography>
            </Stack>
            <Box sx={{ flexGrow: 1 }} />
            <Stack
              direction="row"
              spacing={0.5}
              component="nav"
              aria-label="Secções da landing"
              sx={{ display: { xs: 'none', md: 'flex' } }}
            >
              {[
                { href: '#familias', label: 'Famílias' },
                { href: '#como-funciona', label: 'Como funciona' },
              ].map((item) => (
                <Button key={item.href} href={item.href} color="inherit" size="small">
                  {item.label}
                </Button>
              ))}
            </Stack>
            <Button variant="outlined" onClick={() => navigate('/login')}>
              Entrar
            </Button>
          </Stack>
        </Container>
      </Box>

      <Container maxWidth="lg" component="main" id="conteudo-principal">
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', lg: '1.15fr 0.85fr' },
            gap: { xs: 5, lg: 8 },
            alignItems: 'center',
            py: { xs: 7, md: 12 },
          }}
        >
          <Box>
            <Chip
              label="Pesquisa quantitativa · piloto · paper-trading primeiro"
              sx={{
                mb: 3,
                maxWidth: '100%',
                height: 'auto',
                '& .MuiChip-label': { whiteSpace: 'normal', py: 0.75 },
              }}
            />
            <Typography
              component="h1"
              sx={{
                fontWeight: 700,
                fontSize: { xs: '2.4rem', sm: '3.25rem', md: '4.15rem' },
                lineHeight: 1.05,
                letterSpacing: '-0.045em',
                maxWidth: 720,
              }}
            >
              Mesa de pesquisa quantitativa.
            </Typography>
            <Typography
              sx={{
                fontSize: { xs: '1.05rem', md: '1.2rem' },
                color: 'text.secondary',
                maxWidth: 560,
                mt: 3,
              }}
            >
              ATOM é um desk de pesquisa: hipóteses, modelos e evidência — não uma corretora.
              Paper-trading primeiro. Sem execução ao vivo, sem promessa de retorno.
            </Typography>
            <Stack direction="row" spacing={1.5} useFlexGap flexWrap="wrap" sx={{ mt: 4 }}>
              <Button size="large" variant="contained" onClick={() => navigate('/login')}>
                Entrar na mesa
              </Button>
              <Button size="large" variant="outlined" onClick={() => navigate('/login')}>
                Abrir o desk
              </Button>
            </Stack>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
              O laboratório inclui uma demonstração com dados sintéticos, identificada em todo o processo.
            </Typography>
          </Box>

          <Card
            aria-hidden
            sx={{
              display: { xs: 'none', lg: 'block' },
              p: 0.5,
              background:
                'linear-gradient(180deg, color-mix(in srgb, var(--atom-accent) 18%, transparent), transparent 40%), var(--atom-surface)',
            }}
          >
            <CardContent sx={{ p: 3 }}>
              <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
                <Typography variant="overline">Harness · demonstração</Typography>
                <Chip size="small" label="paper only" />
              </Stack>
              {[
                ['Walk-forward', 'purga + embargo'],
                ['Fill', 't+1, nunca t'],
                ['Custos', 'comissão + slippage'],
                ['Execução', '0 ordens no broker'],
              ].map(([k, v]) => (
                <Stack
                  key={k}
                  direction="row"
                  justifyContent="space-between"
                  sx={{
                    py: 1.25,
                    borderBottom: '1px solid',
                    borderColor: 'divider',
                    fontFamily: 'var(--atom-font-mono)',
                    fontSize: '0.82rem',
                  }}
                >
                  <Box component="span" sx={{ color: 'text.secondary' }}>{k}</Box>
                  <Box component="span" sx={{ color: 'primary.main' }}>{v}</Box>
                </Stack>
              ))}
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 2 }}>
                Métricas de pesquisa, não de performance comercial.
              </Typography>
            </CardContent>
          </Card>
        </Box>

        <Box id="familias" sx={{ py: { xs: 6, md: 10 } }}>
          <Typography variant="overline" sx={{ color: 'primary.main' }}>
            Famílias de modelos
          </Typography>
          <Typography variant="h4" component="h2" sx={{ mt: 1, mb: 1, maxWidth: 640 }}>
            O mesmo desk, cinco linhas de pesquisa.
          </Typography>
          <Typography color="text.secondary" sx={{ mb: 4, maxWidth: 560 }}>
            Cada família vive no harness: premissas explícitas, o que quebrou, e nenhuma autorização de execução.
          </Typography>
          <Box
            sx={{
              display: 'grid',
              gridTemplateColumns: { xs: '1fr', md: 'repeat(2, 1fr)', lg: 'repeat(3, 1fr)' },
              gap: 2.5,
            }}
          >
            {families.map((item) => (
              <Card key={item.title} sx={{ height: '100%' }}>
                <CardContent sx={{ p: 3, height: '100%', display: 'flex', flexDirection: 'column' }}>
                  <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 2 }}>
                    <Box
                      sx={{
                        width: 36,
                        height: 36,
                        borderRadius: '10px',
                        display: 'grid',
                        placeItems: 'center',
                        bgcolor: 'var(--atom-accent-muted)',
                        color: 'primary.main',
                        border: '1px solid',
                        borderColor: 'divider',
                      }}
                    >
                      {item.icon}
                    </Box>
                    <Typography variant="overline">{item.kicker}</Typography>
                  </Stack>
                  <Typography variant="h6" sx={{ mb: 0.5 }}>{item.title}</Typography>
                  <Typography variant="caption" sx={{ color: 'primary.main', fontFamily: 'var(--atom-font-mono)', mb: 1.5 }}>
                    {item.paper}
                  </Typography>
                  <Typography color="text.secondary">{item.text}</Typography>
                </CardContent>
              </Card>
            ))}
          </Box>
        </Box>

        <Box id="como-funciona" sx={{ py: { xs: 6, md: 10 } }}>
          <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 1 }}>
            <Layers sx={{ color: 'primary.main' }} />
            <Typography variant="overline" sx={{ color: 'primary.main' }}>Como funciona</Typography>
          </Stack>
          <Typography variant="h4" component="h2" sx={{ mb: 1, maxWidth: 640 }}>
            Um harness em camadas, não um botão de operar.
          </Typography>
          <Typography color="text.secondary" sx={{ mb: 4, maxWidth: 560 }}>
            Da hipótese ao diário. A última camada é a recusa: o produto não executa na corretora.
          </Typography>
          <Box
            sx={{
              display: 'grid',
              gridTemplateColumns: { xs: '1fr', md: 'repeat(5, 1fr)' },
              gap: 1.5,
            }}
          >
            {layers.map((layer, i) => (
              <Box
                key={layer.n}
                sx={{
                  p: 2.5,
                  borderRadius: 'var(--atom-radius-md)',
                  border: '1px solid',
                  borderColor: i === layers.length - 1 ? 'var(--atom-accent)' : 'divider',
                  background:
                    i === layers.length - 1
                      ? 'var(--atom-accent-muted)'
                      : 'linear-gradient(180deg, var(--atom-surface), var(--atom-bg-elevated))',
                  minHeight: 180,
                }}
              >
                <Typography
                  sx={{
                    fontFamily: 'var(--atom-font-mono)',
                    color: 'primary.main',
                    fontSize: '0.75rem',
                    mb: 1.5,
                  }}
                >
                  {layer.n}
                </Typography>
                <Typography variant="subtitle1" sx={{ mb: 1, fontWeight: 600 }}>
                  {layer.title}
                </Typography>
                <Typography variant="body2">{layer.text}</Typography>
              </Box>
            ))}
          </Box>
        </Box>

        <Box
          sx={{
            my: { xs: 4, md: 8 },
            p: { xs: 3, md: 6 },
            borderRadius: 'var(--atom-radius-lg)',
            border: '1px solid',
            borderColor: 'divider',
            background:
              'radial-gradient(ellipse at top left, var(--atom-accent-muted), transparent 55%), var(--atom-surface)',
            textAlign: { xs: 'left', md: 'center' },
          }}
        >
          <AccountTree sx={{ color: 'primary.main', mb: 2 }} />
          <Typography variant="h4" component="h2" sx={{ mb: 1.5 }}>
            Feito para quem precisa explicar o resultado.
          </Typography>
          <Typography color="text.secondary" sx={{ maxWidth: 640, mx: { md: 'auto' }, mb: 3 }}>
            ATOM está em piloto. A avaliação depende da qualidade dos dados e ainda exige validação independente.
            Resultados de pesquisa não demonstram rentabilidade futura; o produto não executa operações na corretora.
          </Typography>
          <Stack direction="row" spacing={1.5} useFlexGap flexWrap="wrap" justifyContent={{ md: 'center' }}>
            <Button size="large" variant="contained" onClick={() => navigate('/login')}>
              Entrar na mesa
            </Button>
            <Button size="large" variant="outlined" onClick={() => navigate('/login')}>
              Abrir o desk
            </Button>
          </Stack>
        </Box>

        <Box component="footer" sx={{ py: 4, pb: 10, borderTop: '1px solid', borderColor: 'divider' }}>
          <Typography variant="caption" color="text.secondary">
            ATOM Research · piloto local · pesquisa quantitativa para hipóteses, não para execução.
          </Typography>
        </Box>
      </Container>
    </Box>
  );
}
