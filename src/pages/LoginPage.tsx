import React, { useState } from 'react';
import {
  Box, Card, CardContent, Tabs, Tab, TextField, Button,
  Typography, Alert, CircularProgress, InputAdornment, IconButton,
} from '@mui/material';
import { Visibility, VisibilityOff, Lock, Person, Email } from '@mui/icons-material';
import { useAuth } from '../contexts/AuthContext';
import { useNavigate } from 'react-router-dom';

export default function LoginPage() {
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const [tab, setTab] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [showPwd, setShowPwd] = useState(false);
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (!username || !password) { setError('Preencha todos os campos.'); return; }
    if (tab === 1 && !email) { setError('E-mail é obrigatório para cadastro.'); return; }
    setLoading(true);
    try {
      if (tab === 0) await login(username, password);
      else await register(username, email, password);
      navigate('/dashboard');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Erro desconhecido.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box
      id="conteudo-principal"
      sx={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        p: 2,
        backgroundImage: `
          radial-gradient(ellipse 70% 50% at 50% -10%, var(--atom-accent-muted), transparent 55%),
          linear-gradient(var(--atom-grid) 1px, transparent 1px),
          linear-gradient(90deg, var(--atom-grid) 1px, transparent 1px)
        `,
        backgroundSize: 'auto, 48px 48px, 48px 48px',
      }}
    >
      <Card sx={{ width: '100%', maxWidth: 440 }}>
        <CardContent sx={{ p: { xs: 3, sm: 4 } }}>
          <Box sx={{ textAlign: 'center', mb: 3 }}>
            <Box
              component="img"
              src="/atom.svg"
              alt=""
              sx={{ width: 48, height: 48, mb: 1.5, filter: 'drop-shadow(0 0 16px var(--atom-accent-glow))' }}
            />
            <Typography variant="h5" sx={{ fontWeight: 700, letterSpacing: '-0.03em' }}>
              ATOM
            </Typography>
            <Typography variant="caption" color="text.secondary" sx={{ letterSpacing: '0.12em', textTransform: 'uppercase' }}>
              Mesa de pesquisa quantitativa
            </Typography>
          </Box>

          <Tabs
            value={tab}
            onChange={(_, v) => { setTab(v); setError(''); }}
            variant="fullWidth"
            sx={{ mb: 3 }}
          >
            <Tab label="Entrar" id="tab-login" />
            <Tab label="Criar Conta" id="tab-register" />
          </Tabs>

          <Box component="form" onSubmit={handleSubmit}>
            <TextField
              id="login-username"
              fullWidth
              label="Usuário"
              value={username}
              onChange={e => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
              sx={{ mb: 2 }}
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start">
                    <Person sx={{ fontSize: 18, color: 'text.secondary' }} />
                  </InputAdornment>
                ),
              }}
            />

            {tab === 1 && (
              <TextField
                id="register-email"
                fullWidth
                label="E-mail"
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                autoComplete="email"
                sx={{ mb: 2 }}
                InputProps={{
                  startAdornment: (
                    <InputAdornment position="start">
                      <Email sx={{ fontSize: 18, color: 'text.secondary' }} />
                    </InputAdornment>
                  ),
                }}
              />
            )}

            <TextField
              id="login-password"
              fullWidth
              label="Senha"
              type={showPwd ? 'text' : 'password'}
              value={password}
              onChange={e => setPassword(e.target.value)}
              autoComplete={tab === 0 ? 'current-password' : 'new-password'}
              sx={{ mb: 3 }}
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start">
                    <Lock sx={{ fontSize: 18, color: 'text.secondary' }} />
                  </InputAdornment>
                ),
                endAdornment: (
                  <InputAdornment position="end">
                    <IconButton
                      size="small"
                      onClick={() => setShowPwd(!showPwd)}
                      edge="end"
                      aria-label={showPwd ? 'Ocultar senha' : 'Mostrar senha'}
                    >
                      {showPwd ? <VisibilityOff sx={{ fontSize: 18 }} /> : <Visibility sx={{ fontSize: 18 }} />}
                    </IconButton>
                  </InputAdornment>
                ),
              }}
            />

            {error && (
              <Alert severity="error" sx={{ mb: 2 }}>
                {error}
              </Alert>
            )}

            <Button
              id="login-submit-btn"
              type="submit"
              fullWidth
              variant="contained"
              disabled={loading}
              sx={{ py: 1.25 }}
            >
              {loading
                ? <CircularProgress size={20} sx={{ color: 'inherit' }} />
                : tab === 0 ? 'Entrar na mesa' : 'Criar conta'}
            </Button>
          </Box>

          <Box
            sx={{
              mt: 3,
              p: 2,
              borderRadius: 'var(--atom-radius-sm)',
              border: '1px solid',
              borderColor: 'divider',
              bgcolor: 'var(--atom-accent-muted)',
            }}
          >
            <Typography variant="caption" color="text.secondary" sx={{ lineHeight: 1.6, display: 'block' }}>
              ATOM é um piloto de pesquisa quantitativa. Não constitui recomendação de investimento
              registrada na CVM ou SEC e não executa operações na corretora.
            </Typography>
          </Box>
        </CardContent>
      </Card>
    </Box>
  );
}
