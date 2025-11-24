from datetime import datetime, timedelta, timezone
from typing import Optional, Union, Any
from jose import JWTError, jwt
from passlib.context import CryptContext
from uuid import UUID
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


# 암호화 컨텍스트 설정
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """평문 비밀번호와 해시된 비밀번호 비교"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """비밀번호 해싱"""
    return pwd_context.hash(password)


def create_access_token(
    subject: Union[str, Any], expires_delta: Optional[timedelta] = None
) -> str:
    """
    Access Token 생성
    subject -> 사용자 식별자
    expires_delta -> 만료 시간 커스텀 설정
    """
    if expires_delta:
        # python 최신 버전에서는 utcnow -> 사용 권장 안함
        # 타임존 정보가 없는 시간을 반환하여 나중에 타임존이 있는 시간과 비교할 때 오류 유발 가능성 존재
        # datetime.now를 사용해 명시적으로 UTC 타임존 지정해야 함
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

    # sub(subject) -> 명시적으로 포함, type을 통해 토큰 용도 구분
    to_encode = {"sub": str(subject), "exp": expire, "type": "access"}

    encoded_jwt = jwt.encode(
        to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def create_refresh_token(user_id: UUID) -> str:
    """Refresh Token 생성"""
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )

    to_encode = {"sub": str(user_id), "exp": expire, "type": "refresh"}
    encoded_jwt = jwt.encode(
        to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def decode_token(token: str) -> Optional[dict]:
    """
    토큰 디코딩 및 검증
    return payload dict or None(유효하지 않은 경우)
    """
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError as e:
        logger.error(f"JWT error: {e}")
        return None
