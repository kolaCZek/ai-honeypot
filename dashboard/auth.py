"""HTTP Basic auth dependency for dashboard."""
from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic(auto_error=False)


def require_basic_auth(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(security),
) -> str:
    settings = request.app.state.settings
    cfg = settings.dashboard.basic_auth
    headers = {"WWW-Authenticate": 'Basic realm="dashboard"'}
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="auth required", headers=headers)
    user_ok = secrets.compare_digest(credentials.username.encode(), cfg.username.encode())
    pass_ok = secrets.compare_digest(credentials.password.encode(), cfg.password.encode())
    if not (user_ok and pass_ok):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="bad credentials", headers=headers)
    return credentials.username
