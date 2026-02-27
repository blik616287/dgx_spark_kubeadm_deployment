from tree_sitter import Parser, Node
from .languages import LANGUAGES
from .models import Entity, Relationship, ParseResult


def parse_file(file_path: str, content: str, language: str) -> ParseResult:
    lang = LANGUAGES.get(language)
    if not lang:
        raise ValueError(f"Unsupported language: {language}")

    parser = Parser(lang)
    tree = parser.parse(content.encode())

    entities: list[Entity] = []
    relationships: list[Relationship] = []

    # Add module entity
    module_name = file_path.rsplit("/", 1)[-1]
    entities.append(Entity(
        name=module_name,
        kind="module",
        file_path=file_path,
        line_start=1,
        line_end=content.count("\n") + 1,
    ))

    _extract(tree.root_node, content, file_path, language, module_name,
             entities, relationships)

    document = _build_document(file_path, language, entities, relationships, content)
    return ParseResult(
        file_path=file_path,
        language=language,
        document=document,
        entities=entities,
        relationships=relationships,
    )


# ── Extraction per language ─────────────────────────────────────────

_CLASS_TYPES = {
    "python": ["class_definition"],
    "javascript": ["class_declaration"],
    "typescript": ["class_declaration", "interface_declaration"],
    "go": ["type_declaration"],
    "rust": ["struct_item", "enum_item", "trait_item", "impl_item"],
    "java": ["class_declaration", "interface_declaration", "enum_declaration"],
    "c": ["struct_specifier"],
    "cpp": ["class_specifier", "struct_specifier"],
}

_FUNC_TYPES = {
    "python": ["function_definition"],
    "javascript": ["function_declaration", "arrow_function", "method_definition"],
    "typescript": ["function_declaration", "arrow_function", "method_definition"],
    "go": ["function_declaration", "method_declaration"],
    "rust": ["function_item"],
    "java": ["method_declaration", "constructor_declaration"],
    "c": ["function_definition"],
    "cpp": ["function_definition"],
}

_IMPORT_TYPES = {
    "python": ["import_statement", "import_from_statement"],
    "javascript": ["import_statement"],
    "typescript": ["import_statement"],
    "go": ["import_declaration"],
    "rust": ["use_declaration"],
    "java": ["import_declaration"],
    "c": ["preproc_include"],
    "cpp": ["preproc_include"],
}


def _extract(
    node: Node,
    source: str,
    file_path: str,
    language: str,
    parent_name: str,
    entities: list[Entity],
    relationships: list[Relationship],
):
    class_types = set(_CLASS_TYPES.get(language, []))
    func_types = set(_FUNC_TYPES.get(language, []))
    import_types = set(_IMPORT_TYPES.get(language, []))

    for child in node.children:
        ntype = child.type

        if ntype in class_types:
            name = _get_name(child, language)
            if not name:
                continue
            kind = "interface" if "interface" in ntype else "class"
            docstring = _get_docstring(child, language, source)
            entities.append(Entity(
                name=name,
                kind=kind,
                file_path=file_path,
                line_start=child.start_point[0] + 1,
                line_end=child.end_point[0] + 1,
                docstring=docstring,
                parent=parent_name,
            ))
            relationships.append(Relationship(
                source=parent_name, target=name, kind="contains",
            ))
            # Check inheritance
            _extract_inheritance(child, language, name, source, relationships)
            # Recurse into class body for methods
            _extract(child, source, file_path, language, name,
                     entities, relationships)

        elif ntype in func_types:
            name = _get_name(child, language)
            if not name:
                continue
            is_method = parent_name and any(
                e.kind in ("class", "interface") and e.name == parent_name
                for e in entities
            )
            kind = "method" if is_method else "function"
            sig = _get_signature(child, source)
            docstring = _get_docstring(child, language, source)
            entities.append(Entity(
                name=f"{parent_name}.{name}" if is_method else name,
                kind=kind,
                file_path=file_path,
                line_start=child.start_point[0] + 1,
                line_end=child.end_point[0] + 1,
                signature=sig,
                docstring=docstring,
                parent=parent_name,
            ))
            relationships.append(Relationship(
                source=parent_name, target=name, kind="contains",
            ))

        elif ntype in import_types:
            imp_text = source[child.start_byte:child.end_byte].strip()
            target = _parse_import_target(imp_text, language)
            if target:
                relationships.append(Relationship(
                    source=parent_name, target=target, kind="imports",
                ))

        else:
            # Recurse into other nodes (e.g., decorated_definition)
            if child.child_count > 0:
                _extract(child, source, file_path, language, parent_name,
                         entities, relationships)


def _get_name(node: Node, language: str) -> str | None:
    for child in node.children:
        if child.type in ("identifier", "type_identifier", "name"):
            return child.text.decode()
        if child.type == "type_spec":
            return _get_name(child, language)
    return None


