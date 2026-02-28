from pydantic import BaseModel


class Entity(BaseModel):
    name: str
    kind: str  # module, class, function, method, interface
    file_path: str
    line_start: int
    line_end: int
    signature: str | None = None
    docstring: str | None = None
    parent: str | None = None


class Relationship(BaseModel):
    source: str
    target: str
    kind: str  # contains, calls, imports, extends, implements


class ParseResult(BaseModel):
    file_path: str
    language: str
    document: str
    entities: list[Entity]
    relationships: list[Relationship]


class CodeBlock(BaseModel):
    language: str | None
    code: str
    index: int


class IngestRequest(BaseModel):
    workspace: str = "default"
    lightrag_url: str = "http://lightrag:9621"


class IngestResponse(BaseModel):
    workspace: str
    files_processed: int
    documents_sent: int
    errors: list[str]
