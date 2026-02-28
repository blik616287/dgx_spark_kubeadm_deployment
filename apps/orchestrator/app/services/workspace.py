import re

from ..models import ChatCompletionRequest


def derive_workspace(request: ChatCompletionRequest, header_workspace: str | None = None) -> str:
    """Derive workspace name with precedence:
    1. Explicit workspace field in request body
    2. X-Workspace header
    3. Extracted from system prompt
    4. Default to 'default'
    """
    if request.workspace:
        return _sanitize(request.workspace)

    if header_workspace:
        return _sanitize(header_workspace)

    for msg in request.messages:
        if msg.role == "system" and msg.content:
            match = re.search(
                r'(?:workspace|project)\s*[:=]\s*["\']?(\S+)["\']?',
                msg.content,
                re.IGNORECASE,
            )
            if match:
                return _sanitize(match.group(1))

    return "default"


def _sanitize(name: str) -> str:
    cleaned = re.sub(r'[^a-zA-Z0-9_-]', '-', name.strip())
    return cleaned[:64] or "default"
