from fastapi import APIRouter, HTTPException, Query

from ..models import SessionInfo
from ..services import recall_memory, working_memory

router = APIRouter()


@router.get("/v1/sessions")
async def list_sessions(workspace: str | None = Query(default=None)):
    sessions = await recall_memory.list_sessions(workspace)
    return {
        "sessions": [
            SessionInfo(
                id=s["id"],
                workspace=s["workspace"],
                model=s["model"],
                turn_count=s.get("turn_count", 0),
                created_at=str(s["created_at"]),
                updated_at=str(s["updated_at"]),
                summary=s.get("summary"),
            )
            for s in sessions
        ]
    }


@router.delete("/v1/sessions/{session_id}")
async def delete_session(session_id: str):
    info = await recall_memory.get_session_info(session_id)
    if not info:
        raise HTTPException(404, f"Session {session_id} not found")

    await working_memory.delete_session(session_id)
    await recall_memory.delete_session(session_id)

    return {"deleted": session_id}
