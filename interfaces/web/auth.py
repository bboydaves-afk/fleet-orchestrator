"""JWT authentication for Fleet Orchestrator web dashboard."""

import os
import logging
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger("fleet.web.auth")

security = HTTPBearer(auto_error=False)

SECRET_KEY = os.environ.get("FLEET_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "FLEET_SECRET_KEY not set. "
        "Populate fleet_orchestrator/.env and ensure load_dotenv() runs before import."
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24
DEFAULT_USERNAME = os.environ.get("FLEET_ADMIN_USERNAME", "admin")
DEFAULT_PASSWORD = os.environ.get("FLEET_ADMIN_PASSWORD", "admin")


def create_access_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> str:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub", "")
    except JWTError:
        return ""


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    username = verify_token(credentials.credentials)
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return username
