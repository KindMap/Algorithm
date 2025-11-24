from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID
from jose import JWTError

from app.models.domain import User
from app.auth.security import (
    verify_password,
    get_password_hash,
    decode_token,
)
from app.db.database import get_db_connection
from app.core.config import settings


class AuthService:
    @staticmethod
    def create_user(
        email: str,
        password: str,
        username: Optional[str],
        disability_type: Optional[str],
    ) -> User:
        password_hash = get_password_hash(password)

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (email, password_hash, username, disability_type)
                    VALUES (%s, %s, %s, %s)
                    RETURNING user_id, email, username, disability_type, is_active, created_at
                    """,
                    (email, password_hash, username, disability_type),
                )

                row = cur.fetchone()
                conn.commit()

                return User(
                    user_id=row[0],
                    email=row[1],
                    username=row[2],
                    disability_type=row[3],
                    is_active=row[4],
                    created_at=row[5],
                    last_login=datetime.now(timezone.utc),
                )

    @staticmethod
    def authenticate_user(email: str, password: str) -> Optional[User]:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT user_id, email, password_hash, username, disability_type, is_active, created_at, last_login
                    FROM users WHERE email = %s
                """,
                    (email,),
                )

                row = cur.fetchone()
                if not row or not verify_password(password, row[2]):
                    return None
                cur.execute(
                    "UPDATE users SET last_login = NOW() WHERE user_id = %s", (row[0],)
                )
                conn.commit()

                return User(
                    user_id=row[0],
                    email=row[1],
                    username=row[3],
                    disability_type=row[4],
                    is_active=row[5],
                    created_at=row[6],
                    last_login=datetime.now(timezone.utc),
                )

    @staticmethod
    def verify_refresh_token(token: str) -> Optional[UUID]:
        try:
            payload = decode_token(token)

            # decode 실패 처리 추가
            if payload is None:
                return None

            # Access Token 도용 방지 로직 추가
            if payload.get("type") != "refresh":
                return None

            user_id_str = payload.get("sub")
            if not user_id_str:
                return None

            user_id = UUID(user_id_str)

            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    # DB에 저장된 Refresh Token인지 확인 -> white list
                    cur.execute(
                        """
                        SELECT user_id FROM refresh_tokens
                        WHERE user_id = %s AND expires_at > NOW()
                    """,
                        (user_id,),
                    )

                    if cur.fetchone():
                        return user_id
        except (JWTError, ValueError, TypeError):
            pass

        return None

    @staticmethod
    def revoke_refresh_tokens(user_id: UUID):
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # logout -> 해당 유저의 모든 리프레시 토큰 삭제
                cur.execute("DELETE FROM refresh_tokens WHERE user_id = %s", (user_id,))
                conn.commit()

    @staticmethod
    def email_exists(email: str) -> bool:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM users WHERE email = %s", (email,))
                return cur.fetchone() is not None

    @staticmethod
    def get_user_by_id(user_id: UUID) -> Optional[User]:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                        SELECT user_id, email, username, disability_type, is_active, created_at, last_login
                        FROM users WHERE user_id = %s
                        """,
                    (user_id,),
                )
                row = cur.fetchone()

                if row:
                    return User(
                        user_id=row[0],
                        email=row[1],
                        username=row[2],
                        disability_type=row[3],
                        is_active=row[4],
                        created_at=row[5],
                        last_login=row[6],
                    )
                return None

    @staticmethod
    def save_refresh_token(user_id: UUID, token: str):
        # 토큰의 만료 시간을 계산 (설정 파일 값 참조)
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # 기존 토큰을 지우고 새로 넣을지, 누적할지는 추후 정책 결정 필요
                # 우선 '단일 기기 로그인' 처럼 기존 토큰 삭제 후 삽입으로 구현
                cur.execute("DELETE FROM refresh_tokens WHERE user_id = %s", (user_id,))

                cur.execute(
                    """
                    INSERT INTO refresh_tokens (user_id, token, expires_at)
                    VALUES (%s, %s, %s)
                    """,
                    (user_id, token, expires_at),
                )
                conn.commit()

    

