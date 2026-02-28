from fastapi import APIRouter

from ..models import ModelInfo, ModelListResponse
from ..services.router import list_models

router = APIRouter()


@router.get("/v1/models")
async def get_models():
    names = list_models()
    return ModelListResponse(
        data=[ModelInfo(id=name) for name in names],
    )
