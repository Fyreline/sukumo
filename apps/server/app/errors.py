"""Uniform error shape (docs/API.md): ``{"detail": ..., "code": ...}``.

FastAPI's default ``HTTPException`` only carries ``detail``. Routers that
need a machine-readable ``code`` alongside the human message raise
``SukumoHTTPException`` instead; ``main.py`` registers the exception handler
below so the JSON body matches the documented shape exactly. Renamed port of
Michi's ``MichiHTTPException`` / Mishka Hub's ``MishkaHTTPException``
(docs/ARCHITECTURE.md §4).
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse


class SukumoHTTPException(HTTPException):
    def __init__(self, status_code: int, detail: str, code: str) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(SukumoHTTPException)
    async def _sukumo_http_exception_handler(
        request: Request, exc: SukumoHTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "code": exc.code},
        )
