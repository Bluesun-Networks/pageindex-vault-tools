#!/usr/bin/env python3
"""
Vault Search - Reasoning-based search across PageIndex tree indexes.

Usage:
    python vault_search.py "your query here"
    python vault_search.py --rebuild-catalog   # rebuild the master catalog
    python vault_search.py --interactive        # interactive mode
"""

import os
import json
import sys
import glob
import argparse
from pathlib import Path

# Support OpenAI, OpenAI-compatible APIs, and Amazon Bedrock
import openai
from dotenv import load_dotenv
load_dotenv()

# Optional Bedrock dependencies
try:
    import boto3
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False

INDEX_DIR = os.path.expandvars(os.path.expanduser(
    os.getenv("INDEX_DIR", "~/src/PageIndex/vault-index")))
CATALOG_PATH = os.path.expandvars(os.path.expanduser(
    os.getenv("CATALOG_PATH", "~/src/PageIndex/vault-catalog.json")))
VAULT_ROOT = os.path.expandvars(os.path.expanduser(
    os.getenv("VAULT_PATH", "~/src/shared-vault")))

API_KEY = os.getenv("CHATGPT_API_KEY") or os.getenv("OPENAI_API_KEY")
MODEL = os.getenv("PAGEINDEX_MODEL", "gpt-4o-2024-11-20")
BASE_URL = os.getenv("PAGEINDEX_BASE_URL")  # Set for OpenAI-compatible APIs
PROVIDER = os.getenv("PAGEINDEX_PROVIDER", "openai").lower()

# Bedrock API key support (OpenAI-compatible endpoint)
BEDROCK_API_KEY = os.getenv("AWS_BEARER_TOKEN_BEDROCK")
BEDROCK_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-west-2"
if BEDROCK_API_KEY and PROVIDER != "bedrock":
    # Auto-detect: if bearer token is set but provider isn't explicitly bedrock,
    # switch to bedrock-apikey mode
    PROVIDER = "bedrock-apikey"
elif BEDROCK_API_KEY and PROVIDER == "bedrock":
    # Prefer API key over boto3 if both are available
    PROVIDER = "bedrock-apikey"

# Bedrock model mapping
BEDROCK_MODELS = {
    'claude-3.5-sonnet': 'anthropic.claude-3-5-sonnet-20241022-v2:0',
    'claude-3-sonnet': 'anthropic.claude-3-sonnet-20240229-v1:0',
    'claude-3-haiku': 'anthropic.claude-3-haiku-20240307-v1:0',
    'claude-3.5-haiku': 'anthropic.claude-3-5-haiku-20241022-v1:0',
}
BEDROCK_DEFAULT_MODEL = 'anthropic.claude-3-5-sonnet-20241022-v2:0'


def _get_aws_region():
    return os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-west-2"


def _resolve_bedrock_model():
    model_id = os.getenv("BEDROCK_MODEL_ID") or MODEL
    return BEDROCK_MODELS.get(model_id, model_id)


def get_client():
    if PROVIDER == "bedrock-apikey":
        # Use Bedrock's OpenAI-compatible endpoint with API key
        base_url = BASE_URL or f"https://bedrock-mantle.{BEDROCK_REGION}.api.aws/v1"
        return openai.OpenAI(api_key=BEDROCK_API_KEY, base_url=base_url)
    if PROVIDER == "bedrock":
        if not HAS_BOTO3:
            raise ImportError("boto3 is required for Bedrock provider. Install with: pip install boto3")
        return boto3.client('bedrock-runtime', region_name=_get_aws_region())
    kwargs = {"api_key": API_KEY}
    if BASE_URL:
        kwargs["base_url"] = BASE_URL
    return openai.OpenAI(**kwargs)


def llm_call(client, prompt, system=None, temperature=0, retries=5):
    import time
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    for attempt in range(retries):
        try:
            if PROVIDER == "bedrock":
                body = {
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 4096,
                    "temperature": temperature,
                    "messages": messages,
                }
                response = client.invoke_model(
                    modelId=_resolve_bedrock_model(),
                    contentType='application/json',
                    accept='application/json',
                    body=json.dumps(body),
                )
                result = json.loads(response['body'].read())
                return result['content'][0]['text']
            else:
                model = _resolve_bedrock_model() if PROVIDER == "bedrock-apikey" else MODEL
                resp = client.chat.completions.create(
                    model=model, messages=messages, temperature=temperature
                )
                return resp.choices[0].message.content
        except Exception as e:
            wait = min(2 ** attempt, 30)
            print(f"  Error: {e}, waiting {wait}s...")
            time.sleep(wait)
    raise Exception("Max retries exceeded")


