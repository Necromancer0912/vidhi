"""
NyayaBot — Legacy root entrypoint proxy.
Proxies the actual FastAPI application from src/api/main.py.
This ensures standard deployment scripts/commands (e.g. uvicorn main:app) continue to function.
"""
from src.api.main import app
