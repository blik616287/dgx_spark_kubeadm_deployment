from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # NATS
    nats_url: str = "nats://nats:4222"

    # PostgreSQL
    pg_host: str = "postgresql"
    pg_port: int = 5432
    pg_user: str = "lightrag"
    pg_password: str = "graphrag-local-2024"
    pg_database: str = "lightrag"

    # Code Preprocessor
    preprocessor_url: str = "http://code-preprocessor:8090"

    # Worker config
    max_redeliveries: int = 3
    ack_wait_seconds: int = 600
    batch_size: int = 20
