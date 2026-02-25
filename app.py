"""Vault Search Web UI — FastAPI backend."""

import os
import asyncio
from pathlib import Path

import markdown
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from vault_search import (
    get_client,
    load_catalog,
    search_catalog,
    deep_search,
    VAULT_ROOT,
)

app = FastAPI(title="Vault Search")

# Serve static files
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Cache the catalog in memory
_catalog = None


def get_catalog():
    global _catalog
    if _catalog is None:
        _catalog = load_catalog()
    return _catalog


# ── Models ──────────────────────────────────────────────────────────


class SearchRequest(BaseModel):
    query: str
    deep: bool = True
    top_n: int = 10


# ── Routes ──────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def index():
    return (STATIC_DIR / "index.html").read_text()


@app.get("/api/stats")
async def stats():
    catalog = get_catalog()
    return {"doc_count": len(catalog)}


@app.post("/api/search")
async def api_search(req: SearchRequest):
    catalog = get_catalog()
    client = get_client()

    # Phase 1 — catalog search (runs LLM calls, may be slow)
    matches = await asyncio.to_thread(
        search_catalog, client, catalog, req.query, req.top_n
    )

    if not matches:
        return {"results": [], "deep_results": {}}

    # Phase 2 — optional deep search on top 3
    deep_results = {}
    if req.deep:
        for doc in matches[:3]:
            index_path = doc.get("index_path")
            if index_path and os.path.exists(index_path):
                result = await asyncio.to_thread(
                    deep_search, client, index_path, req.query
                )
                if result:
                    deep_results[doc["doc_name"]] = result

    return {"results": matches, "deep_results": deep_results}


@app.get("/api/doc")
async def get_document(path: str):
    """Return rendered markdown for a vault document."""
    # Resolve safely within VAULT_ROOT
    full = Path(VAULT_ROOT) / path
    try:
        full = full.resolve()
    except (OSError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid path")

    vault_resolved = Path(VAULT_ROOT).resolve()
    if not str(full).startswith(str(vault_resolved)):
        raise HTTPException(status_code=403, detail="Path outside vault")

    if not full.exists():
        raise HTTPException(status_code=404, detail="File not found")

    raw = full.read_text(errors="replace")
    html = markdown.markdown(
        raw,
        extensions=["fenced_code", "tables", "toc", "codehilite"],
    )
    return {"path": path, "raw": raw, "html": html}
