import React, { useState } from 'react';
import {
  Box, Card, CardContent, Tabs, Tab, TextField, Button,
  Typography, Alert, CircularProgress, InputAdornment, IconButton,
} from '@mui/material';
import { Visibility, VisibilityOff, AutoGraph, Lock, Person, Email } from '@mui/icons-material';
import { useAuth } from '../contexts/AuthContext';
import { useNavigate } from 'react-router-dom';

export default function LoginPage() {
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const [tab, setTab] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [showPwd, setShowPwd] = useState(false);

  // Form state
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
    } catch (err: any) {
      setError(err.message || 'Erro desconhecido.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box sx={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'linear-gradient(135deg, #0a0f1e 0%, #0d1929 50%, #0a1628 100%)',
      p: 2,
    }}>
      {/* Decorative glow */}
      <Box sx={{
        position: 'fixed', top: '20%', left: '50%', transform: 'translateX(-50%)',
        width: 600, height: 300,
        background: 'radial-gradient(ellipse, rgba(99,102,241,0.15) 0%, transparent 70%)',
        pointerEvents: 'none',
      }} />

      <Card sx={{
        width: '100%', maxWidth: 440,
        bgcolor: 'rgba(13,25,42,0.95)',
        border: '1px solid rgba(99,102,241,0.3)',
        backdropFilter: 'blur(20px)',
        borderRadius: 3,
        boxShadow: '0 25px 80px rgba(0,0,0,0.6)',
      }}>
        <CardContent sx={{ p: 4 }}>
          {/* Logo */}
          <Box sx={{ textAlign: 'center', mb: 4 }}>
            <Box sx={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              width: 64, height: 64, borderRadius: '50%',
              background: 'linear-gradient(135deg, #6366f1, #818cf8)',
              mb: 2, boxShadow: '0 0 30px rgba(99,102,241,0.5)',
            }}>
              <AutoGraph sx={{ fontSize: 32, color: '#fff' }} />
            </Box>
            <Typography variant="h5" sx={{ fontWeight: 800, letterSpacing: '-0.02em' }}>
              ATOM
            </Typography>
            <Typography variant="caption" color="text.secondary">
              Quantitative Finance Platform
            </Typography>
          </Box>

          <Tabs
            value={tab}
            onChange={(_, v) => { setTab(v); setError(''); }}
            variant="fullWidth"
            sx={{
              mb: 3,
              '& .MuiTab-root': { fontWeight: 700, fontSize: '0.8rem' },
              '& .MuiTabs-indicator': { bgcolor: 'primary.main', height: 3, borderRadius: 2 },
            }}
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
              size="small"
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
                size="small"
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
              size="small"
              sx={{ mb: 3 }}
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start">
                    <Lock sx={{ fontSize: 18, color: 'text.secondary' }} />
                  </InputAdornment>
                ),
                endAdornment: (
                  <InputAdornment position="end">
                    <IconButton size="small" onClick={() => setShowPwd(!showPwd)} edge="end">
                      {showPwd ? <VisibilityOff sx={{ fontSize: 18 }} /> : <Visibility sx={{ fontSize: 18 }} />}
                    </IconButton>
                  </InputAdornment>
                ),
              }}
            />

            {error && (
              <Alert severity="error" sx={{ mb: 2, py: 0.5, fontSize: '0.8rem' }}>
                {error}
              </Alert>
            )}

            <Button
              id="login-submit-btn"
              type="submit"
              fullWidth
              variant="contained"
              disabled={loading}
              sx={{
                py: 1.5, fontWeight: 800, fontSize: '0.9rem',
                background: 'linear-gradient(135deg, #6366f1, #818cf8)',
                boxShadow: '0 4px 20px rgba(99,102,241,0.4)',
                '&:hover': { boxShadow: '0 6px 30px rgba(99,102,241,0.6)' },
              }}
            >
              {loading
                ? <CircularProgress size={20} sx={{ color: '#fff' }} />
                : tab === 0 ? 'Entrar na Plataforma' : 'Criar Conta'}
            </Button>
          </Box>

          <Box sx={{ mt: 3, p: 2, bgcolor: 'rgba(99,102,241,0.05)', borderRadius: 2, border: '1px solid rgba(99,102,241,0.2)' }}>
            <Typography variant="caption" color="text.secondary" sx={{ lineHeight: 1.5, display: 'block' }}>
              ⚠️ <strong>Nota Legal:</strong> ATOM é uma ferramenta de análise quantitativa baseada em IA e modelos estatísticos. 
              Não constitui recomendação de investimento registrada na CVM ou SEC.
            </Typography>
          </Box>
        </CardContent>
      </Card>
    </Box>
  );
}
