"""
RedisSessionManager 테스트
"""

import pytest
import json
from unittest.mock import MagicMock, patch
from datetime import datetime

from app.db.redis_client import RedisSessionManager


class TestRedisSessionManager:
    """RedisSessionManager 테스트 클래스"""

    @pytest.fixture
    def redis_manager(self, mock_redis_client):
        """RedisSessionManager 인스턴스"""
        with patch("app.db.redis_client.redis.Redis") as mock_redis_class:
            mock_redis_class.return_value = mock_redis_client
            manager = RedisSessionManager()
            manager.redis_client = mock_redis_client
            return manager

    def test_create_session(self, redis_manager, sample_route_data, mock_redis_client):
        """세션 생성 테스트"""
        mock_redis_client.setex.return_value = True

        result = redis_manager.create_session("user123", sample_route_data)

        assert result is True
        mock_redis_client.setex.assert_called_once()

        # 세션 키 확인
        call_args = mock_redis_client.setex.call_args
        session_key = call_args[0][0]
        assert session_key == "session:user123"

        # TTL 확인 (4시간 = 14400초)
        ttl = call_args[0][1]
        assert ttl == 14400

        # 세션 데이터 확인
        session_data_json = call_args[0][2]
        session_data = json.loads(session_data_json)

        assert session_data["route_id"] == sample_route_data["route_id"]
        assert session_data["origin"] == sample_route_data["origin"]
        assert session_data["destination"] == sample_route_data["destination"]
        assert session_data["selected_route_rank"] == 1

    def test_create_session_with_primary_route(
        self, redis_manager, sample_route_data, mock_redis_client
    ):
        """세션 생성 시 1순위 경로 저장 확인"""
        mock_redis_client.setex.return_value = True

        redis_manager.create_session("user123", sample_route_data)

        call_args = mock_redis_client.setex.call_args
        session_data_json = call_args[0][2]
        session_data = json.loads(session_data_json)

        primary_route = sample_route_data["routes"][0]

        # 1순위 경로 정보 확인
        assert json.loads(session_data["route_sequence"]) == primary_route["route_sequence"]
        assert json.loads(session_data["route_lines"]) == primary_route["route_lines"]
        assert session_data["total_time"] == primary_route["total_time"]
        assert session_data["transfers"] == primary_route["transfers"]

    def test_get_session_exists(self, redis_manager, sample_session_data, mock_redis_client):
        """세션 조회 - 존재하는 경우"""
        # Redis에서 반환할 데이터 준비
        stored_data = sample_session_data.copy()
        stored_data["route_sequence"] = json.dumps(stored_data["route_sequence"])
        stored_data["route_lines"] = json.dumps(stored_data["route_lines"])
        stored_data["transfer_stations"] = json.dumps(stored_data["transfer_stations"])
        stored_data["transfer_info"] = json.dumps(stored_data["transfer_info"])
        stored_data["all_routes"] = json.dumps(stored_data["all_routes"])

        mock_redis_client.get.return_value = json.dumps(stored_data)

        session = redis_manager.get_session("user123")

        assert session is not None
        assert session["route_id"] == sample_session_data["route_id"]
        assert session["origin"] == sample_session_data["origin"]
        assert isinstance(session["route_sequence"], list)
        assert isinstance(session["route_lines"], list)

    def test_get_session_not_exists(self, redis_manager, mock_redis_client):
        """세션 조회 - 존재하지 않는 경우"""
        mock_redis_client.get.return_value = None

        session = redis_manager.get_session("user123")

        assert session is None

    def test_delete_session_success(self, redis_manager, mock_redis_client):
        """세션 삭제 - 성공"""
        mock_redis_client.delete.return_value = 1

        result = redis_manager.delete_session("user123")

        assert result is True
        mock_redis_client.delete.assert_called_once_with("session:user123")

    def test_delete_session_not_exists(self, redis_manager, mock_redis_client):
        """세션 삭제 - 존재하지 않는 세션"""
        mock_redis_client.delete.return_value = 0

        result = redis_manager.delete_session("user123")

        assert result is False

    def test_switch_route_success(self, redis_manager, sample_session_data, mock_redis_client):
        """경로 변경 - 성공"""
        # get_session이 세션 데이터를 반환하도록 설정
        with patch.object(redis_manager, "get_session") as mock_get_session:
            mock_get_session.return_value = sample_session_data
            mock_redis_client.setex.return_value = True

            result = redis_manager.switch_route("user123", 2)

            assert result is True
            mock_redis_client.setex.assert_called_once()

            # 변경된 세션 데이터 확인
            call_args = mock_redis_client.setex.call_args
            session_data_json = call_args[0][2]
            session_data = json.loads(session_data_json)

            assert session_data["selected_route_rank"] == 2

    def test_switch_route_invalid_rank(self, redis_manager, sample_session_data, mock_redis_client):
        """경로 변경 - 유효하지 않은 순위"""
        with patch.object(redis_manager, "get_session") as mock_get_session:
            mock_get_session.return_value = sample_session_data

            # 0번 경로 (유효하지 않음)
            result = redis_manager.switch_route("user123", 0)
            assert result is False

            # 4번 경로 (존재하지 않음, 3개만 있음)
            result = redis_manager.switch_route("user123", 4)
            assert result is False

    def test_switch_route_no_session(self, redis_manager, mock_redis_client):
        """경로 변경 - 세션 없음"""
        with patch.object(redis_manager, "get_session") as mock_get_session:
            mock_get_session.return_value = None

            result = redis_manager.switch_route("user123", 2)

            assert result is False

    def test_update_location(self, redis_manager, sample_session_data, mock_redis_client):
        """위치 업데이트 테스트"""
        with patch.object(redis_manager, "get_session") as mock_get_session:
            mock_get_session.return_value = sample_session_data
            mock_redis_client.setex.return_value = True

            redis_manager.update_location("user123", "new_station_cd")

            mock_redis_client.setex.assert_called_once()

            # 업데이트된 데이터 확인
            call_args = mock_redis_client.setex.call_args
            session_data_json = call_args[0][2]
            session_data = json.loads(session_data_json)

            assert session_data["current_station"] == "new_station_cd"
            assert "last_update" in session_data

    def test_update_location_no_session(self, redis_manager, mock_redis_client):
        """위치 업데이트 - 세션 없음"""
        with patch.object(redis_manager, "get_session") as mock_get_session:
            mock_get_session.return_value = None

            # 예외 발생하지 않고 조용히 무시되어야 함
            redis_manager.update_location("user123", "new_station_cd")

            mock_redis_client.setex.assert_not_called()

    def test_session_ttl(self, redis_manager, sample_route_data, mock_redis_client):
        """세션 TTL 확인 (4시간)"""
        mock_redis_client.setex.return_value = True

        redis_manager.create_session("user123", sample_route_data)

        call_args = mock_redis_client.setex.call_args
        ttl = call_args[0][1]

        # 4시간 = 14400초
        assert ttl == 14400

    def test_session_key_format(self, redis_manager, sample_route_data, mock_redis_client):
        """세션 키 형식 확인"""
        mock_redis_client.setex.return_value = True

        redis_manager.create_session("test_user_456", sample_route_data)

        call_args = mock_redis_client.setex.call_args
        session_key = call_args[0][0]

        assert session_key == "session:test_user_456"
        assert session_key.startswith("session:")

    def test_all_routes_stored(self, redis_manager, sample_route_data, mock_redis_client):
        """전체 경로 정보 저장 확인"""
        mock_redis_client.setex.return_value = True

        redis_manager.create_session("user123", sample_route_data)

        call_args = mock_redis_client.setex.call_args
        session_data_json = call_args[0][2]
        session_data = json.loads(session_data_json)

        all_routes = json.loads(session_data["all_routes"])
        assert len(all_routes) == 3
        assert all_routes == sample_route_data["routes"]

    def test_switch_route_changes_correct_route(
        self, redis_manager, sample_session_data, mock_redis_client
    ):
        """경로 변경 시 올바른 경로로 변경되는지 확인"""
        with patch.object(redis_manager, "get_session") as mock_get_session:
            mock_get_session.return_value = sample_session_data
            mock_redis_client.setex.return_value = True

            result = redis_manager.switch_route("user123", 3)

            # switch_route가 성공적으로 호출되었는지 확인
            assert result is True

            # setex가 호출되었는지 확인
            mock_redis_client.setex.assert_called_once()

            call_args = mock_redis_client.setex.call_args
            if call_args and call_args[0] and len(call_args[0]) > 2:
                session_data_json = call_args[0][2]
                if session_data_json:
                    session_data = json.loads(session_data_json)
                    # 선택된 경로 순위가 3으로 변경되었는지 확인
                    assert session_data["selected_route_rank"] == 3
