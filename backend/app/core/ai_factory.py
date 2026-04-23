"""
ATOM AI Factory — Centralized hub for multi-model intelligence.
Manages Claude (Fundamentals), GPT (Quant/Backtesting), and Gemini (News).
"""
from __future__ import annotations
import os
import logging
from typing import Literal, Optional, Any
from abc import ABC, abstractmethod

import anthropic
import openai
import google.generativeai as genai

logger = logging.getLogger(__name__)

class LLMException(Exception):
    """Base exception for LLM provider errors."""
    pass

class QuotaException(LLMException):
    """Exception raised when an API quota is exceeded (429)."""
    pass

class CreditException(LLMException):
    """Exception raised when account credit is insufficient (400 - insufficient_balance)."""
    pass

class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> str:
        pass

class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = "claude-3-5-sonnet-20241022"

    async def complete(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> str:
        try:
            message = await self.client.messages.create(
                model=self.model,
                max_tokens=kwargs.get("max_tokens", 1024),
                system=system_prompt if system_prompt else "Você é um analista financeiro sênior.",
                messages=[{"role": "user", "content": prompt}]
            )
            return message.content[0].text
        except anthropic.BadRequestError as e:
            if "credit balance" in str(e).lower():
                logger.error(f"Claude Credit Error: {e}")
                raise CreditException(str(e))
            raise LLMException(str(e))
        except anthropic.RateLimitError as e:
            logger.error(f"Claude Quota Error: {e}")
            raise QuotaException(str(e))
        except Exception as e:
            logger.error(f"Claude General Error: {e}")
            raise LLMException(str(e))

class GPTProvider(LLMProvider):
    def __init__(self, api_key: str):
        self.client = openai.AsyncOpenAI(api_key=api_key)
        self.model = "gpt-4o" # Placeholder for latest GPT

    async def complete(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> str:
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt if system_prompt else "Você é um estrategista quantitativo."},
                    {"role": "user", "content": prompt}
                ],
                **kwargs
            )
            return response.choices[0].message.content
        except Exception as e:
            err_msg = str(e).lower()
            if "insufficient_quota" in err_msg or "rate_limit" in err_msg:
                logger.error(f"GPT Quota Error: {e}")
                raise QuotaException(str(e))
            elif "insufficient_balance" in err_msg:
                logger.error(f"GPT Credit Error: {e}")
                raise CreditException(str(e))
            
            logger.error(f"GPT General Error: {e}")
            raise LLMException(str(e))

class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)
        # Using flash as it is more likely to be available on free/low-tier accounts
        self.model = genai.GenerativeModel('gemini-1.5-flash')

    async def complete(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> str:
        try:
            # Gemini handles system instructions in the model constructor or as a prefix
            full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
            response = await self.model.generate_content_async(full_prompt)
            return response.text
        except Exception as e:
            logger.error(f"Gemini error: {e}")
            raise LLMException(str(e))

class GrokProvider(LLMProvider):
    def __init__(self, api_key: str):
        # xAI is OpenAI compatible
        self.client = openai.AsyncOpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
        self.model = "grok-3"

    async def complete(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> str:
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt if system_prompt else "Você é o Grok, um assistente com inteligência em tempo real."},
                    {"role": "user", "content": prompt}
                ],
                **kwargs
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Grok error: {e}")
            return f"Erro no Grok: {e}"

class PerplexityProvider(LLMProvider):
    def __init__(self, api_key: str):
        # Perplexity is OpenAI compatible
        self.client = openai.AsyncOpenAI(api_key=api_key, base_url="https://api.perplexity.ai")
        self.model = "sonar-pro"

    async def complete(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> str:
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt if system_prompt else "Você é um pesquisador web especializado em finanças."},
                    {"role": "user", "content": prompt}
                ],
                **kwargs
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Perplexity error: {e}")
            return f"Erro no Perplexity: {e}"

