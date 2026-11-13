"""Local Ollama chat — optional, never decides a trade.

Used only to rewrite a Portuguese «por quê» from numbers the orchestrator
already computed. Missing daemon, timeout or empty reply → caller uses the
template. Paid cloud keys stay unused here.
"""
from __future__ import annotations

import logging
import os

import httpx

from app.core.quant_doctrine import compose_system

logger = logging.getLogger(__name__)

_WHY_SYSTEM = (
    "Redija em pt-BR, no máximo quatro frases curtas, o porquê de uma operação "
    "já calculada. Você NÃO escolhe direção, estrutura, stop nem tamanho. "
    "Use só os números e rótulos fornecidos. Sem promessa de retorno, sem "
    "recomendação, sem ordem. Diga que é cenário/simulação. Se o bloco disser "
    "que o arsenal recusou, explique a recusa sem inventar uma tese. "
    "Proibido citar nomes de variáveis ou jargão interno "
    "(z_score, EWMA, GARCH, Hurst, eligible_for_live_trading, kill_switch)."
)


def ollama_configured() -> bool:
    if os.getenv("OLLAMA_ENABLED", "1").strip().lower() in {"0", "false", "no", "off"}:
        return False
    return bool(os.getenv("OLLAMA_HOST", "http://localhost:11434").strip())


async def draft_why(facts: str) -> str | None:
    if not ollama_configured():
        return None
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "llama3.2:3b").strip() or "llama3.2:3b"
    timeout = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "8"))
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": compose_system(_WHY_SYSTEM)},
            {"role": "user", "content": facts},
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{host}/api/chat", json=payload)
            response.raise_for_status()
            message = response.json().get("message") or {}
            text = (message.get("content") or "").strip()
            return text or None
    except Exception as exc:
        logger.info("Ollama unavailable for why-text (%s); using template.", type(exc).__name__)
        return None
