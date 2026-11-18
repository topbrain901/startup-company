from __future__ import annotations

from fastapi import APIRouter, Depends

from .auth import current_user
from .schemas import UserContext


router = APIRouter(tags=["users"])


@router.get("/me")
async def me(user: UserContext = Depends(current_user)):
    """The signed-in user and their role ("admin" or "user")."""
    return user
