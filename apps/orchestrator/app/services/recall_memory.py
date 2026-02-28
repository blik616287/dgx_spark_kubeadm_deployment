from ..db import get_pool
from ..models import ChatMessage


async def store_message(session_id: str, message: ChatMessage):
    pool = get_pool()
    await pool.execute(
        """INSERT INTO orchestrator_messages (session_id, role, content)
           VALUES ($1, $2, $3)""",
        session_id, message.role, message.content,
    )


async def ensure_session(session_id: str, workspace: str, model: str):
    pool = get_pool()
    await pool.execute(
        """INSERT INTO orchestrator_sessions (id, workspace, model)
           VALUES ($1, $2, $3)
           ON CONFLICT (id) DO UPDATE SET updated_at = now()""",
        session_id, workspace, model,
    )


async def update_session_summary(
    session_id: str, summary: str, summary_vector: list[float]
):
    pool = get_pool()
    await pool.execute(
        """UPDATE orchestrator_sessions
           SET summary = $2, summary_vector = $3, updated_at = now()
           WHERE id = $1""",
        session_id, summary, summary_vector,
    )


async def search_similar_sessions(
    workspace: str,
    query_vector: list[float],
    top_k: int = 3,
    exclude_session_id: str | None = None,
) -> list[dict]:
    pool = get_pool()

    query = """
        SELECT id, summary, 1 - (summary_vector <=> $1::vector) as similarity
        FROM orchestrator_sessions
        WHERE workspace = $2
          AND summary IS NOT NULL
          AND summary_vector IS NOT NULL
    """
    params: list = [query_vector, workspace]

    if exclude_session_id:
        query += " AND id != $3"
        params.append(exclude_session_id)

    query += " ORDER BY summary_vector <=> $1::vector LIMIT $" + str(len(params) + 1)
    params.append(top_k)

    rows = await pool.fetch(query, *params)
    return [
        {"session_id": r["id"], "summary": r["summary"], "similarity": r["similarity"]}
        for r in rows
    ]


async def get_session_messages(session_id: str) -> list[dict]:
    pool = get_pool()
    rows = await pool.fetch(
        """SELECT role, content, created_at
           FROM orchestrator_messages
           WHERE session_id = $1
           ORDER BY created_at""",
        session_id,
    )
    return [dict(r) for r in rows]


async def get_session_info(session_id: str) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow(
        """SELECT id, workspace, model, created_at, updated_at, summary
           FROM orchestrator_sessions WHERE id = $1""",
        session_id,
    )
    return dict(row) if row else None


async def list_sessions(workspace: str | None = None) -> list[dict]:
    pool = get_pool()
    if workspace:
        rows = await pool.fetch(
            """SELECT s.id, s.workspace, s.model, s.created_at, s.updated_at, s.summary,
                      (SELECT count(*) FROM orchestrator_messages m WHERE m.session_id = s.id) as turn_count
               FROM orchestrator_sessions s
               WHERE s.workspace = $1
               ORDER BY s.updated_at DESC LIMIT 50""",
            workspace,
        )
    else:
        rows = await pool.fetch(
            """SELECT s.id, s.workspace, s.model, s.created_at, s.updated_at, s.summary,
                      (SELECT count(*) FROM orchestrator_messages m WHERE m.session_id = s.id) as turn_count
               FROM orchestrator_sessions s
               ORDER BY s.updated_at DESC LIMIT 50""",
        )
    return [dict(r) for r in rows]


async def delete_session(session_id: str):
    pool = get_pool()
    await pool.execute(
        "DELETE FROM orchestrator_sessions WHERE id = $1",
        session_id,
    )