class AIFactory:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AIFactory, cls).__new__(cls)
            cls._instance._init_providers()
        return cls._instance

    def _init_providers(self):
        self.providers = {
            "claude": ClaudeProvider(os.getenv("ANTHROPIC_API_KEY", "")) if os.getenv("ANTHROPIC_API_KEY") else None,
            "gpt": GPTProvider(os.getenv("OPENAI_API_KEY", "")) if os.getenv("OPENAI_API_KEY") else None,
            "gemini": GeminiProvider(os.getenv("GOOGLE_API_KEY", "")) if os.getenv("GOOGLE_API_KEY") else None,
            "grok": GrokProvider(os.getenv("XAI_API_KEY", "")) if os.getenv("XAI_API_KEY") else None,
            "perplexity": PerplexityProvider(os.getenv("PERPLEXITY_API_KEY", "")) if os.getenv("PERPLEXITY_API_KEY") else None,
        }

    def get_provider(self, name: str) -> Optional[LLMProvider]:
        return self.providers.get(name)

    async def generate_robust_complete(
        self, 
        prompt: str, 
        system_prompt: Optional[str] = None, 
        preferred_order: Optional[list[str]] = None,
        **kwargs
    ) -> str:
        """
        Attempts to complete the prompt using a list of providers in order.
        Fallbacks on QuotaException, CreditException, or other LLMExceptions.
        """
        if preferred_order is None:
            preferred_order = ["claude", "gpt", "grok", "gemini", "perplexity"]
            
        errors = []
        for name in preferred_order:
            provider = self.get_provider(name)
            if not provider:
                continue
            
            try:
                logger.info(f"Attempting robust completion via {name}...")
                return await provider.complete(prompt, system_prompt=system_prompt, **kwargs)
            except (QuotaException, CreditException) as e:
                logger.warning(f"{name} unavailable (quota/credit): {e}. Falling back...")
                errors.append(f"{name}: {e}")
                continue
            except LLMException as e:
                logger.warning(f"{name} failed with general error: {e}. Falling back...")
                errors.append(f"{name}: {e}")
                continue
            except Exception as e:
                logger.error(f"Unexpected error in {name} provider: {e}")
                errors.append(f"{name}: unexpected {e}")
                continue
                
        # If all fail
        logger.critical("All AI Providers failed for robust completion.")
        raise LLMException(f"Todos os provedores de IA falharam: {'; '.join(errors)}")

    @classmethod
    async def analyze_fundamental(cls, ticker: str, data: str) -> str:
        """Claude specialization for deep fundamental analysis. Fallbacks if needed."""
        system = "Você é um analista fundamentalista focado em 10-K e relatórios anuais. Extraia os pontos críticos de risco e oportunidade."
        prompt = f"Analise profundamente os dados fundamentais de {ticker}:\n{data}"
        
        try:
            return await cls().generate_robust_complete(
                prompt, system_prompt=system, preferred_order=["claude", "gpt", "gemini"]
            )
        except Exception as e:
            return f"Erro na análise fundamental: {e}"

    @classmethod
    async def analyze_quant(cls, strategy_name: str, parameters: dict) -> str:
        """GPT specialization for quantitative logic and backtesting. Fallbacks if needed."""
        system = "Você é um mestre em Python quantitativo e backtesting. Gere código e lógica robustos."
        prompt = f"Desenvolva a lógica de backtesting para a estratégia {strategy_name} com os parâmetros: {parameters}"
        
        try:
            return await cls().generate_robust_complete(
                prompt, system_prompt=system, preferred_order=["gpt", "claude", "grok"]
            )
        except Exception as e:
            return f"Erro na análise quant: {e}"

    @classmethod
    async def monitor_news(cls, ticker: str, news_text: str) -> str:
        """Gemini specialization for real-time news and sentiment analysis. Fallbacks if needed."""
        system = "Você é um monitor de notícias em tempo real. Identifique gatilhos imediatos de preço e sentimento de mercado."
        prompt = f"Analise o impacto destas notícias para {ticker}:\n{news_text}"
        
        try:
            return await cls().generate_robust_complete(
                prompt, system_prompt=system, preferred_order=["gemini", "perplexity", "gpt"]
            )
        except Exception as e:
            return f"Erro no monitoramento de notícias: {e}"

    @classmethod
    async def analyze_pulse(cls, ticker: str, data: str) -> str:
        """Grok specialization for social sentiment and real-time market pulse."""
        provider = cls().get_provider("grok")
        if not provider: return "Grok API não configurada."
        
        system = "Você é o Grok do xAI. Analise o pulso social e rumores de mercado com sarcasmo e precisão cirúrgica."
        prompt = f"Qual é o pulso atual para {ticker} nas redes e mercados?\n{data}"
        return await provider.complete(prompt, system_prompt=system)

    @classmethod
    async def search_web(cls, ticker: str) -> str:
        """Perplexity specialization for deep web search and live events."""
        provider = cls().get_provider("perplexity")
        if not provider: return "Perplexity API não configurada."
        
        system = "Você é um pesquisador de elite. Encontre os fatos e notícias mais recentes que impactam este ticker na internet."
        prompt = f"Pesquise os eventos mais recentes (últimas horas) e notícias de impacto para {ticker} na web brasileira e global."
        return await provider.complete(prompt, system_prompt=system)
