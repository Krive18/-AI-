from fastapi import APIRouter, Request

from app.core.errors import AppError
from app.modules.account.routes import router as account_router
from app.modules.admin.routes import router as admin_router
from app.modules.auth.routes import router as auth_router
from app.modules.cost.routes import router as cost_router
from app.modules.imagegen.routes import router as imagegen_router
from app.modules.logs.routes import router as logs_router
from app.modules.project.routes import router as project_router
from app.modules.provider.routes import router as provider_router
from app.modules.videogen.routes import router as videogen_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(account_router)
router.include_router(admin_router)
router.include_router(provider_router)
router.include_router(cost_router)
router.include_router(logs_router)
router.include_router(project_router)
router.include_router(imagegen_router)
router.include_router(videogen_router)


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(request: Request) -> dict[str, str]:
    try:
        await request.app.state.database_manager.ping()
        await request.app.state.redis_manager.ping()
    except Exception as exc:
        raise AppError(
            code="SERVICE_NOT_READY",
            message="Service is not ready",
            status_code=503,
        ) from exc
    return {"status": "ok"}
