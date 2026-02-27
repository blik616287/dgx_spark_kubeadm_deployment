import os
from pathlib import Path

import httpx
from fastapi import FastAPI, UploadFile, File, Header, HTTPException

from .models import ParseResult, IngestResponse
from .languages import detect_language
from .parser import parse_file

app = FastAPI(title="Code Preprocessor", version="0.1.0")

LIGHTRAG_URL = os.environ.get("LIGHTRAG_URL", "http://lightrag:9621")

# File extensions handled by tree-sitter
CODE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
    ".go", ".rs", ".java", ".c", ".h", ".cpp", ".cc", ".cxx",
    ".hpp", ".hh", ".hxx",
}

# File extensions forwarded directly to LightRAG
DOC_EXTENSIONS = {".pdf", ".md", ".txt", ".rst", ".html", ".htm"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/parse", response_model=ParseResult)
async def parse(file: UploadFile = File(...)):
    """Parse a single code file with tree-sitter and return structured document."""
    content = (await file.read()).decode("utf-8", errors="replace")
    file_path = file.filename or "unknown"
    language = detect_language(file_path)
    if not language:
        raise HTTPException(400, f"Unsupported file type: {file_path}")
    return parse_file(file_path, content, language)


@app.post("/parse/batch", response_model=list[ParseResult])
async def parse_batch(files: list[UploadFile] = File(...)):
    """Parse multiple code files with tree-sitter."""
    results = []
    for f in files:
        content = (await f.read()).decode("utf-8", errors="replace")
        file_path = f.filename or "unknown"
        language = detect_language(file_path)
        if language:
            results.append(parse_file(file_path, content, language))
    return results


@app.post("/ingest", response_model=IngestResponse)
async def ingest(
    files: list[UploadFile] = File(...),
    x_workspace: str = Header(default="default"),
):
    """Unified ingestion gateway.

    Code files are parsed with tree-sitter then sent to LightRAG.
    Document files are forwarded directly to LightRAG.
    """
    errors: list[str] = []
    documents_sent = 0

    async with httpx.AsyncClient(timeout=300) as client:
        for f in files:
            file_path = f.filename or "unknown"
            ext = Path(file_path).suffix.lower()
            content = await f.read()

            if ext in CODE_EXTENSIONS:
                # Parse with tree-sitter, send structured text to LightRAG
                try:
                    text = content.decode("utf-8", errors="replace")
                    language = detect_language(file_path)
                    if not language:
                        errors.append(f"{file_path}: unsupported language")
                        continue
                    result = parse_file(file_path, text, language)
                    resp = await client.post(
                        f"{LIGHTRAG_URL}/documents/text",
                        json={"text": result.document},
                        headers={"LIGHTRAG-WORKSPACE": x_workspace},
                    )
                    resp.raise_for_status()
                    documents_sent += 1
                except Exception as e:
                    errors.append(f"{file_path}: {e}")

            elif ext in DOC_EXTENSIONS:
                # Forward directly to LightRAG upload
                try:
                    resp = await client.post(
                        f"{LIGHTRAG_URL}/documents/upload",
                        files={"file": (file_path, content)},
                        headers={"LIGHTRAG-WORKSPACE": x_workspace},
                    )
                    resp.raise_for_status()
                    documents_sent += 1
                except Exception as e:
                    errors.append(f"{file_path}: {e}")
            else:
                # Try as text
                try:
                    text = content.decode("utf-8", errors="replace")
                    resp = await client.post(
                        f"{LIGHTRAG_URL}/documents/text",
                        json={"text": text},
                        headers={"LIGHTRAG-WORKSPACE": x_workspace},
                    )
                    resp.raise_for_status()
                    documents_sent += 1
                except Exception as e:
                    errors.append(f"{file_path}: {e}")

    return IngestResponse(
        workspace=x_workspace,
        files_processed=len(files),
        documents_sent=documents_sent,
        errors=errors,
    )
