from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.services.admin_session import (
    COOKIE_NAME,
    SESSION_TTL,
    create_session,
    delete_session,
    is_password_required,
    validate_session,
    verify_password,
)

router = APIRouter()


class LoginRequest(BaseModel):
    password: str


@router.get("/status")
async def admin_status(request: Request):
    required = is_password_required()
    authenticated = False
    if required:
        token = request.cookies.get(COOKIE_NAME)
        if token:
            authenticated = validate_session(token)
    else:
        authenticated = True
    return {"required": required, "authenticated": authenticated}


@router.post("/login")
async def admin_login(body: LoginRequest, response: Response):
    if not is_password_required():
        return {"success": True}

    if not verify_password(body.password):
        raise HTTPException(status_code=401, detail="Invalid password")

    token = create_session()
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/api",
        max_age=SESSION_TTL,
    )
    return {"success": True}


@router.post("/logout")
async def admin_logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        delete_session(token)
    response.delete_cookie(key=COOKIE_NAME, path="/api")
    return {"success": True}
