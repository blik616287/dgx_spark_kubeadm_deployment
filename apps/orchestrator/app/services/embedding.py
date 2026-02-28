import httpx

_embed_url: str = ""
_embed_model: str = ""


def init_embedding(url: str, model: str):
    global _embed_url, _embed_model
    _embed_url = url
    _embed_model = model


async def embed_text(text: str, client: httpx.AsyncClient | None = None) -> list[float]:
    should_close = False
    if client is None:
        client = httpx.AsyncClient()
        should_close = True

    try:
        resp = await client.post(
            f"{_embed_url}/api/embed",
            json={"model": _embed_model, "input": text},
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["embeddings"][0]
    finally:
        if should_close:
            await client.aclose()
