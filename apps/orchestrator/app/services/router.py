from ..config import Settings

_ROUTES: dict[str, tuple[str, str]] = {}


def init_routes(settings: Settings):
    global _ROUTES
    _ROUTES = {
        "qwen3-coder": (settings.qwen_backend_url, "qwen3-coder-next:q4_K_M"),
        "qwen3-coder-next": (settings.qwen_backend_url, "qwen3-coder-next:q4_K_M"),
        "deepseek-r1": (settings.deepseek_backend_url, "deepseek-r1:32b"),
        "deepseek": (settings.deepseek_backend_url, "deepseek-r1:32b"),
    }


def resolve(model_name: str) -> tuple[str, str]:
    route = _ROUTES.get(model_name)
    if not route:
        raise ValueError(
            f"Unknown model: {model_name}. Available: {list(_ROUTES.keys())}"
        )
    return route


def list_models() -> list[str]:
    seen = set()
    names = []
    for name, (url, _) in _ROUTES.items():
        if url not in seen:
            seen.add(url)
            names.append(name)
    return names
