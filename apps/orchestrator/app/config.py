from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # NATS
    nats_url: str = "nats://nats:4222"

    # Redis
    redis_url: str = "redis://redis:6379/0"
    session_ttl_seconds: int = 7200

    # PostgreSQL
    pg_host: str = "postgresql"
    pg_port: int = 5432
    pg_user: str = "lightrag"
    pg_password: str = "graphrag-local-2024"
    pg_database: str = "lightrag"

    # LightRAG
    lightrag_url: str = "http://lightrag:9621"

    # Code Preprocessor (handles PDFs, code files via tree-sitter)
    preprocessor_url: str = "http://code-preprocessor:8090"

    # Embedding
    embed_url: str = "http://ollama-embed:11434"
    embed_model: str = "qwen3-embedding:0.6b"
    embed_dim: int = 1024

    # Backend LLMs
    qwen_backend_url: str = "http://qwen3-coder-next-predictor.llm-serving.svc.cluster.local:80"
    deepseek_backend_url: str = "http://deepseek-r1-distill-32b-predictor.llm-serving.svc.cluster.local:80"

    # Summarizer
    summarizer_url: str = "http://ollama-extract:11434"
    summarizer_model: str = "qwen3:8b"

    # Memory thresholds
    promote_after_turns: int = 10
    archival_after_turns: int = 20
    recall_top_k: int = 3
    archival_top_k: int = 3
