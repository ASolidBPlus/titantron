from fastapi import HTTPException, Request

from app.services.admin_session import COOKIE_NAME, is_password_required, validate_session


async def require_admin(request: Request) -> None:
    if not is_password_required():
        return
    token = request.cookies.get(COOKIE_NAME)
    if not token or not validate_session(token):
        raise HTTPException(status_code=401, detail="Admin authentication required")
