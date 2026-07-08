from fastapi import APIRouter
from . import payment_link

router = APIRouter()
router.include_router(payment_link.router, prefix="/payment_link", tags=["payment_link"])