def _get_signature(node: Node, source: str) -> str:
    start = node.start_byte
    # Find the body (block/compound_statement) and take text up to it
    for child in node.children:
        if child.type in ("block", "compound_statement", "statement_block",
                          "class_body", "field_declaration_list",
                          "declaration_list"):
            return source[start:child.start_byte].strip()
    # Fallback: first line
    text = source[start:node.end_byte]
    return text.split("\n")[0].strip()


def _get_docstring(node: Node, language: str, source: str) -> str | None:
    if language == "python":
        for child in node.children:
            if child.type == "block":
                for stmt in child.children:
                    if stmt.type == "expression_statement":
                        for expr in stmt.children:
                            if expr.type == "string":
                                text = expr.text.decode().strip("\"'")
                                return text[:200]
                        break
                break
    elif language in ("javascript", "typescript", "java", "c", "cpp", "go", "rust"):
        # Check for preceding comment
        prev = node.prev_sibling
        if prev and prev.type in ("comment", "block_comment", "line_comment"):
            return prev.text.decode().strip("/* \n")[:200]
    return None


def _extract_inheritance(
    node: Node, language: str, class_name: str, source: str,
    relationships: list[Relationship],
):
    if language == "python":
        for child in node.children:
            if child.type == "argument_list":
                for arg in child.children:
                    if arg.type == "identifier":
                        relationships.append(Relationship(
                            source=class_name,
                            target=arg.text.decode(),
                            kind="extends",
                        ))
    elif language in ("java", "typescript", "javascript"):
        for child in node.children:
            if child.type == "superclass":
                name = _get_name(child, language)
                if name:
                    relationships.append(Relationship(
                        source=class_name, target=name, kind="extends",
                    ))
            elif child.type == "super_interfaces":
                for iface in child.children:
                    if iface.type in ("type_identifier", "identifier"):
                        relationships.append(Relationship(
                            source=class_name,
                            target=iface.text.decode(),
                            kind="implements",
                        ))


def _parse_import_target(text: str, language: str) -> str | None:
    if language == "python":
        if text.startswith("from "):
            parts = text.split()
            return parts[1] if len(parts) > 1 else None
        elif text.startswith("import "):
            return text.replace("import ", "").split(",")[0].strip()
    elif language in ("javascript", "typescript"):
        if "from " in text:
            return text.split("from")[-1].strip().strip("\"';")
    elif language == "go":
        # import "fmt" or import ( "fmt" )
        for part in text.split('"'):
            if "/" in part or part.isalpha():
                return part
    elif language == "rust":
        return text.replace("use ", "").rstrip(";").split("::")[0]
    elif language == "java":
        return text.replace("import ", "").rstrip(";").strip()
    elif language in ("c", "cpp"):
        for ch in ("<", '"'):
            if ch in text:
                return text.split(ch)[1].split(">" if ch == "<" else '"')[0]
    return None


# ── Build natural language document ──────────────────────────────────

def _build_document(
    file_path: str,
    language: str,
    entities: list[Entity],
    relationships: list[Relationship],
    source: str,
) -> str:
    lines = [f"# Module: {file_path} ({language})\n"]

    imports = [r for r in relationships if r.kind == "imports"]
    if imports:
        lines.append("## Imports")
        for r in imports:
            lines.append(f"- {r.target}")
        lines.append("")

    classes = [e for e in entities if e.kind in ("class", "interface")]
    for cls in classes:
        keyword = "Interface" if cls.kind == "interface" else "Class"
        lines.append(f"## {keyword}: {cls.name}")
        lines.append(f"Defined at lines {cls.line_start}-{cls.line_end}.")

        extends = [r for r in relationships
                   if r.source == cls.name and r.kind in ("extends", "implements")]
        if extends:
            for r in extends:
                lines.append(f"{r.kind.capitalize()} {r.target}.")

        if cls.docstring:
            lines.append(f'Docstring: "{cls.docstring}"')
        lines.append("")

        methods = [e for e in entities
                   if e.kind == "method" and e.parent == cls.name]
        for m in methods:
            lines.append(f"### Method: {m.name}")
            if m.signature:
                lines.append(f"Signature: {m.signature}")
            lines.append(f"Defined at lines {m.line_start}-{m.line_end}.")
            if m.docstring:
                lines.append(f'Docstring: "{m.docstring}"')
            lines.append("")

    functions = [e for e in entities if e.kind == "function"]
    if functions:
        lines.append("## Functions")
        for f in functions:
            lines.append(f"### Function: {f.name}")
            if f.signature:
                lines.append(f"Signature: {f.signature}")
            lines.append(f"Defined at lines {f.line_start}-{f.line_end}.")
            if f.docstring:
                lines.append(f'Docstring: "{f.docstring}"')
            lines.append("")

    return "\n".join(lines)
