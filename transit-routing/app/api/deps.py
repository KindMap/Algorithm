from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from uuid import UUID

from app.auth.security import decode_token
from app.services.auth_service import AuthService
from app.models.domain import User

# auto_error=False -> token이 없어도 에러를 내지 않고 None을 반환
# => 선택적 인증을 위해 필수
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

async def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> Optional[User]:
    if token is None:
        return None
    
    try:
        payload = decode_token(token)
        user_id: str = payload.get("sub")

        if payload.get("type") != "access":
            return None

        user_id_str: str = payload.get("sub")
        if user_id_str is None:
            return None
        
        user = AuthService.get_user_by_id(UUID(user_id_str))
        return user
    
    except(JWTError,ValueError):
        return None # error 발생 X

# error 반환 -> 로그인이 필수인 엔드포인트에서 사용
async def get_current_active_user(current_user: Optional[User] = Depends(get_current_user)) -> User:
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )

    return current_user