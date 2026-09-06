"""Vercel Python entry point. Vercel's Python runtime looks for serverless
functions under api/ (relative to this project's Root Directory, `backend`)
and detects an ASGI `app` object automatically -- this just re-exports the
real FastAPI app from ../app/main.py so there's exactly one FastAPI
instance, not a duplicate. See ../vercel.json for the rewrite that routes
every path here instead of only /api/index.
"""

from app.main import app

__all__ = ["app"]
