"""
인증 API 엔드포인트 테스트
app/api/v1/endpoints/auth.py의 HTTP API 엔드포인트 테스트
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from uuid import UUID

from app.models.domain import User


@pytest.fixture
def client():
    """FastAPI TestClient fixture"""
    from app.main import app
    return TestClient(app)


class TestRegisterEndpoint:
    """회원가입 엔드포인트 테스트"""

    @patch('app.api.v1.endpoints.auth.AuthService.email_exists')
    @patch('app.api.v1.endpoints.auth.AuthService.create_user')
    def test_register_success(self, mock_create_user, mock_email_exists, sample_user, client):
        """회원가입 - 성공 (201 Created)"""
        # Given
        mock_email_exists.return_value = False
        mock_create_user.return_value = sample_user

        # When
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "newuser@example.com",
                "password": "password123",
                "username": "newuser",
                "disability_type": "PHY"
            }
        )

        # Then
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == sample_user.email
        assert "password" not in data  # 비밀번호는 응답에 포함되지 않아야 함

    @patch('app.api.v1.endpoints.auth.AuthService.email_exists')
    def test_register_duplicate_email(self, mock_email_exists, client):
        """회원가입 - 중복 이메일 (400 Bad Request)"""
        # Given
        mock_email_exists.return_value = True

        # When
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "existing@example.com",
                "password": "password123"
            }
        )

        # Then
        assert response.status_code == 400
        assert "이미 사용 중인 이메일" in response.json()["detail"]

    def test_register_invalid_email_format(self):
        """회원가입 - 잘못된 이메일 형식 (422 Validation Error)"""
        # Given
        invalid_email = "not-an-email"

        # When
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": invalid_email,
                "password": "password123"
            }
        )

        # Then
        assert response.status_code == 422  # Pydantic validation error

    def test_register_password_too_short(self):
        """회원가입 - 비밀번호 너무 짧음 (422 Validation Error)"""
        # Given
        short_password = "short"

        # When
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "test@example.com",
                "password": short_password
            }
        )

        # Then
        assert response.status_code == 422

    def test_register_invalid_disability_type(self):
        """회원가입 - 잘못된 disability_type (422 Validation Error)"""
        # Given
        invalid_disability_type = "INVALID"

        # When
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "test@example.com",
                "password": "password123",
                "disability_type": invalid_disability_type
            }
        )

        # Then
        assert response.status_code == 422


class TestLoginEndpoint:
    """로그인 엔드포인트 테스트"""

    @patch('app.api.v1.endpoints.auth.AuthService.authenticate_user')
    @patch('app.api.v1.endpoints.auth.AuthService.save_refresh_token')
    def test_login_success(self, mock_save_token, mock_authenticate, sample_user, client):
        """로그인 - 성공 (200 OK)"""
        # Given
        mock_authenticate.return_value = sample_user

        # When
        response = client.post(
            "/api/v1/auth/login",
            data={
                "username": "test@example.com",  # OAuth2PasswordRequestForm uses 'username'
                "password": "password123"
            }
        )

        # Then
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        mock_save_token.assert_called_once()

    @patch('app.api.v1.endpoints.auth.AuthService.authenticate_user')
    def test_login_invalid_credentials(self, mock_authenticate, client):
        """로그인 - 잘못된 자격증명 (401 Unauthorized)"""
        # Given
        mock_authenticate.return_value = None

        # When
        response = client.post(
            "/api/v1/auth/login",
            data={
                "username": "test@example.com",
                "password": "wrongpassword"
            }
        )

        # Then
        assert response.status_code == 401
        assert "이메일 혹은 비밀번호" in response.json()["detail"]

    @patch('app.api.v1.endpoints.auth.AuthService.authenticate_user')
    def test_login_inactive_user(self, mock_authenticate, sample_inactive_user, client):
        """로그인 - 비활성화된 사용자 (400 Bad Request)"""
        # Given
        mock_authenticate.return_value = sample_inactive_user

        # When
        response = client.post(
            "/api/v1/auth/login",
            data={
                "username": "inactive@example.com",
                "password": "password123"
            }
        )

        # Then
        assert response.status_code == 400
        assert "만료된 사용자" in response.json()["detail"]

    def test_login_missing_credentials(self):
        """로그인 - 자격증명 누락 (422 Validation Error)"""
        # When
        response = client.post(
            "/api/v1/auth/login",
            data={}
        )

        # Then
        assert response.status_code == 422

    @patch('app.api.v1.endpoints.auth.AuthService.authenticate_user')
    @patch('app.api.v1.endpoints.auth.create_access_token')
    @patch('app.api.v1.endpoints.auth.create_refresh_token')
    def test_login_token_generation(self, mock_refresh, mock_access, mock_authenticate, sample_user, client):
        """로그인 - 토큰 생성 확인"""
        # Given
        mock_authenticate.return_value = sample_user
        mock_access.return_value = "access_token_123"
        mock_refresh.return_value = "refresh_token_456"

        # When
        response = client.post(
            "/api/v1/auth/login",
            data={
                "username": "test@example.com",
                "password": "password123"
            }
        )

        # Then
        assert response.status_code == 200
        mock_access.assert_called_once_with(subject=str(sample_user.user_id))
        mock_refresh.assert_called_once_with(sample_user.user_id)


class TestRefreshEndpoint:
    """토큰 갱신 엔드포인트 테스트"""

    @patch('app.api.v1.endpoints.auth.AuthService.verify_refresh_token')
    @patch('app.api.v1.endpoints.auth.AuthService.save_refresh_token')
    def test_refresh_success(self, mock_save_token, mock_verify, sample_user, client):
        """토큰 갱신 - 성공 (200 OK)"""
        # Given
        mock_verify.return_value = sample_user.user_id

        # When
        response = client.post(
            "/api/v1/auth/refresh",
            json={
                "refresh_token": "valid_refresh_token"
            }
        )

        # Then
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        mock_save_token.assert_called_once()

    @patch('app.api.v1.endpoints.auth.AuthService.verify_refresh_token')
    def test_refresh_invalid_token(self, mock_verify, client):
        """토큰 갱신 - 잘못된 토큰 (401 Unauthorized)"""
        # Given
        mock_verify.return_value = None

        # When
        response = client.post(
            "/api/v1/auth/refresh",
            json={
                "refresh_token": "invalid_refresh_token"
            }
        )

        # Then
        assert response.status_code == 401
        assert "Invalid refresh token" in response.json()["detail"]

    def test_refresh_missing_token(self):
        """토큰 갱신 - 토큰 누락 (422 Validation Error)"""
        # When
        response = client.post(
            "/api/v1/auth/refresh",
            json={}
        )

        # Then
        assert response.status_code == 422

    @patch('app.api.v1.endpoints.auth.AuthService.verify_refresh_token')
    @patch('app.api.v1.endpoints.auth.create_access_token')
    @patch('app.api.v1.endpoints.auth.create_refresh_token')
    def test_refresh_generates_new_tokens(self, mock_new_refresh, mock_new_access, mock_verify, sample_user, client):
        """토큰 갱신 - 새로운 토큰 쌍 생성"""
        # Given
        mock_verify.return_value = sample_user.user_id
        mock_new_access.return_value = "new_access_token"
        mock_new_refresh.return_value = "new_refresh_token"

        # When
        response = client.post(
            "/api/v1/auth/refresh",
            json={
                "refresh_token": "old_refresh_token"
            }
        )

        # Then
        assert response.status_code == 200
        data = response.json()
        assert data["access_token"] == "new_access_token"
        assert data["refresh_token"] == "new_refresh_token"

    @patch('app.api.v1.endpoints.auth.AuthService.verify_refresh_token')
    def test_refresh_expired_token(self, mock_verify, client):
        """토큰 갱신 - 만료된 토큰 (401 Unauthorized)"""
        # Given
        mock_verify.return_value = None  # 만료된 토큰은 None 반환

        # When
        response = client.post(
            "/api/v1/auth/refresh",
            json={
                "refresh_token": "expired_refresh_token"
            }
        )

        # Then
        assert response.status_code == 401


class TestLogoutEndpoint:
    """로그아웃 엔드포인트 테스트"""

    @patch('app.api.v1.endpoints.auth.get_current_active_user')
    @patch('app.api.v1.endpoints.auth.AuthService.revoke_refresh_tokens')
    def test_logout_success(self, mock_revoke, mock_get_user, sample_user, sample_tokens, client):
        """로그아웃 - 성공 (200 OK)"""
        # Given
        mock_get_user.return_value = sample_user

        # When
        response = client.post(
            "/api/v1/auth/logout",
            headers={
                "Authorization": f"Bearer {sample_tokens['access_token']}"
            }
        )

        # Then
        assert response.status_code == 200
        assert "성공" in response.json()["message"]
        mock_revoke.assert_called_once_with(sample_user.user_id)

    @patch('app.api.v1.endpoints.auth.get_current_active_user')
    def test_logout_without_authentication(self, mock_get_user, client):
        """로그아웃 - 인증 없음 (401 Unauthorized)"""
        # Given
        from fastapi import HTTPException, status
        mock_get_user.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )

        # When
        response = client.post(
            "/api/v1/auth/logout"
        )

        # Then
        assert response.status_code == 401

    @patch('app.api.v1.endpoints.auth.get_current_active_user')
    @patch('app.api.v1.endpoints.auth.AuthService.revoke_refresh_tokens')
    def test_logout_revokes_all_tokens(self, mock_revoke, mock_get_user, sample_user, sample_tokens, client):
        """로그아웃 - 모든 리프레시 토큰 철회 확인"""
        # Given
        mock_get_user.return_value = sample_user

        # When
        client.post(
            "/api/v1/auth/logout",
            headers={
                "Authorization": f"Bearer {sample_tokens['access_token']}"
            }
        )

        # Then
        mock_revoke.assert_called_once_with(sample_user.user_id)


class TestGetMeEndpoint:
    """현재 사용자 정보 조회 엔드포인트 테스트"""

    @patch('app.api.v1.endpoints.auth.get_current_active_user')
    def test_get_me_success(self, mock_get_user, sample_user, sample_tokens, client):
        """사용자 정보 조회 - 성공 (200 OK)"""
        # Given
        mock_get_user.return_value = sample_user

        # When
        response = client.get(
            "/api/v1/auth/me",
            headers={
                "Authorization": f"Bearer {sample_tokens['access_token']}"
            }
        )

        # Then
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == sample_user.email
        assert data["username"] == sample_user.username
        assert "password" not in data

    @patch('app.api.v1.endpoints.auth.get_current_active_user')
    def test_get_me_without_authentication(self, mock_get_user, client):
        """사용자 정보 조회 - 인증 없음 (401 Unauthorized)"""
        # Given
        from fastapi import HTTPException, status
        mock_get_user.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )

        # When
        response = client.get("/api/v1/auth/me")

        # Then
        assert response.status_code == 401

    @patch('app.api.v1.endpoints.auth.get_current_active_user')
    def test_get_me_inactive_user(self, mock_get_user, sample_inactive_user, client):
        """사용자 정보 조회 - 비활성화된 사용자 (400 Bad Request)"""
        # Given
        from fastapi import HTTPException, status
        mock_get_user.side_effect = HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )

        # When
        response = client.get(
            "/api/v1/auth/me",
            headers={
                "Authorization": "Bearer some_token"
            }
        )

        # Then
        assert response.status_code == 400


class TestAuthenticationFlow:
    """전체 인증 플로우 통합 테스트"""

    @patch('app.api.v1.endpoints.auth.AuthService.email_exists')
    @patch('app.api.v1.endpoints.auth.AuthService.create_user')
    @patch('app.api.v1.endpoints.auth.AuthService.authenticate_user')
    @patch('app.api.v1.endpoints.auth.AuthService.save_refresh_token')
    def test_full_registration_and_login_flow(
        self,
        mock_save_token,
        mock_authenticate,
        mock_create_user,
        mock_email_exists,
        sample_user
    ):
        """회원가입 → 로그인 전체 플로우"""
        # Given
        mock_email_exists.return_value = False
        mock_create_user.return_value = sample_user
        mock_authenticate.return_value = sample_user

        # When - 회원가입
        register_response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "newuser@example.com",
                "password": "password123",
                "username": "newuser"
            }
        )

        # Then - 회원가입 성공
        assert register_response.status_code == 201

        # When - 로그인
        login_response = client.post(
            "/api/v1/auth/login",
            data={
                "username": "newuser@example.com",
                "password": "password123"
            }
        )

        # Then - 로그인 성공 및 토큰 발급
        assert login_response.status_code == 200
        tokens = login_response.json()
        assert "access_token" in tokens
        assert "refresh_token" in tokens
