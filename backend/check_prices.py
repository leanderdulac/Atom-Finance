import os
import sys
import asyncio

# Adiciona o diretório backend ao path para importar app
sys.path.append(os.getcwd())

from app.services.brapi_service import BrapiService
from app.models.ibovespa import IBOVESPA_ASSETS

async def check_prices():
    print(f"{'Ticker':<10} | {'Hardcoded S0':<15} | {'Real Price (Brapi)':<20} | {'Status'}")
    print("-" * 60)
    
    for asset in IBOVESPA_ASSETS:
        ticker = asset['ticker']
        hardcoded_s0 = asset['S0']
        
        # BrapiService.get_quote é síncrono no código original
        quote = BrapiService.get_quote(ticker)
        
        if quote:
            real_price = quote.get('price', 0)
            diff = real_price - hardcoded_s0
            status = "DEFASADO" if abs(diff) > 1.0 else "OK"
            print(f"{ticker:<10} | {hardcoded_s0:<15.2f} | {real_price:<20.2f} | {status}")
        else:
            print(f"{ticker:<10} | {hardcoded_s0:<15.2f} | {'Falha ao buscar':<20} | ERROR")

if __name__ == "__main__":
    # Carrega variáveis de ambiente se necessário (.env)
    from dotenv import load_dotenv
    load_dotenv()
    
    asyncio.run(check_prices())
