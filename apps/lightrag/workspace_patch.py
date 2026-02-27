"""
Patch LightRAG to support per-request workspace multitenancy.

The PG and Neo4j storage backends already scope data by a `workspace`
column/label. This patch makes `workspace` a contextvar-backed property
on all relevant classes so each async request gets its own workspace,
read from the LIGHTRAG-WORKSPACE header.

Usage: Set as the Docker entrypoint instead of `lightrag-server`.
"""

import contextvars
import os
import sys

# ── contextvar: per-request workspace ───────────────────────────────
_current_workspace: contextvars.ContextVar[str] = contextvars.ContextVar(
    "lightrag_workspace", default=os.getenv("WORKSPACE", "default")
)


class _WorkspaceDescriptor:
    """Data descriptor that delegates to the contextvar."""

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return _current_workspace.get()

    def __set__(self, obj, value):
        _current_workspace.set(value)


def _patch_classes():
    """Install the workspace descriptor on LightRAG + all storage classes."""
    from lightrag import LightRAG
    from lightrag.kg.postgres_impl import (
        PGKVStorage,
        PGDocStatusStorage,
        PGVectorStorage,
    )
    from lightrag.kg.neo4j_impl import Neo4JStorage

    descriptor = _WorkspaceDescriptor()
    for cls in (LightRAG, PGKVStorage, PGDocStatusStorage, PGVectorStorage, Neo4JStorage):
        cls.workspace = descriptor


def _add_middleware(app):
    """Add ASGI middleware that sets workspace from request header."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from lightrag.kg.shared_storage import initialize_pipeline_status

    _initialized_workspaces: set[str] = set()

    class WorkspaceMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            ws = request.headers.get("LIGHTRAG-WORKSPACE", "").strip()
            if not ws:
                ws = os.getenv("WORKSPACE", "default")
            _current_workspace.set(ws)
            # Auto-initialize pipeline_status for new workspaces
            if ws not in _initialized_workspaces:
                await initialize_pipeline_status(workspace=ws)
                _initialized_workspaces.add(ws)
            return await call_next(request)

    app.add_middleware(WorkspaceMiddleware)


def main():
    # Patch classes BEFORE the app creates any instances
    _patch_classes()

    from lightrag.api.lightrag_server import create_app
    from lightrag.api.config import parse_args
    import uvicorn

    args = parse_args()
    app = create_app(args)

    # Add workspace middleware
    _add_middleware(app)

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
