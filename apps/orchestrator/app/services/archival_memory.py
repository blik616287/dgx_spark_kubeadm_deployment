import httpx

_lightrag_url: str = ""


def init_archival(url: str):
    global _lightrag_url
    _lightrag_url = url


async def query(
    text: str,
    workspace: str,
    mode: str = "hybrid",
    client: httpx.AsyncClient | None = None,
) -> dict:
    """Query LightRAG and return raw structured graph data."""
    should_close = False
    if client is None:
        client = httpx.AsyncClient()
        should_close = True

    empty = {"entities": [], "relations": [], "chunks": []}
    try:
        resp = await client.post(
            f"{_lightrag_url}/query/data",
            json={"query": text, "mode": mode},
            headers={"LIGHTRAG-WORKSPACE": workspace},
            timeout=15.0,
        )
        if resp.status_code == 200:
            payload = resp.json()
            data = payload.get("data", payload)
            return {
                "entities": data.get("entities", []),
                "relations": data.get("relations", []),
                "chunks": data.get("chunks", []),
            }
        return empty
    except Exception:
        return empty
    finally:
        if should_close:
            await client.aclose()


def format_context(
    data: dict,
    max_entities: int = 30,
    max_relations: int = 20,
    max_chunks: int = 5,
) -> str:
    """Format raw graph data into structured context for a coding LLM."""
    parts = []

    entities = data.get("entities", [])
    if entities:
        lines = []
        for e in entities[:max_entities]:
            name = e.get("entity_name", "?")
            etype = e.get("entity_type", "?")
            desc = e.get("description", "")
            if desc:
                lines.append(f"- [{etype}] {name}: {desc}")
            else:
                lines.append(f"- [{etype}] {name}")
        parts.append("Entities:\n" + "\n".join(lines))

    relations = data.get("relations", [])
    if relations:
        lines = []
        for r in relations[:max_relations]:
            src = r.get("src_id", "?")
            tgt = r.get("tgt_id", "?")
            desc = r.get("description", "relates to")
            lines.append(f"- {src} -> {tgt}: {desc}")
        parts.append("Relations:\n" + "\n".join(lines))

    chunks = data.get("chunks", [])
    if chunks:
        lines = []
        for c in chunks[:max_chunks]:
            content = c.get("content", "")
            if content:
                if len(content) > 500:
                    content = content[:500] + "..."
                lines.append(content)
        if lines:
            parts.append("Source context:\n" + "\n---\n".join(lines))

    return "\n\n".join(parts)


async def ingest_text(
    text: str,
    workspace: str,
    client: httpx.AsyncClient | None = None,
):
    should_close = False
    if client is None:
        client = httpx.AsyncClient()
        should_close = True

    try:
        resp = await client.post(
            f"{_lightrag_url}/documents/text",
            json={"text": text},
            headers={"LIGHTRAG-WORKSPACE": workspace},
            timeout=300.0,
        )
        resp.raise_for_status()
        return resp.json()
    finally:
        if should_close:
            await client.aclose()
