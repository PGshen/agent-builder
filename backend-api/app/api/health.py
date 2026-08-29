from datetime import datetime, timezone

from fastapi import APIRouter, Response, status

from app.db import check_database_connection

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(response: Response) -> dict:
    db_connected = await check_database_connection()
    overall_status = "ok" if db_connected else "degraded"
    if not db_connected:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": overall_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dependencies": {
            "database": {"connected": db_connected},
        },
    }