def extract_json_from_response(text):
    """Extract JSON from LLM response, handling markdown code blocks."""
    import re
    # Try to find JSON in code blocks first
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if match:
        text = match.group(1)
    # Try to parse directly
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON array or object
        for start_char, end_char in [('[', ']'), ('{', '}')]:
            start = text.find(start_char)
            end = text.rfind(end_char)
            if start != -1 and end != -1:
                try:
                    return json.loads(text[start:end+1])
                except json.JSONDecodeError:
                    continue
    return None


def build_catalog():
    """Build a compact master catalog from all tree indexes."""
    print("Building master catalog from tree indexes...")
    catalog = []
    
    # Find all structure JSON files
    json_files = []
    for root, dirs, files in os.walk(INDEX_DIR):
        for f in files:
            if f.endswith("_structure.json"):
                json_files.append(os.path.join(root, f))
    
    print(f"Found {len(json_files)} index files")
    
    for jf in json_files:
        try:
            with open(jf, 'r') as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue
        
        doc_name = data.get("doc_name", Path(jf).stem.replace("_structure", ""))
        structure = data.get("structure", [])
        
        # Extract top-level titles and summaries (compact representation)
        sections = []
        for node in structure:
            entry = {"title": node.get("title", "")}
            # Prefer prefix_summary over summary, truncate to save space
            summary = node.get("prefix_summary") or node.get("summary", "")
            if summary and len(summary) > 200:
                summary = summary[:200] + "..."
            if summary:
                entry["summary"] = summary
            
            # Include child titles for more context
            children = node.get("nodes", [])
            if children:
                entry["subsections"] = [c.get("title", "") for c in children[:8]]
            
            sections.append(entry)
        
        # Try to recover the vault-relative path
        vault_path = recover_vault_path(jf, doc_name)
        
        catalog.append({
            "doc_name": doc_name,
            "vault_path": vault_path,
            "index_path": jf,
            "section_count": len(sections),
            "sections": sections[:15]  # Limit to top 15 sections for catalog
        })
    
    # Sort by doc_name
    catalog.sort(key=lambda x: x["doc_name"].lower())
    
    with open(CATALOG_PATH, 'w') as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
    
    print(f"Catalog built: {len(catalog)} documents")
    return catalog


def recover_vault_path(index_path, doc_name):
    """Try to find the original vault file path from the index path."""
    # The index files ended up with full paths due to the symlink issue
    # Try to reconstruct
    rel = os.path.relpath(index_path, INDEX_DIR)
    # Remove _structure.json suffix and try as vault path
    md_rel = rel.replace("_structure.json", ".md")
    
    # Check common patterns
    candidates = [
        os.path.join(VAULT_ROOT, md_rel),
        os.path.join(VAULT_ROOT, doc_name + ".md"),
    ]
    
    for c in candidates:
        if os.path.exists(c):
            return os.path.relpath(c, VAULT_ROOT)
    
    return doc_name + ".md"


def load_catalog():
    """Load the master catalog, building if needed."""
    if not os.path.exists(CATALOG_PATH):
        return build_catalog()
    with open(CATALOG_PATH, 'r') as f:
        return json.load(f)


def search_catalog(client, catalog, query, top_n=10):
    """Use LLM to find relevant documents from the catalog. Chunks if needed."""
    
    # Build compact catalog — just names, minimal info
    compact = []
    for i, doc in enumerate(catalog):
        entry = f"[{i}] {doc['doc_name']}"
        compact.append(entry)
    
    # Chunk catalog into groups that fit in ~15K tokens (~60K chars)
    CHUNK_SIZE = 800  # entries per chunk
    all_candidates = []
    
    chunks = [compact[i:i+CHUNK_SIZE] for i in range(0, len(compact), CHUNK_SIZE)]
    
    for chunk_idx, chunk in enumerate(chunks):
        catalog_text = "\n".join(chunk)
        
        prompt = f"""You are searching a knowledge vault. Find documents relevant to this query.

Query: {query}

Document list (chunk {chunk_idx+1}/{len(chunks)}):
{catalog_text}

Return a JSON array of the most relevant document indices (numbers in brackets), max {top_n}.
[{{"index": 0, "reason": "brief reason"}}]
Only return the JSON array."""

        response = llm_call(client, prompt)
        results = extract_json_from_response(response)
        if results:
            all_candidates.extend(results)
    
    if not all_candidates:
        print("Failed to parse search results")
        return []
    
    # If we got candidates from multiple chunks, do a final ranking
    if len(chunks) > 1 and len(all_candidates) > top_n:
        # Collect the candidate docs with their reasons
        candidate_docs = []
        for r in all_candidates:
            idx = r.get("index", -1)
            if 0 <= idx < len(catalog):
                candidate_docs.append(f"[{idx}] {catalog[idx]['doc_name']} — {r.get('reason', '')}")
        
        rerank_text = "\n".join(candidate_docs)
        prompt = f"""Rank these documents by relevance to the query. Return top {top_n}.

Query: {query}

Candidates:
{rerank_text}

Return JSON array: [{{"index": N, "reason": "why"}}]
Only return the JSON array."""
        
        response = llm_call(client, prompt)
        reranked = extract_json_from_response(response)
        if reranked:
            all_candidates = reranked
    
    # Map back to catalog entries
    matched = []
    seen = set()
    for r in all_candidates[:top_n]:
        idx = r.get("index", -1)
        if 0 <= idx < len(catalog) and idx not in seen:
            seen.add(idx)
            matched.append({
                **catalog[idx],
                "relevance_reason": r.get("reason", "")
            })
    
    return matched


