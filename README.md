# PageIndex Vault Tools

Tools for indexing and searching [Obsidian](https://obsidian.md/) vaults using [PageIndex](https://github.com/VectifyAI/PageIndex) — a vectorless, reasoning-based approach to document retrieval.

Instead of chunking documents and embedding them into vectors (traditional RAG), PageIndex builds **hierarchical tree structures** from your documents and uses **LLM reasoning** to navigate them. Think "where would a human expert look?" instead of "what text looks similar?"

## What's Here

- **`index_vault.sh`** — Batch index all markdown files in an Obsidian vault
- **`vault_search.py`** — Search across all indexed documents using LLM reasoning
- **`app.py`** — Web UI for searching your vault (FastAPI)

## Prerequisites

- Python 3.10+
- [PageIndex](https://github.com/VectifyAI/PageIndex) cloned and installed
- An OpenAI API key (PageIndex uses GPT-4o by default)

## Quick Start

### 1. Clone PageIndex and install

```bash
git clone https://github.com/VectifyAI/PageIndex.git
cd PageIndex
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### 2. Clone this repo

```bash
git clone https://github.com/Bluesun-Networks/pageindex-vault-tools.git
cd pageindex-vault-tools
```

### 3. Set your API key

```bash
cp .env.example .env
# Edit .env and add your OpenAI API key
```

### 4. Index your vault

```bash
# Edit VAULT and PAGEINDEX_DIR in index_vault.sh first
bash index_vault.sh
```

This will:
- Find all `.md` files in your vault
- Skip tiny files (< 3 lines) and already-indexed files
- Build PageIndex tree structures with summaries for each file
- Save JSON indexes mirroring your vault structure

On a ~2,400 file vault, this takes 1-2 hours and costs ~$10 in OpenAI API calls. It's a one-time cost — only re-index files that change.

### 5. Build the search catalog

```bash
python vault_search.py --rebuild-catalog
```

### 6. Search!

```bash
# CLI search
python vault_search.py "What CI/CD solution did we choose?"

# Interactive mode
python vault_search.py --interactive

# Shallow search (faster, no deep section drill-down)
python vault_search.py --shallow "homelab setup"
```

### 7. Web UI (optional)

```bash
pip install -r requirements.txt
uvicorn app:app --port 8888
# Open http://localhost:8888
```

## How It Works

### Indexing (`index_vault.sh`)

For each markdown file, PageIndex:
1. Extracts the header hierarchy (h1 → h2 → h3...)
2. Builds a tree structure mapping sections to content
3. Generates LLM summaries for each section
4. Saves the result as a JSON file

### Searching (`vault_search.py`)

Search happens in two phases:

1. **Catalog search** — The master catalog (document names) is sent to the LLM in chunks. The LLM identifies which documents are likely relevant to your query.

2. **Deep search** — For the top 3 matches, the full tree structure (with summaries) is sent to the LLM. It reasons about which specific sections contain the answer.

This is fundamentally different from vector search:
- No embeddings, no vector DB, no similarity scores
- The LLM *reasons* about document structure
- Results are traceable — you can see exactly why a section was chosen
- Expert knowledge integrates trivially (just modify the prompt)

## Configuration

All config via environment variables (or `.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `CHATGPT_API_KEY` | (required) | OpenAI API key |
| `PAGEINDEX_MODEL` | `gpt-4o-2024-11-20` | Model for search queries |
| `PAGEINDEX_BASE_URL` | (none) | For OpenAI-compatible APIs |
| `VAULT_PATH` | `~/src/shared-vault` | Path to your Obsidian vault |
| `INDEX_DIR` | `~/src/PageIndex/vault-index` | Where tree indexes are stored |
| `CATALOG_PATH` | `~/src/PageIndex/vault-catalog.json` | Master catalog location |

## Cost

- **Indexing:** ~$0.004 per file (one-time)
- **Search:** ~$0.01-0.05 per query (depending on catalog size and deep search)
- A 2,400 file vault costs ~$10 to fully index

## Limitations

- **OpenAI-only** (for now) — PageIndex is hardcoded to OpenAI. You can point `PAGEINDEX_BASE_URL` at an OpenAI-compatible API for search queries, but indexing still uses OpenAI.
- **Rate limits** — New OpenAI accounts have low TPM limits (30K). Searches may be slow until limits increase.
- **No incremental re-indexing** — Changed files need full re-indexing. The script skips already-indexed files.
- **Large catalogs need chunking** — With 2,000+ docs, the catalog gets split across multiple LLM calls.

## Credits

- [PageIndex](https://github.com/VectifyAI/PageIndex) by Vectify AI — the core tree indexing engine
- Inspired by a tweet from [@akshay_pachaar](https://x.com/akshay_pachaar/status/2025548705605341336)

## License

MIT
