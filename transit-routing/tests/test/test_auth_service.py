"""
인증 서비스 레이어 테스트
app/services/auth_service.py의 사용자 관리 및 인증 로직 테스트
"""

import pytest
from unittest.mock import patch, MagicMock
from uuid import UUID
from datetime import datetime, timezone, timedelta

from app.services.auth_service import AuthService
from app.auth.security import get_password_hash, create_refresh_token


class TestUserCreation:
    """사용자 생성 테스트"""

    @patch('app.services.auth_service.get_db_connection')
    def test_create_user_success(self, mock_get_conn, sample_user, mocker):
        """사용자 생성 - 성공"""
        # Given
        mock_cursor = mocker.MagicMock()
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = mocker.MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mocker.MagicMock(return_value=None)
        mock_cursor.fetchone.return_value = (
            str(sample_user.user_id),
            sample_user.email,
            sample_user.username,
            sample_user.disability_type,
            sample_user.is_active,
            sample_user.created_at
        )
        mock_get_conn.return_value = mock_conn

        # When
        user = AuthService.create_user(
            email="test@example.com",
            password="password123",
            username="testuser",
            disability_type="PHY"
        )

        # Then
        assert user is not None
        assert user.email == sample_user.email
        assert user.username == sample_user.username
        mock_cursor.execute.assert_called_once()

    @patch('app.services.auth_service.get_db_connection')
    def test_create_user_password_hashed(self, mock_get_conn, mocker):
        """사용자 생성 시 비밀번호 해싱 확인"""
        # Given
        mock_cursor = mocker.MagicMock()
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = mocker.MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mocker.MagicMock(return_value=None)
        mock_get_conn.return_value = mock_conn

        plain_password = "password123"

        # When
        with patch('app.services.auth_service.get_password_hash') as mock_hash:
            mock_hash.return_value = "hashed_password"
            AuthService.create_user(
                email="test@example.com",
                password=plain_password
            )

            # Then
            mock_hash.assert_called_once_with(plain_password)

    @patch('app.services.auth_service.get_db_connection')
    def test_create_user_with_optional_fields(self, mock_get_conn, mocker):
        """사용자 생성 - 선택 필드 포함"""
        # Given
        mock_cursor = mocker.MagicMock()
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = mocker.MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mocker.MagicMock(return_value=None)
        mock_cursor.fetchone.return_value = (
            "12345678-1234-5678-1234-567812345678",
            "test@example.com",
            "testuser",
            "VIS",
            True,
            datetime.now(timezone.utc)
        )
        mock_get_conn.return_value = mock_conn

        # When
        user = AuthService.create_user(
            email="test@example.com",
            password="password123",
            username="testuser",
            disability_type="VIS"
        )

        # Then
        assert user is not None
        assert user.username == "testuser"
        assert user.disability_type == "VIS"

    @patch('app.services.auth_service.get_db_connection')
    def test_create_user_db_error(self, mock_get_conn, mocker):
        """사용자 생성 - DB 에러 시 None 반환"""
        # Given
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.MagicMock(side_effect=Exception("DB Error"))
        mock_get_conn.return_value = mock_conn

        # When
        user = AuthService.create_user(
            email="test@example.com",
            password="password123"
        )

        # Then
        assert user is None


