from payment_platform.admin_service.api.routes.auth import router as auth_router
from payment_platform.admin_service.api.routes.dashboard import router as dashboard_router
from payment_platform.admin_service.api.routes.merchants import router as merchants_router
from payment_platform.admin_service.api.routes.support import router as support_router
from payment_platform.admin_service.api.routes.admin_users import router as admin_users_router
from payment_platform.admin_service.api.routes.alerts import router as alerts_router

__all__ = [
    "auth_router",
    "dashboard_router",
    "merchants_router",
    "support_router",
    "admin_users_router",
    "alerts_router",
]