def deep_search(client, index_path, query):
    """Search within a specific document's tree index."""
    try:
        with open(index_path, 'r') as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return None
    
    structure = data.get("structure", [])
    
    # Build tree representation with summaries
    def tree_to_text(nodes, depth=0):
        lines = []
        for n in nodes:
            indent = "  " * depth
            line = f"{indent}- [{n.get('node_id', '?')}] {n.get('title', 'Untitled')}"
            summary = n.get("prefix_summary") or n.get("summary", "")
            if summary:
                # Truncate long summaries
                if len(summary) > 300:
                    summary = summary[:300] + "..."
                line += f"\n{indent}  Summary: {summary}"
            lines.append(line)
            if n.get("nodes"):
                lines.extend(tree_to_text(n["nodes"], depth + 1))
        return lines
    
    tree_text = "\n".join(tree_to_text(structure))
    
    prompt = f"""You are analyzing a document's structure to find sections relevant to a query.

Query: {query}

Document: {data.get('doc_name', 'Unknown')}

Document tree structure:
{tree_text}

Which sections are most relevant to the query? For each relevant section, explain what information it likely contains.

Return a JSON array:
[
  {{"node_id": "0001", "title": "section title", "relevance": "why this section answers the query"}}
]

Only return the JSON array."""

    response = llm_call(client, prompt)
    return extract_json_from_response(response)


def format_results(catalog_matches, deep_results=None):
    """Format search results for display."""
    output = []
    output.append(f"\n{'='*60}")
    output.append(f"Found {len(catalog_matches)} relevant documents")
    output.append(f"{'='*60}\n")
    
    for i, doc in enumerate(catalog_matches):
        output.append(f"📄 [{i+1}] {doc['doc_name']}")
        output.append(f"   Path: {doc.get('vault_path', 'unknown')}")
        output.append(f"   Why: {doc.get('relevance_reason', 'N/A')}")
        
        if deep_results and doc['doc_name'] in deep_results:
            sections = deep_results[doc['doc_name']]
            if sections:
                output.append(f"   Relevant sections:")
                for s in sections[:5]:
                    output.append(f"     → [{s.get('node_id', '?')}] {s.get('title', '?')}")
                    output.append(f"       {s.get('relevance', '')}")
        output.append("")
    
    return "\n".join(output)


def search(query, deep=True, top_n=10):
    """Main search function."""
    client = get_client()
    catalog = load_catalog()
    
    print(f"\n🔍 Searching vault for: \"{query}\"")
    print(f"   Catalog: {len(catalog)} documents\n")
    
    # Phase 1: Find relevant documents
    matches = search_catalog(client, catalog, query, top_n=top_n)
    
    if not matches:
        print("No relevant documents found.")
        return
    
    # Phase 2: Deep search within top matches
    deep_results = {}
    if deep:
        print(f"Deep searching top {min(3, len(matches))} documents...")
        for doc in matches[:3]:
            index_path = doc.get("index_path")
            if index_path and os.path.exists(index_path):
                result = deep_search(client, index_path, query)
                if result:
                    deep_results[doc['doc_name']] = result
    
    # Format and display
    print(format_results(matches, deep_results))
    return matches, deep_results


def interactive_mode():
    """Interactive search loop."""
    print("\n🔮 PageIndex Vault Search")
    print("Type your query, or 'quit' to exit.\n")
    
    while True:
        try:
            query = input("🔍 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break
        
        if not query or query.lower() in ('quit', 'exit', 'q'):
            break
        
        deep = not query.startswith("!")  # prefix with ! for shallow search
        if not deep:
            query = query[1:].strip()
        
        search(query, deep=deep)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Search vault using PageIndex trees")
    parser.add_argument("query", nargs="?", help="Search query")
    parser.add_argument("--rebuild-catalog", action="store_true", help="Rebuild master catalog")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")
    parser.add_argument("--shallow", action="store_true", help="Skip deep search")
    parser.add_argument("--top", type=int, default=10, help="Number of results")
    args = parser.parse_args()
    
    if args.rebuild_catalog:
        build_catalog()
    elif args.interactive:
        interactive_mode()
    elif args.query:
        search(args.query, deep=not args.shallow, top_n=args.top)
    else:
        parser.print_help()
