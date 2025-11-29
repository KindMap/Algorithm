"""
인증 의존성 함수 테스트
app/api/deps.py의 FastAPI 의존성 함수 테스트
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from uuid import UUID

from app.api.deps import get_current_user, get_current_active_user


class TestGetCurrentUser:
    """Optional 인증 의존성 테스트 (get_current_user)"""

    @patch('app.api.deps.decode_token')
    @patch('app.api.deps.AuthService.get_user_by_id')
    async def test_get_current_user_with_valid_token(
        self,
        mock_get_user,
        mock_decode,
        sample_user,
        sample_tokens
    ):
        """유효한 토큰으로 사용자 조회 - 성공"""
        # Given
        mock_decode.return_value = {
            "sub": str(sample_user.user_id),
            "type": "access"
        }
        mock_get_user.return_value = sample_user

        # When
        user = await get_current_user(token=sample_tokens["access_token"])

        # Then
        assert user is not None
        assert user.user_id == sample_user.user_id
        assert user.email == sample_user.email

    async def test_get_current_user_without_token(self):
        """토큰 없이 호출 - None 반환 (에러 없음)"""
        # When
        user = await get_current_user(token=None)

        # Then
        assert user is None

    @patch('app.api.deps.decode_token')
    async def test_get_current_user_with_invalid_token(self, mock_decode):
        """잘못된 토큰 - None 반환"""
        # Given
        mock_decode.return_value = None  # 디코딩 실패

        # When
        user = await get_current_user(token="invalid_token")

        # Then
        assert user is None

    @patch('app.api.deps.decode_token')
    async def test_get_current_user_with_refresh_token(self, mock_decode, sample_user):
        """Refresh 토큰으로 호출 - None 반환 (type 불일치)"""
        # Given
        mock_decode.return_value = {
            "sub": str(sample_user.user_id),
            "type": "refresh"  # access가 아님
        }

        # When
        user = await get_current_user(token="refresh_token")

        # Then
        assert user is None

    @patch('app.api.deps.decode_token')
    @patch('app.api.deps.AuthService.get_user_by_id')
    async def test_get_current_user_user_not_found(self, mock_get_user, mock_decode):
        """토큰은 유효하나 사용자가 DB에 없음 - None 반환"""
        # Given
        mock_decode.return_value = {
            "sub": "12345678-1234-5678-1234-567812345678",
            "type": "access"
        }
        mock_get_user.return_value = None  # DB에서 사용자 없음

        # When
        user = await get_current_user(token="valid_token")

        # Then
        assert user is None

    @patch('app.api.deps.decode_token')
    async def test_get_current_user_with_expired_token(self, mock_decode):
        """만료된 토큰 - None 반환"""
        # Given
        mock_decode.return_value = None  # 만료된 토큰은 decode_token에서 None 반환

        # When
        user = await get_current_user(token="expired_token")

        # Then
        assert user is None


class TestGetCurrentActiveUser:
    """Required 인증 의존성 테스트 (get_current_active_user)"""

    async def test_get_current_active_user_success(self, sample_user):
        """인증되고 활성화된 사용자 - 성공"""
        # When
        user = await get_current_active_user(current_user=sample_user)

        # Then
        assert user is not None
        assert user.user_id == sample_user.user_id
        assert user.is_active is True

    async def test_get_current_active_user_not_authenticated(self):
        """인증되지 않은 요청 - 401 에러"""
        # When & Then
        with pytest.raises(HTTPException) as exc_info:
            await get_current_active_user(current_user=None)

        assert exc_info.value.status_code == 401
        assert "Not authenticated" in exc_info.value.detail

    async def test_get_current_active_user_inactive(self, sample_inactive_user):
        """비활성화된 사용자 - 400 에러"""
        # When & Then
        with pytest.raises(HTTPException) as exc_info:
            await get_current_active_user(current_user=sample_inactive_user)

        assert exc_info.value.status_code == 400
        assert "Inactive user" in exc_info.value.detail

    async def test_get_current_active_user_returns_same_user(self, sample_user):
        """활성 사용자 객체 그대로 반환"""
        # When
        returned_user = await get_current_active_user(current_user=sample_user)

        # Then
        assert returned_user is sample_user  # 동일한 객체


class TestDependencyIntegration:
    """의존성 함수 통합 테스트"""

    @patch('app.api.deps.decode_token')
    @patch('app.api.deps.AuthService.get_user_by_id')
    async def test_optional_to_required_flow(
        self,
        mock_get_user,
        mock_decode,
        sample_user,
        sample_tokens
    ):
        """Optional → Required 의존성 체인 테스트"""
        # Given
        mock_decode.return_value = {
            "sub": str(sample_user.user_id),
            "type": "access"
        }
        mock_get_user.return_value = sample_user

        # When - Optional 의존성 호출
        user_from_optional = await get_current_user(token=sample_tokens["access_token"])

        # Then - 사용자 객체 반환
        assert user_from_optional is not None

        # When - Required 의존성 호출
        user_from_required = await get_current_active_user(current_user=user_from_optional)

        # Then - 동일한 사용자 반환
        assert user_from_required.user_id == sample_user.user_id

    async def test_optional_without_token_to_required_fails(self):
        """토큰 없이 Optional 호출 → Required는 실패해야 함"""
        # When - Optional 의존성 (토큰 없음)
        user_from_optional = await get_current_user(token=None)

        # Then - None 반환
        assert user_from_optional is None

        # When & Then - Required 의존성 (None 전달) → 401 에러
        with pytest.raises(HTTPException) as exc_info:
            await get_current_active_user(current_user=user_from_optional)

        assert exc_info.value.status_code == 401

    @patch('app.api.deps.decode_token')
    @patch('app.api.deps.AuthService.get_user_by_id')
    async def test_inactive_user_through_chain(
        self,
        mock_get_user,
        mock_decode,
        sample_inactive_user,
        sample_tokens
    ):
        """비활성 사용자가 Optional 통과 → Required에서 차단"""
        # Given
        mock_decode.return_value = {
            "sub": str(sample_inactive_user.user_id),
            "type": "access"
        }
        mock_get_user.return_value = sample_inactive_user

        # When - Optional 의존성
        user_from_optional = await get_current_user(token=sample_tokens["access_token"])

        # Then - Optional은 비활성 사용자도 반환
        assert user_from_optional is not None
        assert user_from_optional.is_active is False

        # When & Then - Required 의존성 → 400 에러
        with pytest.raises(HTTPException) as exc_info:
            await get_current_active_user(current_user=user_from_optional)

        assert exc_info.value.status_code == 400
        assert "Inactive user" in exc_info.value.detail
