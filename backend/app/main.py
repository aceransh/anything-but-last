from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routers import health, leagues, lineup, trade

app = FastAPI(title="Fantasy Copilot Season Tools API")

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(leagues.router, prefix="/leagues", tags=["leagues"])
app.include_router(lineup.router, prefix="/leagues", tags=["lineup"])
app.include_router(trade.router, prefix="/leagues", tags=["trade"])
