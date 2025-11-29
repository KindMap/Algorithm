"""
WebSocket 엔드포인트 테스트
"""

import pytest
import json
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi import WebSocket

from app.api.v1.endpoints.websocket import (
    ConnectionManager,
    handle_start_navigation,
    handle_location_update,
    handle_switch_route,
    handle_recalculate_route,
    handle_end_navigation,
)


class TestConnectionManager:
    """ConnectionManager 테스트"""

    @pytest.fixture
    def manager(self):
        """ConnectionManager 인스턴스"""
        return ConnectionManager()

    @pytest.fixture
    def mock_websocket(self):
        """Mock WebSocket"""
        ws = AsyncMock(spec=WebSocket)
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        ws.close = AsyncMock()
        return ws

    @pytest.mark.asyncio
    async def test_connect_new_user(self, manager, mock_websocket):
        """새로운 사용자 연결"""
        await manager.connect(mock_websocket, "user123")

        assert "user123" in manager.active_connections
        assert manager.active_connections["user123"] == mock_websocket
        mock_websocket.accept.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_duplicate_user(self, manager, mock_websocket):
        """중복 연결 처리"""
        old_ws = AsyncMock(spec=WebSocket)
        old_ws.send_json = AsyncMock()
        old_ws.close = AsyncMock()

        # 첫 번째 연결
        await manager.connect(old_ws, "user123")

        # 두 번째 연결 (중복)
        new_ws = AsyncMock(spec=WebSocket)
        new_ws.accept = AsyncMock()
        await manager.connect(new_ws, "user123")

        # 이전 연결이 종료되고 새 연결로 대체되어야 함
        assert manager.active_connections["user123"] == new_ws
        old_ws.send_json.assert_called_once()
        old_ws.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_max_connections(self, manager, mock_websocket):
        """최대 연결 수 제한"""
        # 최대 연결 수를 2로 설정 (테스트용)
        manager.MAX_CONNECTIONS = 2

        # 2개 연결
        ws1 = AsyncMock(spec=WebSocket)
        ws1.accept = AsyncMock()
        ws2 = AsyncMock(spec=WebSocket)
        ws2.accept = AsyncMock()

        await manager.connect(ws1, "user1")
        await manager.connect(ws2, "user2")

        # 3번째 연결 시도 (초과)
        ws3 = AsyncMock(spec=WebSocket)
        ws3.close = AsyncMock()

        with pytest.raises(Exception, match="최대 연결 수 초과"):
            await manager.connect(ws3, "user3")

        ws3.close.assert_called_once()

    def test_disconnect(self, manager, mock_websocket):
        """연결 해제"""
        manager.active_connections["user123"] = mock_websocket

        manager.disconnect("user123")

        assert "user123" not in manager.active_connections

    def test_disconnect_nonexistent_user(self, manager):
        """존재하지 않는 사용자 연결 해제"""
        # 예외 발생하지 않아야 함
        manager.disconnect("nonexistent_user")

    @pytest.mark.asyncio
    async def test_send_message(self, manager, mock_websocket):
        """메시지 전송"""
        manager.active_connections["user123"] = mock_websocket

        message = {"type": "test", "data": "hello"}
        await manager.send_message("user123", message)

        mock_websocket.send_json.assert_called_once_with(message)

    @pytest.mark.asyncio
    async def test_send_message_connection_error(self, manager, mock_websocket):
        """메시지 전송 실패 시 연결 해제"""
        mock_websocket.send_json = AsyncMock(side_effect=Exception("Connection error"))
        manager.active_connections["user123"] = mock_websocket

        message = {"type": "test"}
        await manager.send_message("user123", message)

        # 연결이 자동으로 해제되어야 함
        assert "user123" not in manager.active_connections

    @pytest.mark.asyncio
    async def test_send_error(self, manager, mock_websocket):
        """에러 메시지 전송"""
        manager.active_connections["user123"] = mock_websocket

        await manager.send_error("user123", "Error occurred", "ERROR_CODE")

        # send_json이 호출되었는지 확인
        mock_websocket.send_json.assert_called_once()

        # 전송된 메시지 확인
        call_args = mock_websocket.send_json.call_args[0][0]
        assert call_args["type"] == "error"
        assert call_args["message"] == "Error occurred"
        assert call_args["code"] == "ERROR_CODE"

    def test_get_connection_count(self, manager, mock_websocket):
        """활성 연결 수 조회"""
        manager.active_connections = {
            "user1": mock_websocket,
            "user2": mock_websocket,
            "user3": mock_websocket,
        }

        count = manager.get_connection_count()

        assert count == 3


