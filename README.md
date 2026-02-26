# PageIndex Vault Tools

Tools for indexing and searching [Obsidian](https://obsidian.md/) vaults using [PageIndex](https://github.com/VectifyAI/PageIndex) — a vectorless, reasoning-based approach to document retrieval.

Instead of chunking documents and embedding them into vectors (traditional RAG), PageIndex builds **hierarchical tree structures** from your documents and uses **LLM reasoning** to navigate them. Think "where would a human expert look?" instead of "what text looks similar?"

## What's Here

- **`index_vault.sh`** — Batch index all markdown files in an Obsidian vault
- **`vault_search.py`** — Search across all indexed documents using LLM reasoning
- **`app.py`** — Web UI for searching your vault (FastAPI)

## Prerequisites

- Python 3.10+
- An OpenAI API key **or** AWS credentials with Bedrock access

---

## Part 1: Set Up PageIndex

PageIndex is the core indexing engine. Set it up first.

### 1.1 Clone and create a virtual environment

#### With pip
```bash
git clone https://github.com/VectifyAI/PageIndex.git
cd PageIndex
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

#### With uv (faster)
```bash
git clone https://github.com/VectifyAI/PageIndex.git
cd PageIndex
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
```

### 1.2 Configure your LLM API key

```bash
export CHATGPT_API_KEY="sk-..."
```

Or for Bedrock:
```bash
export PAGEINDEX_PROVIDER=bedrock
export AWS_REGION=us-west-2
# AWS credentials via env vars, ~/.aws/credentials, or IAM role
```

### 1.3 Test it

Try indexing a single file to make sure everything works:

```bash
python run_pageindex.py --pdf_path /path/to/any/document.pdf
```

If that produces a JSON tree output, PageIndex is working.

---

## Part 2: Set Up Vault Tools

The vault tools wrap PageIndex for Obsidian vault indexing, CLI search, and a web UI.

### 2.1 Clone and install (into the same venv)

Activate the PageIndex venv from Part 1 first:

```bash
# If you're not already in the venv:
cd /path/to/PageIndex
source venv/bin/activate   # or: source .venv/bin/activate (uv)
```

Then install the vault tools:

#### With pip
```bash
git clone https://github.com/Bluesun-Networks/pageindex-vault-tools.git
cd pageindex-vault-tools
pip install -r requirements.txt
```

#### With uv
```bash
git clone https://github.com/Bluesun-Networks/pageindex-vault-tools.git
cd pageindex-vault-tools
uv pip install -r requirements.txt
```

### 2.2 Configure

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```bash
# LLM provider (openai or bedrock)
CHATGPT_API_KEY=sk-...
PAGEINDEX_PROVIDER=openai
PAGEINDEX_MODEL=gpt-4o-2024-11-20

# Paths
VAULT_PATH=~/src/shared-vault          # your Obsidian vault
INDEX_DIR=~/src/PageIndex/vault-index   # where tree indexes are stored
CATALOG_PATH=~/src/PageIndex/vault-catalog.json
```

See [Configuration](#configuration) below for the full list of options.

### 2.3 Index your vault

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

### 2.4 Build the search catalog

```bash
python vault_search.py --rebuild-catalog
```

### 2.5 Search (CLI)

```bash
# Single query
python vault_search.py "What CI/CD solution did we choose?"

# Interactive mode
python vault_search.py --interactive

# Shallow search (faster, no deep section drill-down)
python vault_search.py --shallow "homelab setup"
```

### 2.6 Search (Web UI)

The web UI is a FastAPI app that provides a browser-based search interface.

#### Foreground (development)

```bash
uvicorn app:app --host 0.0.0.0 --port 8888 --reload
# Open http://localhost:8888
# Ctrl+C to stop
```

#### Background (quick)

```bash
nohup uvicorn app:app --host 0.0.0.0 --port 8888 >> vault-search.log 2>&1 &
echo $!  # save the PID if you need to stop it later
```

#### Daemon — systemd (Linux)

```ini
# /etc/systemd/system/vault-search.service
[Unit]
Description=Vault Search Web UI
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/pageindex-vault-tools
Environment=PYTHONPATH=/path/to/PageIndex
EnvironmentFile=/path/to/pageindex-vault-tools/.env
ExecStart=/path/to/venv/bin/uvicorn app:app --host 0.0.0.0 --port 8888
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vault-search
sudo systemctl status vault-search
```

#### Daemon — launchd (macOS)

```xml
<!-- ~/Library/LaunchAgents/com.vaultsearch.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.vaultsearch</string>
    <key>WorkingDirectory</key>
    <string>/path/to/pageindex-vault-tools</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/venv/bin/uvicorn</string>
        <string>app:app</string>
        <string>--host</string>
        <string>0.0.0.0</string>
        <string>--port</string>
        <string>8888</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/vault-search.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/vault-search.log</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.vaultsearch.plist
launchctl list | grep vaultsearch
```

---

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
| `CHATGPT_API_KEY` | (required for OpenAI) | OpenAI API key |
| `PAGEINDEX_PROVIDER` | `openai` | LLM provider: `openai` or `bedrock` |
| `PAGEINDEX_MODEL` | `gpt-4o-2024-11-20` | Model for search queries |
| `PAGEINDEX_BASE_URL` | (none) | For OpenAI-compatible APIs |
| `AWS_REGION` | `us-west-2` | AWS region for Bedrock |
| `BEDROCK_MODEL_ID` | `anthropic.claude-3-5-sonnet-20241022-v2:0` | Bedrock model override |
| `VAULT_PATH` | `~/src/shared-vault` | Path to your Obsidian vault |
| `INDEX_DIR` | `~/src/PageIndex/vault-index` | Where tree indexes are stored |
| `CATALOG_PATH` | `~/src/PageIndex/vault-catalog.json` | Master catalog location |

### Using Amazon Bedrock

Set `PAGEINDEX_PROVIDER=bedrock` and ensure AWS credentials are available (env vars, `~/.aws/credentials`, or IAM role).

```bash
# .env
PAGEINDEX_PROVIDER=bedrock
AWS_REGION=us-west-2
# Optional: override model (default is Claude 3.5 Sonnet)
# BEDROCK_MODEL_ID=anthropic.claude-3-5-haiku-20241022-v1:0

# Friendly model names also work:
# PAGEINDEX_MODEL=claude-3.5-sonnet
```

Install the optional Bedrock dependencies:
```bash
pip install boto3  # or: uv pip install boto3
```

## Cost

- **Indexing:** ~$0.004 per file (one-time)
- **Search:** ~$0.01-0.05 per query (depending on catalog size and deep search)
- A 2,400 file vault costs ~$10 to fully index

## Limitations

- **OpenAI or Bedrock** — Supports OpenAI (default) and Amazon Bedrock. Set `PAGEINDEX_PROVIDER=bedrock` to use Bedrock with Claude models.
- **Rate limits** — New OpenAI accounts have low TPM limits (30K). Searches may be slow until limits increase.
- **No incremental re-indexing** — Changed files need full re-indexing. The script skips already-indexed files.
- **Large catalogs need chunking** — With 2,000+ docs, the catalog gets split across multiple LLM calls.

## Credits

- [PageIndex](https://github.com/VectifyAI/PageIndex) by Vectify AI — the core tree indexing engine
- Inspired by a tweet from [@akshay_pachaar](https://x.com/akshay_pachaar/status/2025548705605341336)

## License

MIT
