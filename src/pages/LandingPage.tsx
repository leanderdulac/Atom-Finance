import { useNavigate } from 'react-router-dom';
import { Box, Button, Card, CardContent, Chip, Container, Stack, Typography } from '@mui/material';
import { Assessment, Science, MenuBook, ShowChart } from '@mui/icons-material';
import { useClientConfig } from '../contexts/ClientModeContext';

export default function LandingPage() {
  const navigate = useNavigate();
  const { client_mode } = useClientConfig();

  if (client_mode) {
    return (
      <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
        <Container maxWidth="lg">
          <Stack component="header" direction="row" justifyContent="space-between" alignItems="center" sx={{ py: 3, borderBottom: 1, borderColor: 'divider' }}>
            <Typography variant="h6" fontWeight={800}>ATOM <Box component="span" sx={{ color: 'text.secondary', fontWeight: 400 }}>Cliente</Box></Typography>
            <Button onClick={() => navigate('/login')}>Entrar</Button>
          </Stack>
          <Box component="main" sx={{ py: { xs: 6, md: 10 } }}>
            <Chip label="Simulação paper · sem ordens reais · sem promessa de retorno" sx={{ mb: 3, maxWidth: '100%', height: 'auto', '& .MuiChip-label': { whiteSpace: 'normal', py: 1 } }} />
            <Typography component="h1" sx={{ fontWeight: 750, fontSize: { xs: '2.4rem', md: '4rem' }, lineHeight: 1.08, letterSpacing: '-0.04em', maxWidth: 900 }}>
              Três escolhas. A operação vem pronta.
            </Typography>
            <Typography sx={{ fontSize: '1.2rem', color: 'text.secondary', maxWidth: 690, mt: 3 }}>
              Você escolhe o ativo, se opera à vista, opção ou futuro, e o tempo.
              O arsenal da mesa monta entrada, stop, alvo e tamanho — ou diz que não tem dado suficiente.
              Isto é cenário, não recomendação.
            </Typography>
            <Stack direction="row" spacing={2} useFlexGap flexWrap="wrap" sx={{ mt: 4 }}>
              <Button size="large" variant="contained" onClick={() => navigate('/login')}>Começar</Button>
              <Button size="large" variant="outlined" onClick={() => navigate('/login')}>Já tenho conta</Button>
            </Stack>
            <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(3, 1fr)' }, gap: 3, mt: 8 }}>
              {[
                { icon: <ShowChart />, title: '01 · Ativo', text: 'PETR4, VALE3, Bitcoin, Ethereum — as fontes que o ATOM já usa, sem inventar preço.' },
                { icon: <Science />, title: '02 · Instrumento', text: 'À vista, opção (se houver livro) ou futuro/perpétuo em cripto. Só o que o arsenal cobre.' },
                { icon: <Assessment />, title: '03 · Tempo', text: 'Dias, semanas ou meses. O restante — regime, volatilidade, risco — corre sozinho.' },
              ].map((item) => (
                <Card key={item.title} variant="outlined">
                  <CardContent sx={{ p: 3 }}>
                    {item.icon}
                    <Typography variant="h6" sx={{ mt: 2 }}>{item.title}</Typography>
                    <Typography color="text.secondary" sx={{ mt: 1 }}>{item.text}</Typography>
                  </CardContent>
                </Card>
              ))}
            </Box>
            <Box sx={{ mt: 6, borderTop: 1, borderColor: 'divider', pt: 3 }}>
              <Typography variant="h6">Paper trading. Sem corretora, sem ordem real.</Typography>
              <Typography color="text.secondary" sx={{ mt: 1 }}>
                Quando o arsenal não tem dado ou sinal, a tela diz isso. Nada aqui autoriza capital.
              </Typography>
            </Box>
          </Box>
        </Container>
      </Box>
    );
  }

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
      <Container maxWidth="lg">
        <Stack component="header" direction="row" justifyContent="space-between" alignItems="center" sx={{ py: 3, borderBottom: 1, borderColor: 'divider' }}>
          <Typography variant="h6" fontWeight={800}>ATOM <Box component="span" sx={{ color: 'text.secondary', fontWeight: 400 }}>Research</Box></Typography>
          <Button onClick={() => navigate('/login')}>Entrar</Button>
        </Stack>
        <Box component="main" sx={{ py: { xs: 6, md: 10 } }}>
          <Chip label="Pesquisa quantitativa para ações brasileiras · piloto local" sx={{ mb: 3, maxWidth: '100%', height: 'auto', '& .MuiChip-label': { whiteSpace: 'normal', py: 1 } }} />
          <Typography component="h1" sx={{ fontWeight: 750, fontSize: { xs: '2.6rem', md: '4.5rem' }, lineHeight: 1.08, letterSpacing: '-0.04em', maxWidth: 880 }}>Uma boa hipótese merece um teste rigoroso.</Typography>
          <Typography sx={{ fontSize: '1.2rem', color: 'text.secondary', maxWidth: 690, mt: 3 }}>Compare modelos com alternativas simples, veja o resultado após custos e preserve a evidência por trás de cada decisão de pesquisa.</Typography>
          <Stack direction="row" spacing={2} useFlexGap flexWrap="wrap" sx={{ mt: 4 }}>
            <Button size="large" variant="contained" onClick={() => navigate('/ml')}>Criar meu primeiro experimento</Button>
            <Button size="large" variant="outlined" onClick={() => navigate('/dashboard')}>Abrir diário de pesquisa</Button>
          </Stack>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>O laboratório inclui uma demonstração com dados sintéticos, identificada em todo o processo.</Typography>
          <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(3, 1fr)' }, gap: 3, mt: 8 }}>
            {[
              { icon: <MenuBook />, title: '01 · Formule', text: 'Organize artigos com o QuantMind e escreva a hipótese econômica que deseja colocar à prova. A extração de artigos depende da configuração do serviço de IA.' },
              { icon: <Science />, title: '02 · Confronte', text: 'Avalie janelas temporais com purga, baselines, custos, turnover e drawdown. Ridge e Random Forest disputam espaço com modelos simples.' },
              { icon: <Assessment />, title: '03 · Registre', text: 'Guarde dados, premissas, resultados e tentativas que falharam. Exporte o registro e documente por que investigar ou descartar uma hipótese.' },
            ].map((item) => (
              <Card key={item.title} variant="outlined">
                <CardContent sx={{ p: 3 }}>
                  {item.icon}
                  <Typography variant="h6" sx={{ mt: 2 }}>{item.title}</Typography>
                  <Typography color="text.secondary" sx={{ mt: 1 }}>{item.text}</Typography>
                </CardContent>
              </Card>
            ))}
          </Box>
          <Box sx={{ mt: 6, borderTop: 1, borderColor: 'divider', pt: 3 }}>
            <Typography variant="h6">Feito para pesquisadores e analistas que precisam explicar seus resultados.</Typography>
            <Typography color="text.secondary" sx={{ mt: 1 }}>O ATOM está em piloto. A avaliação depende da qualidade dos dados e ainda exige validação independente. Resultados de pesquisa não demonstram rentabilidade futura; o produto não executa operações na corretora.</Typography>
          </Box>
        </Box>
      </Container>
    </Box>
  );
}