class TestUserAuthentication:
    """사용자 인증 테스트"""

    @patch('app.services.auth_service.get_db_connection')
    def test_authenticate_user_success(self, mock_get_conn, sample_user, sample_user_credentials, mocker):
        """사용자 인증 - 성공"""
        # Given
        mock_cursor = mocker.MagicMock()
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = mocker.MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mocker.MagicMock(return_value=None)

        # 첫 번째 fetchone: 사용자 조회 (password_hash 포함)
        mock_cursor.fetchone.return_value = (
            str(sample_user.user_id),
            sample_user.email,
            sample_user_credentials["password_hash"],
            sample_user.username,
            sample_user.disability_type,
            sample_user.is_active,
            sample_user.created_at,
            sample_user.last_login
        )
        mock_get_conn.return_value = mock_conn

        # When
        user = AuthService.authenticate_user(
            email=sample_user.email,
            password=sample_user_credentials["password"]
        )

        # Then
        assert user is not None
        assert user.email == sample_user.email
        assert user.user_id == sample_user.user_id

    @patch('app.services.auth_service.get_db_connection')
    def test_authenticate_user_wrong_password(self, mock_get_conn, sample_user, sample_user_credentials, mocker):
        """사용자 인증 - 잘못된 비밀번호"""
        # Given
        mock_cursor = mocker.MagicMock()
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = mocker.MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mocker.MagicMock(return_value=None)

        mock_cursor.fetchone.return_value = (
            str(sample_user.user_id),
            sample_user.email,
            sample_user_credentials["password_hash"],
            sample_user.username,
            sample_user.disability_type,
            sample_user.is_active,
            sample_user.created_at,
            sample_user.last_login
        )
        mock_get_conn.return_value = mock_conn

        # When
        user = AuthService.authenticate_user(
            email=sample_user.email,
            password=sample_user_credentials["wrong_password"]
        )

        # Then
        assert user is None

    @patch('app.services.auth_service.get_db_connection')
    def test_authenticate_user_not_found(self, mock_get_conn, mocker):
        """사용자 인증 - 존재하지 않는 이메일"""
        # Given
        mock_cursor = mocker.MagicMock()
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = mocker.MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mocker.MagicMock(return_value=None)

        mock_cursor.fetchone.return_value = None
        mock_get_conn.return_value = mock_conn

        # When
        user = AuthService.authenticate_user(
            email="nonexistent@example.com",
            password="password123"
        )

        # Then
        assert user is None

    @patch('app.services.auth_service.get_db_connection')
    def test_authenticate_user_updates_last_login(self, mock_get_conn, sample_user, sample_user_credentials, mocker):
        """사용자 인증 시 last_login 업데이트 확인"""
        # Given
        mock_cursor = mocker.MagicMock()
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = mocker.MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mocker.MagicMock(return_value=None)

        mock_cursor.fetchone.return_value = (
            str(sample_user.user_id),
            sample_user.email,
            sample_user_credentials["password_hash"],
            sample_user.username,
            sample_user.disability_type,
            sample_user.is_active,
            sample_user.created_at,
            sample_user.last_login
        )
        mock_get_conn.return_value = mock_conn

        # When
        AuthService.authenticate_user(
            email=sample_user.email,
            password=sample_user_credentials["password"]
        )

        # Then
        # execute가 2번 호출되어야 함: 1) 사용자 조회, 2) last_login 업데이트
        assert mock_cursor.execute.call_count == 2


class TestEmailCheck:
    """이메일 중복 확인 테스트"""

    @patch('app.services.auth_service.get_db_connection')
    def test_email_exists_true(self, mock_get_conn, mocker):
        """이메일 존재 - True 반환"""
        # Given
        mock_cursor = mocker.MagicMock()
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = mocker.MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mocker.MagicMock(return_value=None)

        mock_cursor.fetchone.return_value = (1,)  # COUNT(*) = 1
        mock_get_conn.return_value = mock_conn

        # When
        exists = AuthService.email_exists("existing@example.com")

        # Then
        assert exists is True

    @patch('app.services.auth_service.get_db_connection')
    def test_email_exists_false(self, mock_get_conn, mocker):
        """이메일 없음 - False 반환"""
        # Given
        mock_cursor = mocker.MagicMock()
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = mocker.MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mocker.MagicMock(return_value=None)

        mock_cursor.fetchone.return_value = (0,)  # COUNT(*) = 0
        mock_get_conn.return_value = mock_conn

        # When
        exists = AuthService.email_exists("new@example.com")

        # Then
        assert exists is False


class TestGetUser:
    """사용자 조회 테스트"""

    @patch('app.services.auth_service.get_db_connection')
    def test_get_user_by_id_success(self, mock_get_conn, sample_user, mocker):
        """사용자 ID로 조회 - 성공"""
        # Given
        mock_cursor = mocker.MagicMock()
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = mocker.MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mocker.MagicMock(return_value=None)

        mock_cursor.fetchone.return_value = (
            str(sample_user.user_id),
            sample_user.email,
            sample_user.username,
            sample_user.disability_type,
            sample_user.is_active,
            sample_user.created_at,
            sample_user.last_login
        )
        mock_get_conn.return_value = mock_conn

        # When
        user = AuthService.get_user_by_id(sample_user.user_id)

        # Then
        assert user is not None
        assert user.user_id == sample_user.user_id
        assert user.email == sample_user.email

    @patch('app.services.auth_service.get_db_connection')
    def test_get_user_by_id_not_found(self, mock_get_conn, mocker):
        """사용자 ID로 조회 - 없음"""
        # Given
        mock_cursor = mocker.MagicMock()
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = mocker.MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mocker.MagicMock(return_value=None)

        mock_cursor.fetchone.return_value = None
        mock_get_conn.return_value = mock_conn

        # When
        user = AuthService.get_user_by_id(UUID("00000000-0000-0000-0000-000000000000"))

        # Then
        assert user is None


