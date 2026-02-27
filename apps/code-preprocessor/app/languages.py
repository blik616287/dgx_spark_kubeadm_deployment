import tree_sitter_python
import tree_sitter_javascript
import tree_sitter_typescript
import tree_sitter_go
import tree_sitter_rust
import tree_sitter_java
import tree_sitter_c
import tree_sitter_cpp
from tree_sitter import Language

LANGUAGES: dict[str, Language] = {}
EXTENSIONS: dict[str, str] = {}


def _get_language(mod, name: str):
    """Get the language function from a tree-sitter module.

    Some modules (like typescript) export language_typescript() / language_tsx()
    instead of language().
    """
    if hasattr(mod, "language"):
        return mod.language()
    # tree_sitter_typescript exports language_typescript and language_tsx
    lang_func = getattr(mod, f"language_{name}", None)
    if lang_func:
        return lang_func()
    raise AttributeError(f"Cannot find language function in {mod.__name__}")


def _init():
    specs = [
        (tree_sitter_python, "python", [".py"]),
        (tree_sitter_javascript, "javascript", [".js", ".jsx", ".mjs", ".cjs"]),
        (tree_sitter_typescript, "typescript", [".ts", ".tsx"]),
        (tree_sitter_go, "go", [".go"]),
        (tree_sitter_rust, "rust", [".rs"]),
        (tree_sitter_java, "java", [".java"]),
        (tree_sitter_c, "c", [".c", ".h"]),
        (tree_sitter_cpp, "cpp", [".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx"]),
    ]
    for mod, name, exts in specs:
        LANGUAGES[name] = Language(_get_language(mod, name))
        for ext in exts:
            EXTENSIONS[ext] = name


_init()


def detect_language(file_path: str) -> str | None:
    for ext, lang in EXTENSIONS.items():
        if file_path.endswith(ext):
            return lang
    return None
