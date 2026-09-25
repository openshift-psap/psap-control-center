import secrets
import base64
import hashlib
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from jose import JWTError, jwt
from pydantic import BaseModel

from app.core.auth import (
    validate_credentials,
    create_session_token,
    get_current_user,
    COOKIE_NAME,
)
from app.core.config import settings
from app.utils.logger import create_logger

router = APIRouter()
logger = create_logger("AuthAPI")

OAUTH_STATE_COOKIE = "google_oauth_state"
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(body: LoginRequest, request: Request):
    if not settings.LOCAL_LOGIN_ENABLED:
        raise HTTPException(status_code=404, detail="Local login is disabled")
    user = validate_credentials(body.username, body.password)
    if user is None:
        logger.warn(f"Failed login attempt for user: {body.username}")
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid credentials"},
        )

    token = create_session_token(
        user["username"],
        user["role"],
        subject=f"local:{user['username']}",
        name=user["username"],
        auth_provider="local",
    )

    is_secure = request.url.scheme == "https" or \
        request.headers.get("x-forwarded-proto") == "https"

    response = JSONResponse(content={
        "username": user["username"],
        "email": None,
        "name": user["username"],
        "auth_provider": "local",
        "role": user["role"],
    })
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=is_secure,
        samesite="lax",
        path="/api",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )

    logger.info(f"User '{user['username']}' logged in (role={user['role']})")
    return response


def _secure_request(request: Request) -> bool:
    return request.url.scheme == "https" or \
        request.headers.get("x-forwarded-proto") == "https"


def _session_response(user: dict, request: Request) -> JSONResponse:
    token = create_session_token(
        user["username"],
        user["role"],
        subject=user["subject"],
        email=user.get("email"),
        name=user.get("name"),
        auth_provider=user.get("auth_provider", "google"),
    )
    response = JSONResponse(content={
        key: user.get(key)
        for key in ("username", "email", "name", "auth_provider", "role")
    })
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=_secure_request(request),
        samesite="lax",
        path="/api",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    return response


@router.get("/config")
async def auth_config():
    """Public feature flags needed to render the sign-in choices."""
    return {
        "google_enabled": settings.GOOGLE_OAUTH_ENABLED,
        "local_login_enabled": settings.LOCAL_LOGIN_ENABLED,
    }


@router.get("/google/login")
async def google_login(request: Request):
    if not settings.GOOGLE_OAUTH_ENABLED:
        raise HTTPException(status_code=404, detail="Google login is disabled")

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b"=").decode()
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    state_token = jwt.encode(
        {
            "state": state,
            "nonce": nonce,
            "code_verifier": code_verifier,
            "type": "google_oauth",
            "exp": expires,
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
        "hd": settings.GOOGLE_ALLOWED_DOMAIN,
    }
    response = RedirectResponse(
        "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    )
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=state_token,
        httponly=True,
        secure=_secure_request(request),
        samesite="lax",
        path="/api",
        max_age=600,
    )
    return response


async def _verify_google_id_token(id_token: str, expected_nonce: str) -> dict:
    try:
        header = jwt.get_unverified_header(id_token)
    except JWTError as exc:
        raise HTTPException(401, "Google returned an invalid ID token") from exc

    async with httpx.AsyncClient(timeout=10.0) as client:
        jwks_response = await client.get("https://www.googleapis.com/oauth2/v3/certs")
    if jwks_response.status_code != 200:
        raise HTTPException(502, "Unable to validate Google identity")

    key = next(
        (item for item in jwks_response.json().get("keys", []) if item.get("kid") == header.get("kid")),
        None,
    )
    if key is None:
        raise HTTPException(401, "Google signing key was not found")

    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=settings.GOOGLE_CLIENT_ID,
            options={"verify_iss": False},
        )
    except JWTError as exc:
        raise HTTPException(401, "Google identity verification failed") from exc

    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise HTTPException(401, "Google identity issuer is invalid")
    if not secrets.compare_digest(str(claims.get("nonce", "")), expected_nonce):
        raise HTTPException(401, "Google login nonce is invalid")
    if claims.get("email_verified") is not True:
        raise HTTPException(403, "A verified organization email is required")
    if claims.get("hd", "").lower() != settings.GOOGLE_ALLOWED_DOMAIN.lower():
        raise HTTPException(403, "This Google Workspace organization is not allowed")
    return claims


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str = Query(..., min_length=1),
    state: str = Query(..., min_length=1),
):
    if not settings.GOOGLE_OAUTH_ENABLED:
        raise HTTPException(status_code=404, detail="Google login is disabled")

    state_token = request.cookies.get(OAUTH_STATE_COOKIE)
    if not state_token:
        raise HTTPException(401, "Google login session expired; please try again")
    try:
        state_claims = jwt.decode(
            state_token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
    except JWTError as exc:
        raise HTTPException(401, "Google login session is invalid") from exc
    if state_claims.get("type") != "google_oauth" or not secrets.compare_digest(
        str(state_claims.get("state", "")), state
    ):
        raise HTTPException(401, "Google login state is invalid")

    async with httpx.AsyncClient(timeout=10.0) as client:
        token_response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
                "code_verifier": state_claims["code_verifier"],
            },
        )
    if token_response.status_code != 200:
        logger.warn("Google authorization-code exchange failed")
        raise HTTPException(401, "Google login could not be completed")
    id_token = token_response.json().get("id_token")
    if not id_token:
        raise HTTPException(401, "Google did not return an identity token")

    claims = await _verify_google_id_token(id_token, state_claims["nonce"])
    email = claims["email"].lower()
    admin_emails = {
        item.strip().lower()
        for item in settings.GOOGLE_ADMIN_EMAILS.split(",")
        if item.strip()
    }
    user = {
        "subject": f"google:{claims['sub']}",
        "username": email,
        "email": email,
        "name": claims.get("name") or email,
        "auth_provider": "google",
        "role": "admin" if email in admin_emails else "user",
    }
    response = _session_response(user, request)
    response.delete_cookie(key=OAUTH_STATE_COOKIE, path="/api")
    logger.info(f"Google user logged in: {email} (role={user['role']})")
    return response


@router.post("/logout")
async def logout():
    response = JSONResponse(content={"detail": "Logged out"})
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/api",
    )
    return response


@router.get("/me")
async def me(request: Request):
    user = get_current_user(request)
    if user is None:
        return JSONResponse(
            status_code=401,
            content={"detail": "Not authenticated"},
        )
    return {
        key: user.get(key)
        for key in ("username", "email", "name", "auth_provider", "role")
    }
