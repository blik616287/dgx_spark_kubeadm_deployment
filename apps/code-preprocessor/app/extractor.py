import re
import logging

from .models import CodeBlock
from .languages import EXTENSIONS

logger = logging.getLogger("code-preprocessor.extractor")

# Map common markdown language tags to tree-sitter language names
_TAG_MAP = {
    "python": "python", "py": "python", "python3": "python",
    "javascript": "javascript", "js": "javascript", "jsx": "javascript",
    "typescript": "typescript", "ts": "typescript", "tsx": "typescript",
    "go": "go", "golang": "go",
    "rust": "rust", "rs": "rust",
    "java": "java",
    "c": "c",
    "cpp": "cpp", "c++": "cpp", "cxx": "cpp", "cc": "cpp",
    "h": "c", "hpp": "cpp",
}

# Regex for fenced code blocks: ```lang\n...\n```
_CODE_BLOCK_RE = re.compile(
    r"```(\w*)\s*\n(.*?)```",
    re.DOTALL,
)

# Pattern to detect code regions in plain text (e.g., from PDFs)
# Looks for blocks starting with common code indicators
_CODE_REGION_RE = re.compile(
    r"(?:^|\n)"
    r"("
    r"(?:#include\b[^\n]*\n)"      # starts with #include
    r"(?:[^\n]*\n)*?"               # followed by more lines
    r"(?:.*\}[;\s]*\n?)"           # ending with a closing brace
    r")",
    re.MULTILINE,
)


def pdf_to_chunks(content: bytes, pages_per_chunk: int = 50) -> list[str]:
    """Extract text from PDF, split into page-grouped chunks.

    Returns a list of text strings, each covering up to pages_per_chunk pages.
    All pages are processed — no truncation.
    """
    import io
    import pdfplumber

    chunks = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        total = len(pdf.pages)
        logger.info(f"Extracting text from all {total} pages in chunks of {pages_per_chunk}")
        for start in range(0, total, pages_per_chunk):
            end = min(start + pages_per_chunk, total)
            text_parts = []
            for page in pdf.pages[start:end]:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
            if text_parts:
                chunks.append("\n\n".join(text_parts))
    return chunks


def pdf_to_text(content: bytes) -> str:
    """Extract all text from PDF as a single string."""
    return "\n\n".join(pdf_to_chunks(content))


def extract_code_blocks(text: str) -> list[CodeBlock]:
    """Extract code blocks from markdown or plain text content."""
    blocks = []

    # 1. Try fenced code blocks (markdown)
    for i, match in enumerate(_CODE_BLOCK_RE.finditer(text)):
        tag = match.group(1).strip().lower()
        code = match.group(2).strip()

        if not code or len(code) < 10:
            continue

        language = _TAG_MAP.get(tag)
        if not language and tag:
            language = EXTENSIONS.get(f".{tag}")
        if not language:
            language = detect_language_from_content(code)

        blocks.append(CodeBlock(language=language, code=code, index=i))

    # 2. If no fenced blocks found, try extracting code from plain text
    if not blocks:
        blocks = _extract_code_from_plaintext(text)

    return blocks


def _extract_code_from_plaintext(text: str) -> list[CodeBlock]:
    """Extract code regions from plain text (e.g., PDF text extraction).

    Uses brace-counting to find complete code blocks that start with
    recognizable code patterns.
    """
    blocks = []
    lines = text.split("\n")
    i = 0
    block_idx = 0

    while i < len(lines):
        line = lines[i].strip()

        # Detect start of a code region
        if _is_code_start(line):
            code_lines = []
            brace_depth = 0
            found_brace = False
            j = i

            # Collect lines until we close all braces
            while j < len(lines) and j - i < 200:  # Max 200 lines per block
                l = lines[j]
                code_lines.append(l)
                brace_depth += l.count("{") - l.count("}")

                if "{" in l:
                    found_brace = True

                # Block ends when braces balance and we've seen at least one
                if found_brace and brace_depth <= 0:
                    break
                j += 1

            code = "\n".join(code_lines).strip()
            if len(code) >= 20 and found_brace:
                language = detect_language_from_content(code)
                if language:
                    blocks.append(CodeBlock(
                        language=language, code=code, index=block_idx
                    ))
                    block_idx += 1
                    i = j + 1
                    continue
        i += 1

    return blocks


def _is_code_start(line: str) -> bool:
    """Check if a line looks like the start of a code block."""
    patterns = [
        r"^#include\b",
        r"^(int|void|char|float|double|bool|auto|class|struct|template)\s+\w+",
        r"^(public|private|protected)\s*:",
        r"^(def|class)\s+\w+",
        r"^fn\s+\w+",
        r"^func\s+\w+",
        r"^(function|const|let|var)\s+\w+",
        r"^import\s+",
        r"^package\s+",
        r"^using\s+namespace\b",
    ]
    return any(re.match(p, line) for p in patterns)


def detect_language_from_content(code: str) -> str | None:
    """Heuristic language detection from code content."""
    lines = code.split("\n", 20)
    sample = "\n".join(lines)

    if "#include" in sample:
        if "iostream" in sample or "std::" in sample or "class " in sample or "cout" in sample:
            return "cpp"
        return "c"

    if re.search(r"\bdef \w+\(.*\)\s*:", sample):
        return "python"
    if "import " in lines[0] and "java." not in sample:
        return "python"

    if re.search(r"\bfn \w+", sample) and ("::" in sample or "let " in sample):
        return "rust"

    if re.search(r"\bfunc \w+", sample) and ("package " in sample or "fmt." in sample):
        return "go"

    if "public class " in sample or "import java." in sample:
        return "java"

    if re.search(r"\b(const|let|var)\b", sample) and ("=>" in sample or "function " in sample):
        return "javascript"

    # Generic C/C++ (semicolons + braces + type keywords)
    if re.search(r"\b(int|void|char|float|double)\s+\w+\s*\(", sample):
        if "cout" in sample or "cin" in sample or "::" in sample or "class " in sample:
            return "cpp"
        return "c"

    return None
