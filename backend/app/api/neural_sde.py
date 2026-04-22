"""Neural SDE API endpoints."""

import asyncio
from functools import partial

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from app.models.neural_sde import NeuralSDE

router = APIRouter()


class NeuralSDERequest(BaseModel):
    y0: float = Field(0.1, description="Initial state value")
    t_start: float = Field(0.0, description="Simulation start time")
    t_end: float = Field(1.0, gt=0, description="Simulation end time")
    n_steps: int = Field(100, ge=10, le=1000, description="Number of time steps")
    n_paths: int = Field(10, ge=1, le=200, description="Number of trajectories")
    state_size: int = Field(1, ge=1, le=4, description="State dimensionality")
    hidden_size: int = Field(32, ge=8, le=128, description="Hidden units in μ/σ networks")
    method: str = Field("euler", pattern="^(euler|milstein)$", description="SDE solver method")
    seed: Optional[int] = Field(42, description="Random seed (null for random)")


async def _run_in_thread(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))


@router.get("/status")
async def sde_status():
    """Check whether the Neural SDE model (torchsde) is available."""
    return {
        "available": NeuralSDE.is_available(),
        "model": "neural_sde",
        "description": "Neural Stochastic Differential Equation via torchsde (Itô / Euler-Maruyama)",
    }


@router.post("/simulate")
async def simulate_sde(req: NeuralSDERequest):
    """
    Simulate trajectories of a Neural SDE.

    The drift μ(t,y) and diffusion σ(t,y) are parameterised by small
    randomly-initialised neural networks. Each call uses a fresh random
    initialisation (or the provided seed) — results represent one possible
    learned dynamics.
    """
    if not NeuralSDE.is_available():
        raise HTTPException(
            status_code=503,
            detail="torchsde is not installed. Run: pip install torchsde",
        )

    return await _run_in_thread(
        NeuralSDE.simulate,
        req.y0,
        req.t_start,
        req.t_end,
        req.n_steps,
        req.n_paths,
        req.state_size,
        req.hidden_size,
        req.method,
        req.seed,
    )


@router.get("/demo")
async def demo_sde():
    """Run a quick demo simulation with default parameters."""
    if not NeuralSDE.is_available():
        raise HTTPException(status_code=503, detail="torchsde not installed.")

    return await _run_in_thread(
        NeuralSDE.simulate,
        0.1,   # y0
        0.0,   # t_start
        1.0,   # t_end
        100,   # n_steps
        20,    # n_paths
        1,     # state_size
        32,    # hidden_size
        "euler",
        42,    # seed
    )
