import os
import logging
from pathlib import Path

import httpx
from fastapi import FastAPI, UploadFile, File, Header, HTTPException

from .models import ParseResult, IngestResponse
from .languages import detect_language
from .parser import parse_file
from .extractor import pdf_to_text, pdf_to_chunks, extract_code_blocks

logger = logging.getLogger("code-preprocessor")

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
                # Extract text and send to LightRAG
                try:
                    if ext == ".pdf":
                        pages_per_chunk = 50
                        chunks = pdf_to_chunks(content, pages_per_chunk)
                        logger.info(
                            f"PDF {file_path}: {len(chunks)} chunks to ingest"
                        )
                        for ci, chunk in enumerate(chunks):
                            page_start = ci * pages_per_chunk + 1
                            page_end = (ci + 1) * pages_per_chunk
                            label = f"{file_path} (pages {page_start}-{page_end})"
                            resp = await client.post(
                                f"{LIGHTRAG_URL}/documents/text",
                                json={"text": f"# {label}\n\n{chunk}"},
                                headers={"LIGHTRAG-WORKSPACE": x_workspace},
                            )
                            resp.raise_for_status()
                            documents_sent += 1
                    else:
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

                # Extract code blocks and parse with tree-sitter
                try:
                    if ext == ".pdf":
                        md_text = pdf_to_text(content)
                    else:
                        md_text = content.decode("utf-8", errors="replace")

                    code_blocks = extract_code_blocks(md_text)
                    for block in code_blocks:
                        if not block.language:
                            continue
                        lang_ext = {
                            "python": ".py", "javascript": ".js",
                            "typescript": ".ts", "go": ".go",
                            "rust": ".rs", "java": ".java",
                            "c": ".c", "cpp": ".cpp",
                        }.get(block.language, "")
                        synthetic_name = f"{file_path}:block_{block.index}{lang_ext}"
                        result = parse_file(synthetic_name, block.code, block.language)
                        resp = await client.post(
                            f"{LIGHTRAG_URL}/documents/text",
                            json={"text": result.document},
                            headers={"LIGHTRAG-WORKSPACE": x_workspace},
                        )
                        resp.raise_for_status()
                        documents_sent += 1
                        logger.info(
                            f"Extracted code block {block.index} ({block.language}) "
                            f"from {file_path}: {len(result.entities)} entities"
                        )
                except Exception as e:
                    errors.append(f"{file_path} (code extraction): {e}")
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