class TestRefreshTokenManagement:
    """Refresh 토큰 관리 테스트"""

    @patch('app.services.auth_service.get_db_connection')
    def test_save_refresh_token_success(self, mock_get_conn, sample_user, mocker):
        """Refresh 토큰 저장 - 성공"""
        # Given
        mock_cursor = mocker.MagicMock()
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = mocker.MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mocker.MagicMock(return_value=None)
        mock_get_conn.return_value = mock_conn

        refresh_token = create_refresh_token(sample_user.user_id)

        # When
        AuthService.save_refresh_token(sample_user.user_id, refresh_token)

        # Then
        # 2번 호출: 1) 기존 토큰 삭제, 2) 새 토큰 저장
        assert mock_cursor.execute.call_count == 2

    @patch('app.services.auth_service.get_db_connection')
    def test_verify_refresh_token_valid(self, mock_get_conn, sample_user, mocker):
        """Refresh 토큰 검증 - 유효함"""
        # Given
        mock_cursor = mocker.MagicMock()
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = mocker.MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mocker.MagicMock(return_value=None)

        refresh_token = create_refresh_token(sample_user.user_id)
        future_time = datetime.now(timezone.utc) + timedelta(days=7)
        mock_cursor.fetchone.return_value = (str(sample_user.user_id), future_time)
        mock_get_conn.return_value = mock_conn

        # When
        user_id = AuthService.verify_refresh_token(refresh_token)

        # Then
        assert user_id == sample_user.user_id

    @patch('app.services.auth_service.get_db_connection')
    def test_verify_refresh_token_not_in_db(self, mock_get_conn, sample_user, mocker):
        """Refresh 토큰 검증 - DB에 없음 (화이트리스트 실패)"""
        # Given
        mock_cursor = mocker.MagicMock()
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = mocker.MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mocker.MagicMock(return_value=None)

        refresh_token = create_refresh_token(sample_user.user_id)
        mock_cursor.fetchone.return_value = None  # DB에 없음
        mock_get_conn.return_value = mock_conn

        # When
        user_id = AuthService.verify_refresh_token(refresh_token)

        # Then
        assert user_id is None

    @patch('app.services.auth_service.get_db_connection')
    def test_verify_refresh_token_expired(self, mock_get_conn, sample_user, mocker):
        """Refresh 토큰 검증 - 만료됨"""
        # Given
        mock_cursor = mocker.MagicMock()
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = mocker.MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mocker.MagicMock(return_value=None)

        refresh_token = create_refresh_token(sample_user.user_id)
        past_time = datetime.now(timezone.utc) - timedelta(days=1)  # 만료됨
        mock_cursor.fetchone.return_value = (str(sample_user.user_id), past_time)
        mock_get_conn.return_value = mock_conn

        # When
        user_id = AuthService.verify_refresh_token(refresh_token)

        # Then
        assert user_id is None

    def test_verify_refresh_token_invalid_format(self):
        """Refresh 토큰 검증 - 잘못된 형식"""
        # Given
        invalid_token = "invalid.token.format"

        # When
        user_id = AuthService.verify_refresh_token(invalid_token)

        # Then
        assert user_id is None

    def test_verify_refresh_token_wrong_type(self, sample_user):
        """Refresh 토큰 검증 - Access 토큰 사용 (type 불일치)"""
        # Given
        from app.auth.security import create_access_token
        access_token = create_access_token(subject=str(sample_user.user_id))

        # When
        user_id = AuthService.verify_refresh_token(access_token)

        # Then
        assert user_id is None

    @patch('app.services.auth_service.get_db_connection')
    def test_revoke_refresh_tokens_success(self, mock_get_conn, sample_user, mocker):
        """Refresh 토큰 철회 - 성공"""
        # Given
        mock_cursor = mocker.MagicMock()
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = mocker.MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mocker.MagicMock(return_value=None)
        mock_get_conn.return_value = mock_conn

        # When
        AuthService.revoke_refresh_tokens(sample_user.user_id)

        # Then
        mock_cursor.execute.assert_called_once()
        # DELETE 쿼리가 실행되었는지 확인
        call_args = mock_cursor.execute.call_args[0]
        assert "DELETE" in call_args[0]

    @patch('app.services.auth_service.get_db_connection')
    def test_save_refresh_token_replaces_old(self, mock_get_conn, sample_user, mocker):
        """Refresh 토큰 저장 시 기존 토큰 대체 (단일 디바이스 정책)"""
        # Given
        mock_cursor = mocker.MagicMock()
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = mocker.MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mocker.MagicMock(return_value=None)
        mock_get_conn.return_value = mock_conn

        refresh_token = create_refresh_token(sample_user.user_id)

        # When
        AuthService.save_refresh_token(sample_user.user_id, refresh_token)

        # Then
        # 첫 번째 execute: DELETE (기존 토큰 삭제)
        # 두 번째 execute: INSERT (새 토큰 저장)
        assert mock_cursor.execute.call_count == 2
        first_call = mock_cursor.execute.call_args_list[0][0][0]
        assert "DELETE" in first_call