class TestWebSocketHandlers:
    """WebSocket 핸들러 함수 테스트"""

    @pytest.mark.asyncio
    @patch("app.api.v1.endpoints.websocket.manager")
    async def test_handle_start_navigation_success(
        self, mock_manager, sample_route_data
    ):
        """경로 계산 시작 - 성공"""
        mock_manager.send_message = AsyncMock()
        mock_manager.send_error = AsyncMock()

        mock_service = MagicMock()
        mock_service.calculate_route.return_value = sample_route_data

        data = {
            "origin": "서울역",
            "destination": "강남역",
            "disability_type": "PHY",
        }

        with patch("app.api.v1.endpoints.websocket.get_redis_client") as mock_get_redis, \
             patch("app.api.v1.endpoints.websocket.save_navigation_event"):

            mock_redis = mock_get_redis.return_value
            mock_redis.create_session = MagicMock()

            await handle_start_navigation("user123", data, mock_service)

            # 경로 계산 호출 확인
            mock_service.calculate_route.assert_called_once_with(
                "서울역", "강남역", "PHY"
            )

            # 세션 생성 확인
            mock_redis.create_session.assert_called_once()

            # 성공 메시지 전송 확인
            mock_manager.send_message.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.api.v1.endpoints.websocket.manager")
    async def test_handle_start_navigation_missing_params(self, mock_manager):
        """경로 계산 시작 - 파라미터 누락"""
        mock_manager.send_message = AsyncMock()
        mock_manager.send_error = AsyncMock()

        mock_service = MagicMock()

        # 목적지 누락
        data = {"origin": "서울역", "disability_type": "PHY"}

        await handle_start_navigation("user123", data, mock_service)

        # 에러 메시지 전송 확인
        mock_manager.send_error.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.api.v1.endpoints.websocket.manager")
    async def test_handle_location_update_success(self, mock_manager, sample_session_data):
        """위치 업데이트 - 성공"""
        mock_manager.send_message = AsyncMock()
        mock_manager.send_error = AsyncMock()

        mock_service = MagicMock()
        mock_service.get_navigation_guidance.return_value = {
            "current_station": "1000000100",
            "current_station_name": "서울역",
            "next_station": "2000000201",
            "next_station_name": "강남역",
            "distance_to_next": 100.0,
            "remaining_stations": 1,
            "progress_percent": 50,
            "is_transfer": False,
            "message": "강남역 방향으로 이동 중",
        }

        data = {"latitude": 37.5546788, "longitude": 126.9706188}

        with patch("app.api.v1.endpoints.websocket.get_redis_client") as mock_get_redis, \
             patch("app.api.v1.endpoints.websocket.save_location_history"):

            mock_redis = mock_get_redis.return_value
            mock_redis.get_session.return_value = sample_session_data

            await handle_location_update("user123", data, mock_service)

            # 안내 생성 호출 확인
            mock_service.get_navigation_guidance.assert_called_once()

            # 메시지 전송 확인
            mock_manager.send_message.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.api.v1.endpoints.websocket.manager")
    async def test_handle_location_update_deviation(self, mock_manager, sample_session_data):
        """위치 업데이트 - 경로 이탈"""
        mock_manager.send_message = AsyncMock()
        mock_manager.send_error = AsyncMock()

        mock_service = MagicMock()
        mock_service.get_navigation_guidance.return_value = {
            "recalculate": True,
            "message": "경로를 이탈했습니다",
            "current_location": "9999999999",
            "nearest_station": "다른역",
        }

        data = {"latitude": 37.5, "longitude": 127.0}

        with patch("app.api.v1.endpoints.websocket.get_redis_client") as mock_get_redis, \
             patch("app.api.v1.endpoints.websocket.save_navigation_event"):

            mock_redis = mock_get_redis.return_value
            mock_redis.get_session.return_value = sample_session_data

            await handle_location_update("user123", data, mock_service)

            # 이탈 메시지 전송 확인
            call_args = mock_manager.send_message.call_args[0]
            message = call_args[1]
            assert message["type"] == "route_deviation"

    @pytest.mark.asyncio
    @patch("app.api.v1.endpoints.websocket.manager")
    async def test_handle_switch_route_success(self, mock_manager, sample_session_data):
        """경로 변경 - 성공"""
        mock_manager.send_message = AsyncMock()
        mock_manager.send_error = AsyncMock()

        data = {"target_rank": 2}

        with patch("app.api.v1.endpoints.websocket.get_redis_client") as mock_get_redis:
            mock_redis = mock_get_redis.return_value
            mock_redis.switch_route.return_value = True
            mock_redis.get_session.return_value = sample_session_data

            await handle_switch_route("user123", data)

            # 경로 변경 호출 확인
            mock_redis.switch_route.assert_called_once_with("user123", 2)

            # 성공 메시지 전송 확인
            call_args = mock_manager.send_message.call_args[0]
            message = call_args[1]
            assert message["type"] == "route_switched"

    @pytest.mark.asyncio
    @patch("app.api.v1.endpoints.websocket.manager")
    async def test_handle_switch_route_invalid_rank(self, mock_manager):
        """경로 변경 - 유효하지 않은 순위"""
        mock_manager.send_message = AsyncMock()
        mock_manager.send_error = AsyncMock()

        data = {"target_rank": 5}  # 1-3만 유효

        await handle_switch_route("user123", data)

        # 에러 메시지 전송 확인
        mock_manager.send_error.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.api.v1.endpoints.websocket.manager")
    async def test_handle_recalculate_route_success(
        self, mock_manager, sample_session_data, sample_route_data
    ):
        """경로 재계산 - 성공"""
        mock_manager.send_message = AsyncMock()
        mock_manager.send_error = AsyncMock()

        mock_pathfinding = MagicMock()
        mock_pathfinding.calculate_route.return_value = sample_route_data

        mock_guidance = MagicMock()
        mock_guidance.find_nearest_station_name.return_value = "서울역"

        data = {"latitude": 37.5546788, "longitude": 126.9706188, "disability_type": "PHY"}

        with patch("app.api.v1.endpoints.websocket.get_redis_client") as mock_get_redis, \
             patch("app.api.v1.endpoints.websocket.save_navigation_event"):

            mock_redis = mock_get_redis.return_value
            mock_redis.get_session.return_value = sample_session_data

            await handle_recalculate_route("user123", data, mock_pathfinding, mock_guidance)

            # 경로 재계산 호출 확인
            mock_pathfinding.calculate_route.assert_called_once()

            # 메시지 전송 확인
            call_args = mock_manager.send_message.call_args[0]
            message = call_args[1]
            assert message["type"] == "route_recalculated"

    @pytest.mark.asyncio
    @patch("app.api.v1.endpoints.websocket.manager")
    async def test_handle_end_navigation_success(self, mock_manager, sample_session_data):
        """내비게이션 종료 - 성공"""
        mock_manager.send_message = AsyncMock()
        mock_manager.send_error = AsyncMock()

        with patch("app.api.v1.endpoints.websocket.get_redis_client") as mock_get_redis, \
             patch("app.api.v1.endpoints.websocket.save_navigation_event"):

            mock_redis = mock_get_redis.return_value
            mock_redis.get_session.return_value = sample_session_data
            mock_redis.delete_session = MagicMock(return_value=True)

            await handle_end_navigation("user123")

            # 세션 삭제 확인
            mock_redis.delete_session.assert_called_once_with("user123")

            # 종료 메시지 전송 확인
            call_args = mock_manager.send_message.call_args[0]
            message = call_args[1]
            assert message["type"] == "navigation_ended"

    @pytest.mark.asyncio
    @patch("app.api.v1.endpoints.websocket.manager")
    async def test_handle_end_navigation_no_session(self, mock_manager):
        """내비게이션 종료 - 세션 없음"""
        mock_manager.send_message = AsyncMock()
        mock_manager.send_error = AsyncMock()

        with patch("app.api.v1.endpoints.websocket.get_redis_client") as mock_get_redis:
            mock_redis = mock_get_redis.return_value
            mock_redis.get_session.return_value = None

            await handle_end_navigation("user123")

            # 에러 메시지 전송 확인
            mock_manager.send_error.assert_called_once()
