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
    load_embeddings,
    embedding_search,
    search_catalog,
    deep_search,
    local_search,
    VAULT_ROOT,
)

app = FastAPI(title="Vault Search")

# Serve static files
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Cache catalog and embeddings in memory
_catalog = None
_embeddings = None


def get_catalog():
    global _catalog
    if _catalog is None:
        _catalog = load_catalog()
    return _catalog


def get_embeddings():
    global _embeddings
    if _embeddings is None:
        _embeddings = load_embeddings()
    return _embeddings


# ── Models ──────────────────────────────────────────────────────────


class SearchRequest(BaseModel):
    query: str
    deep: bool = False
    top_n: int = 10
    mode: str = "auto"  # "auto", "embedding", "llm", "keyword"


# ── Routes ──────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def index():
    return (STATIC_DIR / "index.html").read_text()


@app.get("/api/stats")
async def stats():
    catalog = get_catalog()
    embeddings = get_embeddings()
    return {
        "doc_count": len(catalog),
        "has_embeddings": embeddings is not None and len(embeddings) == len(catalog),
    }


@app.post("/api/search")
async def api_search(req: SearchRequest):
    catalog = get_catalog()
    embeddings = get_embeddings()

    # Determine search mode
    mode = req.mode
    if mode == "auto":
        if embeddings is not None and len(embeddings) == len(catalog):
            mode = "embedding"
        else:
            mode = "llm"

    if mode == "keyword":
        matches = local_search(catalog, req.query, req.top_n)
        return {"results": matches, "deep_results": {}, "mode": "keyword"}

    if mode == "embedding":
        if embeddings is None or len(embeddings) != len(catalog):
            return {"error": "Embeddings not available. Run --rebuild-catalog first.", "results": [], "deep_results": {}}
        matches = await asyncio.to_thread(
            embedding_search, catalog, embeddings, req.query, req.top_n
        )
        return {"results": matches, "deep_results": {}, "mode": "embedding"}

    # LLM mode
    client = get_client()
    matches = await asyncio.to_thread(
        search_catalog, client, catalog, req.query, req.top_n
    )

    if not matches:
        return {"results": [], "deep_results": {}, "mode": "llm"}

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

    return {"results": matches, "deep_results": deep_results, "mode": "llm"}


# Build a filename→relative-path map at startup for fast lookups
_vault_file_map = None

def _get_vault_file_map():
    global _vault_file_map
    if _vault_file_map is None:
        _vault_file_map = {}
        vault = Path(VAULT_ROOT)
        for p in vault.rglob("*"):
            if p.is_file():
                rel = str(p.relative_to(vault))
                _vault_file_map[p.name] = rel
                # Also map by relative path
                _vault_file_map[rel] = rel
    return _vault_file_map


def _obsidian_to_markdown(text):
    """Convert Obsidian wiki-links to standard markdown."""
    import re
    # ![[image.png]] → ![image.png](/api/doc?path=image.png&raw=1) — but just strip for now
    # ![[file]] embeds — convert to linked references
    text = re.sub(r'!\[\[([^\]]+)\]\]', lambda m: f'*(embedded: {m.group(1)})*', text)
    # [[link|display]] → display
    text = re.sub(r'\[\[([^\]|]+)\|([^\]]+)\]\]', r'\2', text)
    # [[link]] → link
    text = re.sub(r'\[\[([^\]]+)\]\]', r'\1', text)
    return text


@app.get("/api/doc")
async def get_document(path: str):
    """Return rendered markdown for a vault document."""
    vault_resolved = Path(VAULT_ROOT).resolve()
    
    # Try direct path first
    full = Path(VAULT_ROOT) / path
    try:
        full = full.resolve()
    except (OSError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid path")

    if not str(full).startswith(str(vault_resolved)):
        raise HTTPException(status_code=403, detail="Path outside vault")

    # If not found directly, search by filename
    if not full.exists():
        file_map = _get_vault_file_map()
        filename = Path(path).name
        mapped = file_map.get(filename) or file_map.get(path)
        if mapped:
            full = (Path(VAULT_ROOT) / mapped).resolve()
            if not str(full).startswith(str(vault_resolved)):
                raise HTTPException(status_code=403, detail="Path outside vault")
        else:
            raise HTTPException(status_code=404, detail="File not found")

    if not full.exists():
        raise HTTPException(status_code=404, detail="File not found")

    raw = full.read_text(errors="replace")
    processed = _obsidian_to_markdown(raw)
    html = markdown.markdown(
        processed,
        extensions=["fenced_code", "tables", "toc", "codehilite"],
    )
    return {"path": path, "raw": raw, "html": html}
