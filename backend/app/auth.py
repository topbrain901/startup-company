from __future__ import annotations

import hashlib
import time

import httpx
from fastapi import Depends, HTTPException, Request, status

from .config import Settings, get_settings
from .schemas import UserContext
from .supabase import SupabaseAPI, eq, http_client


CACHE_SECONDS = 60
_cache: dict[str, tuple[float, UserContext]] = {}


def forget_user(user_id: str) -> None:
    """Drop cached sessions for a user (after a role change)."""
    for key in [key for key, (_, user) in _cache.items() if user.id == user_id]:
        _cache.pop(key, None)


async def _verify_token(token: str, settings: Settings) -> dict:
    try:
        response = await http_client().get(
            f"{settings.supabase_url.rstrip('/')}/auth/v1/user",
            headers={
                "apikey": settings.supabase_anon_key or settings.supabase_service_role_key,
                "Authorization": f"Bearer {token}",
            },
        )
    except httpx.HTTPError as exc:
        host = httpx.URL(settings.supabase_url).host
        reason = str(exc) or exc.__class__.__name__
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"The API could not reach Supabase Auth at {host} ({reason}). Check SUPABASE_URL in backend/.env "
            "and the server's internet connection.",
        ) from exc
    if response.status_code != 200:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")
    return response.json()


async def _profile(api: SupabaseAPI, user_id: str, email: str, settings: Settings) -> dict:
    rows, _ = await api.select("profiles", f"select=id,email,role&id={eq(user_id)}&limit=1")
    wants_admin = email.lower() in settings.admin_email_set
    if not rows:
        created = await api.insert(
            "profiles", {"id": user_id, "email": email, "role": "admin" if wants_admin else "user"}, upsert="id"
        )
        return created[0]
    profile = rows[0]
    if wants_admin and profile.get("role") != "admin":
        profile = (await api.update("profiles", f"id={eq(user_id)}", {"role": "admin"}))[0]
    return profile


async def current_user(request: Request, settings: Settings = Depends(get_settings)) -> UserContext:
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    token = authorization.removeprefix("Bearer ").strip()
    key = hashlib.sha256(token.encode()).hexdigest()
    cached = _cache.get(key)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    auth_user = await _verify_token(token, settings)
    email = auth_user.get("email") or ""
    profile = await _profile(SupabaseAPI(settings), auth_user["id"], email, settings)
    user = UserContext(id=auth_user["id"], email=email, role=profile["role"])
    if len(_cache) > 5000:
        _cache.clear()
    _cache[key] = (time.monotonic() + CACHE_SECONDS, user)
    return user


async def admin_user(user: UserContext = Depends(current_user)) -> UserContext:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required")
    return user
