"""
인증 보안 모듈 테스트
app/auth/security.py의 비밀번호 해싱, JWT 토큰 생성/검증 기능 테스트
"""

import pytest
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.auth.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    create_refresh_token,
    decode_token
)


class TestPasswordHashing:
    """비밀번호 해싱 및 검증 테스트"""

    def test_hash_password_success(self):
        """비밀번호 해싱 - 성공"""
        # Given
        password = "mySecurePassword123"

        # When
        hashed = get_password_hash(password)

        # Then
        assert hashed is not None
        assert hashed != password
        assert hashed.startswith("$2b$")  # bcrypt prefix

    def test_verify_password_correct(self):
        """올바른 비밀번호 검증 - 성공"""
        # Given
        password = "mySecurePassword123"
        hashed = get_password_hash(password)

        # When
        result = verify_password(password, hashed)

        # Then
        assert result is True

    def test_verify_password_incorrect(self):
        """잘못된 비밀번호 검증 - 실패"""
        # Given
        password = "mySecurePassword123"
        wrong_password = "wrongPassword456"
        hashed = get_password_hash(password)

        # When
        result = verify_password(wrong_password, hashed)

        # Then
        assert result is False

    def test_same_password_different_hashes(self):
        """동일한 비밀번호도 다른 해시 생성 (salt 검증)"""
        # Given
        password = "mySecurePassword123"

        # When
        hash1 = get_password_hash(password)
        hash2 = get_password_hash(password)

        # Then
        assert hash1 != hash2  # 서로 다른 salt로 인해 다른 해시
        assert verify_password(password, hash1)  # 둘 다 검증 성공
        assert verify_password(password, hash2)


class TestAccessToken:
    """Access 토큰 생성 및 검증 테스트"""

    def test_create_access_token_default_expiry(self):
        """Access 토큰 생성 - 기본 만료시간 (30분)"""
        # Given
        user_id = "12345678-1234-5678-1234-567812345678"

        # When
        token = create_access_token(subject=user_id)

        # Then
        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

    def test_create_access_token_custom_expiry(self):
        """Access 토큰 생성 - 커스텀 만료시간"""
        # Given
        user_id = "12345678-1234-5678-1234-567812345678"
        expires_delta = timedelta(minutes=60)

        # When
        token = create_access_token(subject=user_id, expires_delta=expires_delta)

        # Then
        assert token is not None
        payload = decode_token(token)
        assert payload is not None

    def test_access_token_payload_contains_correct_data(self):
        """Access 토큰 페이로드 검증"""
        # Given
        user_id = "12345678-1234-5678-1234-567812345678"

        # When
        token = create_access_token(subject=user_id)
        payload = decode_token(token)

        # Then
        assert payload is not None
        assert payload.get("sub") == user_id
        assert payload.get("type") == "access"
        assert "exp" in payload

    def test_decode_valid_access_token(self):
        """유효한 Access 토큰 디코딩 - 성공"""
        # Given
        user_id = "12345678-1234-5678-1234-567812345678"
        token = create_access_token(subject=user_id)

        # When
        payload = decode_token(token)

        # Then
        assert payload is not None
        assert payload.get("sub") == user_id
        assert payload.get("type") == "access"

    def test_decode_expired_access_token(self):
        """만료된 Access 토큰 디코딩 - None 반환"""
        # Given
        user_id = "12345678-1234-5678-1234-567812345678"
        expires_delta = timedelta(seconds=-1)  # 이미 만료됨
        token = create_access_token(subject=user_id, expires_delta=expires_delta)

        # When
        payload = decode_token(token)

        # Then
        assert payload is None

    def test_decode_invalid_token(self):
        """잘못된 토큰 디코딩 - None 반환"""
        # Given
        invalid_token = "invalid.jwt.token"

        # When
        payload = decode_token(invalid_token)

        # Then
        assert payload is None

    def test_decode_malformed_token(self):
        """형식이 잘못된 토큰 디코딩 - None 반환"""
        # Given
        malformed_token = "not-a-jwt-token"

        # When
        payload = decode_token(malformed_token)

        # Then
        assert payload is None


class TestRefreshToken:
    """Refresh 토큰 생성 및 검증 테스트"""

    def test_create_refresh_token_success(self):
        """Refresh 토큰 생성 - 성공"""
        # Given
        user_id = UUID("12345678-1234-5678-1234-567812345678")

        # When
        token = create_refresh_token(user_id=user_id)

        # Then
        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

    def test_refresh_token_payload_contains_correct_type(self):
        """Refresh 토큰 페이로드에 type='refresh' 포함"""
        # Given
        user_id = UUID("12345678-1234-5678-1234-567812345678")

        # When
        token = create_refresh_token(user_id=user_id)
        payload = decode_token(token)

        # Then
        assert payload is not None
        assert payload.get("type") == "refresh"
        assert payload.get("sub") == str(user_id)

    def test_refresh_token_has_longer_expiry(self):
        """Refresh 토큰은 Access 토큰보다 긴 만료시간 (7일)"""
        # Given
        user_id = UUID("12345678-1234-5678-1234-567812345678")

        # When
        refresh_token = create_refresh_token(user_id=user_id)
        access_token = create_access_token(subject=str(user_id))

        refresh_payload = decode_token(refresh_token)
        access_payload = decode_token(access_token)

        # Then
        assert refresh_payload is not None
        assert access_payload is not None
        assert refresh_payload["exp"] > access_payload["exp"]

    def test_decode_valid_refresh_token(self):
        """유효한 Refresh 토큰 디코딩 - 성공"""
        # Given
        user_id = UUID("12345678-1234-5678-1234-567812345678")
        token = create_refresh_token(user_id=user_id)

        # When
        payload = decode_token(token)

        # Then
        assert payload is not None
        assert payload.get("sub") == str(user_id)
        assert payload.get("type") == "refresh"


class TestTokenValidation:
    """토큰 검증 엣지 케이스 테스트"""

    def test_empty_token_returns_none(self):
        """빈 토큰 - None 반환"""
        # Given
        empty_token = ""

        # When
        payload = decode_token(empty_token)

        # Then
        assert payload is None

    def test_token_with_wrong_signature(self):
        """잘못된 서명의 토큰 - None 반환"""
        # Given
        # 다른 secret으로 생성된 토큰 (실제로는 유효하지 않음)
        fake_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NSIsIm5hbWUiOiJUZXN0In0.invalid_signature"

        # When
        payload = decode_token(fake_token)

        # Then
        assert payload is None
