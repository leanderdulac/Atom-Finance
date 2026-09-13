"""
AI Options Expert API — Scan B3 for the best trades.
"""
import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.security import get_current_user
from app.models.options_agent import (  # noqa: F401 — OptionsExpert kept as a patch target for tests/test_derivatives_planner.py::test_legacy_scanner_retired_without_model_call
    OptionsExpert,
    OptionTrade,
)

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(get_current_user)])

class ScanResult(BaseModel):
    timestamp: str
    num_trades: int
    trades: list[OptionTrade]
    expert_narrative: str
    
class ScanRequest(BaseModel):
    num_assets: int = Field(15, ge=5, le=30)
    risk_profile: str = "Moderado"

async def _get_expert_narrative(trades: list[OptionTrade], risk_profile: str) -> str:
    """Uses LLM to summarize the best setup of the day."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "Conecte sua API Key da Anthropic para receber o relatório completo."
    
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        
        trade_data = [
            f"Ativo: {t.ticker}, Ação: {t.action}, Strike: {t.strike}, Prob: {t.prob_success}%, Motivo: {t.reasoning}"
            for t in trades
        ]
        
        prompt = f"""Você é um estrategista sênior de opções da B3 (Brasil). 
Com base nestas 5 melhores operações do dia, escreva um resumo executivo para o cliente.
Fale de forma simples, mas com autoridade. Explique por que estamos recomendando estas estruturas agora.
Destaque a operação com melhor relação risco/retorno para o perfil {risk_profile}.

OPERACÕES:
{chr(10).join(trade_data)}

Relatório em Português (Brasil). Máximo 300 palavras."""

        msg = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        block = msg.content[0]
        if not isinstance(block, anthropic.types.TextBlock):
            return "Erro ao gerar narrativa de IA. Verifique as configurações."
        return block.text
    except Exception as e:
        logger.warning("Agent narrative failed: %s", e)
        return "Erro ao gerar narrativa de IA. Verifique as configurações."

@router.post("/scan")
async def scan_options(req: ScanRequest):
    """Scan and recommend best options trades."""
    raise HTTPException(410, "Scanner com prêmios e probabilidades estimados retirado. Use /api/derivatives/plan com contratos e cotações explícitos.")
