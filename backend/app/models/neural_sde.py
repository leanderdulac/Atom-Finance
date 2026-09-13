"""
Neural Stochastic Differential Equations (Neural SDE)
======================================================
Parameterises both drift μ(t,y) and diffusion σ(t,y) with neural networks
and solves the Itô SDE via torchsde.

Scope: this is a demonstration of the numerical method, not a fitted model.
The networks are randomly initialised and never trained — there is no fitting
routine here and no market data enters. Output is a correct integration of a
random SDE, and says nothing about any asset. The applications the literature
puts on Neural SDEs (learned stochastic volatility, rate dynamics, regime
scenario generation) would all require a training loop that does not exist.

Architecture
------------
  dY_t = μ_θ(t, Y_t) dt + σ_φ(t, Y_t) dW_t   (Itô)

  μ_net  : Linear(d,32) → Tanh → Linear(32,d)
  σ_net  : Linear(d,32) → ReLU → Linear(32,d) → Sigmoid   (keeps σ ∈ (0,1))
"""
from __future__ import annotations

import logging

import numpy as np
import torch
import torch.nn as nn

logger = logging.getLogger(__name__)

# torchsde is an optional dependency — fail gracefully so the rest of the app
# keeps working when it is not installed.
try:
    import torchsde  # type: ignore
    _TORCHSDE_AVAILABLE = True
except ImportError:
    _TORCHSDE_AVAILABLE = False
    logger.warning("torchsde not installed. NeuralSDE model will be unavailable.")


_DEVICE = torch.device("cpu")   # ATOM runs on CPU by default


class _SDEFunc(nn.Module):
    """Neural network that defines drift f and diffusion g."""

    noise_type = "diagonal"
    sde_type   = "ito"

    def __init__(self, state_size: int = 1, hidden: int = 32):
        super().__init__()
        self.mu_net = nn.Sequential(
            nn.Linear(state_size, hidden),
            nn.Tanh(),
            nn.Linear(hidden, state_size),
        )
        self.sigma_net = nn.Sequential(
            nn.Linear(state_size, hidden),
            nn.ReLU(),
            nn.Linear(hidden, state_size),
            nn.Sigmoid(),   # constrains σ ∈ (0, 1)
        )

    def f(self, t: torch.Tensor, y: torch.Tensor) -> torch.Tensor:  # drift
        return self.mu_net(y)

    def g(self, t: torch.Tensor, y: torch.Tensor) -> torch.Tensor:  # diffusion
        return self.sigma_net(y)


class NeuralSDE:
    """High-level interface to Neural SDE simulation."""

    @staticmethod
    def is_available() -> bool:
        return _TORCHSDE_AVAILABLE

    @staticmethod
    def simulate(
        y0: float = 0.1,
        t_start: float = 0.0,
        t_end: float = 1.0,
        n_steps: int = 100,
        n_paths: int = 1,
        state_size: int = 1,
        hidden_size: int = 32,
        method: str = "euler",
        seed: int | None = 42,
    ) -> dict:
        """
        Simulate N trajectories of a Neural SDE on CPU.

        Parameters
        ----------
        y0          : Initial state value (scalar, broadcast to all paths).
        t_start     : Start time.
        t_end       : End time.
        n_steps     : Number of time steps.
        n_paths     : Number of independent trajectories (batch size).
        state_size  : Dimensionality of the state space.
        hidden_size : Hidden units in drift / diffusion networks.
        method      : SDE solver — 'euler' (fast) or 'milstein' (higher order).
        seed        : Random seed for reproducibility (None = random).

        Returns
        -------
        dict with keys:
          trajectories  : list[list[float]]  — shape [n_paths × n_steps]
          time          : list[float]
          statistics    : mean, std, min, max per time step
          parameters    : echoed back inputs
        """
        if not _TORCHSDE_AVAILABLE:
            raise RuntimeError(
                "torchsde is required for NeuralSDE. "
                "Install with: pip install torchsde"
            )

        if seed is not None:
            torch.manual_seed(seed)

        sde = _SDEFunc(state_size=state_size, hidden=hidden_size).to(_DEVICE)

        # y0 shape: (batch, state_size)
        y0_tensor = torch.full(
            (n_paths, state_size), fill_value=float(y0), device=_DEVICE
        )
        ts = torch.linspace(t_start, t_end, steps=n_steps, device=_DEVICE)

        with torch.no_grad():
            # trajectories shape: (n_steps, batch, state_size)
            # torchsde is a hard dependency (see requirements.txt); the
            # _TORCHSDE_AVAILABLE guard above is defensive, but the type
            # checker can't correlate that flag with this name's binding.
            trajectories = torchsde.sdeint(sde, y0_tensor, ts, method=method)  # pyright: ignore[reportPossiblyUnboundVariable]

        # Extract first state dimension → (n_steps, n_paths)
        traj_np: np.ndarray = trajectories[:, :, 0].cpu().numpy()  # pyright: ignore[reportCallIssue,reportArgumentType]

        time_list = ts.cpu().numpy().tolist()

        # Per-time-step statistics across paths
        mean_  = traj_np.mean(axis=1).tolist()
        std_   = traj_np.std(axis=1).tolist()
        min_   = traj_np.min(axis=1).tolist()
        max_   = traj_np.max(axis=1).tolist()

        # Return up to 20 paths to keep response size sane
        sample_paths = traj_np[:, : min(n_paths, 20)].T.tolist()

        return {
            "model": "neural_sde",
            "sde_type": "ito",
            "solver": method,
            "trajectories": sample_paths,          # [n_sample_paths][n_steps]
            "time": time_list,
            "statistics": {
                "mean":  [round(v, 6) for v in mean_],
                "std":   [round(v, 6) for v in std_],
                "min":   [round(v, 6) for v in min_],
                "max":   [round(v, 6) for v in max_],
            },
            "terminal": {
                "mean":  round(float(traj_np[-1].mean()), 6),
                "std":   round(float(traj_np[-1].std()),  6),
                "p5":    round(float(np.percentile(traj_np[-1],  5)), 6),
                "p50":   round(float(np.percentile(traj_np[-1], 50)), 6),
                "p95":   round(float(np.percentile(traj_np[-1], 95)), 6),
            },
            "parameters": {
                "y0": y0,
                "t_start": t_start,
                "t_end": t_end,
                "n_steps": n_steps,
                "n_paths": n_paths,
                "state_size": state_size,
                "hidden_size": hidden_size,
                "method": method,
                "seed": seed,
            },
        }
