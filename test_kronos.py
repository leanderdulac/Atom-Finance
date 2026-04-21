import asyncio
import logging
import sys
import os

# Ensure backend modules can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend')))

from app.models.ibovespa import refresh_ibovespa_params, IBOVESPA_ASSETS

logging.basicConfig(level=logging.INFO)

async def run_test():
    logging.info("Starting test: Refreshing Ibovespa parameters (which hits Kronos AI)...")
    
    # Run the refresh function (this triggers Yahoo Finance + Kronos prediction)
    success = await refresh_ibovespa_params(force=True)
    
    if not success:
        logging.error("Refresh failed.")
        sys.exit(1)
        
    logging.info("Refresh succeeded. Checking the updated parameters:")
    for asset in IBOVESPA_ASSETS[:3]:  # Print first 3 assets to verify
        logging.info(f"{asset['ticker']}: S0={asset['S0']}, mu={asset['mu']}, sigma={asset['sigma']}, sector={asset['sector']}")

if __name__ == "__main__":
    asyncio.run(run_test())
