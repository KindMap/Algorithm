"""
Pytest 설정 및 공통 Fixture
"""

import os
import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock

# 테스트 모드 환경 변수 설정 (모듈 임포트 전에 설정해야 함)
os.environ['TESTING'] = 'true'

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 패치할 모듈을 conftest.py에서 직접 임포트합니다.
# import app.db.cache

# 현재 정의된 픽스쳐들이 실제 테스트 대상 코드에 적용되지 않고 있음
# Mock 객체가 아닌 실제 모듈을 호출하고 실제 database 모듈을 호출하여
# connectionpool 관련 에러 발생

# => 실제 DB/Cache 모듈 대신 Mock를 사용하도록 강제로 패치하는 과정 필요


def pytest_configure(config):
    """
    pytest 초기화 시점에 호출됨 (모듈 임포트 전)
    sys.modules에 Mock 모듈을 주입하여 실제 DB 연결 시도를 차단
    """
    # database 모듈을 Mock으로 대체
    mock_database = MagicMock()
    mock_database.get_db_connection = MagicMock()
    mock_database.get_db_cursor = MagicMock()
    mock_database.get_all_stations = MagicMock(return_value=[])
    mock_database.get_all_sections = MagicMock(return_value=[])
    mock_database.get_all_transfer_station_conv_scores = MagicMock(return_value=[])
    mock_database.initialize_pool = MagicMock()
    sys.modules['app.db.database'] = mock_database


@pytest.fixture
def mock_redis_client():
    """Mock Redis 클라이언트"""
    mock = MagicMock()
    mock.get.return_value = None
    mock.setex.return_value = True
    mock.delete.return_value = 1
    return mock


@pytest.fixture
def mock_redis_session_manager(mocker):
    """Mock RedisSessionManager *return MagicMock*"""
    # from app.db.redis_client import RedisSessionManager => 실제 객체를 Mocking해서 return 하면 안됨

    mock_manager = mocker.MagicMock()

    return mock_manager


@pytest.fixture
def sample_stations():
    """테스트용 샘플 역 데이터"""
    return {
        "1000000100": {
            "station_cd": "1000000100",
            "name": "서울역",
            "line": "1호선",
            "lat": 37.5546788,
            "lng": 126.9706188,
        },
        "2000000201": {
            "station_cd": "2000000201",
            "name": "강남역",
            "line": "2호선",
            "lat": 37.4979462,
            "lng": 127.0276368,
        },
        "2000000202": {
            "station_cd": "2000000202",
            "name": "역삼역",
            "line": "2호선",
            "lat": 37.5003706,
            "lng": 127.0363573,
        },
        "3000000301": {
            "station_cd": "3000000301",
            "name": "양재역",
            "line": "3호선",
            "lat": 37.4841611,
            "lng": 127.0343323,
        },
    }


@pytest.fixture
def sample_route_data():
    """테스트용 샘플 경로 데이터"""
    return {
        "origin": "서울역",
        "origin_cd": "1000000100",
        "destination": "강남역",
        "destination_cd": "2000000201",
        "routes": [
            {
                "rank": 1,
                "route_sequence": ["1000000100", "2000000201"],
                "route_lines": ["1호선", "2호선"],
                "total_time": 25.5,
                "transfers": 1,
                "transfer_stations": ["1000000100"],
                "transfer_info": [["1000000100", "1호선", "2호선"]],
                "score": 0.3542,
                "avg_convenience": 0.85,
                "avg_congestion": 0.57,
                "max_transfer_difficulty": 0.42,
            },
            {
                "rank": 2,
                "route_sequence": ["1000000100", "2000000202", "2000000201"],
                "route_lines": ["1호선", "2호선", "2호선"],
                "total_time": 30.2,
                "transfers": 1,
                "transfer_stations": ["2000000202"],
                "transfer_info": [["2000000202", "1호선", "2호선"]],
                "score": 0.4123,
                "avg_convenience": 0.78,
                "avg_congestion": 0.62,
                "max_transfer_difficulty": 0.55,
            },
            {
                "rank": 3,
                "route_sequence": ["1000000100", "3000000301", "2000000201"],
                "route_lines": ["1호선", "3호선", "2호선"],
                "total_time": 35.8,
                "transfers": 2,
                "transfer_stations": ["3000000301"],
                "transfer_info": [
                    ["3000000301", "1호선", "3호선"],
                    ["3000000301", "3호선", "2호선"],
                ],
                "score": 0.5234,
                "avg_convenience": 0.72,
                "avg_congestion": 0.68,
                "max_transfer_difficulty": 0.68,
            },
        ],
        "total_routes_found": 5,
        "routes_returned": 3,
        "route_id": "test-route-123",
    }


@pytest.fixture
def sample_session_data(sample_route_data):
    """테스트용 샘플 세션 데이터"""
    primary_route = sample_route_data["routes"][0]
    return {
        "route_id": sample_route_data["route_id"],
        "origin": sample_route_data["origin"],
        "origin_cd": sample_route_data["origin_cd"],
        "destination": sample_route_data["destination"],
        "destination_cd": sample_route_data["destination_cd"],
        "route_sequence": primary_route["route_sequence"],
        "route_lines": primary_route["route_lines"],
        "transfer_stations": primary_route["transfer_stations"],
        "transfer_info": primary_route["transfer_info"],
        "total_time": primary_route["total_time"],
        "transfers": primary_route["transfers"],
        "all_routes": sample_route_data["routes"],
        "current_station": sample_route_data["origin_cd"],
        "selected_route_rank": 1,
        "last_update": "2025-01-01T12:00:00",  # datetime.now().isoformat() => test fixture는 항상 동일한 값을 반환해야 함
    }


@pytest.fixture
def mock_db_connection():
    """Mock 데이터베이스 연결"""
    mock = MagicMock()
    return mock


@pytest.fixture
def mock_cache(sample_stations):
    """Mock 캐시"""
    return {
        "stations": sample_stations,
        "station_name_map": {
            "서울역": "1000000100",
            "강남역": "2000000201",
            "역삼역": "2000000202",
            "양재역": "3000000301",
        },
        "lines": {
            "1호선": ["1000000100"],
            "2호선": ["2000000201", "2000000202"],
            "3호선": ["3000000301"],
        },
    }


@pytest.fixture
def seoul_gps_coords():
    """서울 지역 GPS 좌표 샘플"""
    return {
        "valid": {
            "seoul_station": {"lat": 37.5546788, "lon": 126.9706188},  # 서울역
            "gangnam_station": {"lat": 37.4979462, "lon": 127.0276368},  # 강남역
            "yeoksam_station": {"lat": 37.5003706, "lon": 127.0363573},  # 역삼역
        },
        "invalid": {
            "out_of_bounds": {"lat": 40.0, "lon": 130.0},  # 서울 외 지역
            "invalid_lat": {"lat": 200.0, "lon": 127.0},  # 유효하지 않은 위도
            "invalid_lon": {"lat": 37.5, "lon": 200.0},  # 유효하지 않은 경도
        },
    }


# ============================================================
# 인증 관련 Fixtures
# ============================================================

@pytest.fixture
def sample_user():
    """테스트용 샘플 사용자 데이터"""
    from uuid import UUID
    from datetime import datetime, timezone
    from app.models.domain import User

    return User(
        user_id=UUID("12345678-1234-5678-1234-567812345678"),
        email="test@example.com",
        username="testuser",
        disability_type="PHY",
        is_active=True,
        created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        last_login=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    )


@pytest.fixture
def sample_inactive_user():
    """테스트용 비활성화된 사용자 데이터"""
    from uuid import UUID
    from datetime import datetime, timezone
    from app.models.domain import User

    return User(
        user_id=UUID("87654321-4321-8765-4321-876543218765"),
        email="inactive@example.com",
        username="inactiveuser",
        disability_type="VIS",
        is_active=False,
        created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        last_login=None
    )


@pytest.fixture
def sample_user_credentials():
    """테스트용 사용자 자격증명"""
    from app.auth.security import get_password_hash

    plain_password = "testpassword123"
    return {
        "email": "test@example.com",
        "password": plain_password,
        "password_hash": get_password_hash(plain_password),
        "wrong_password": "wrongpassword456"
    }


@pytest.fixture
def sample_tokens(sample_user):
    """테스트용 JWT 토큰"""
    from app.auth.security import create_access_token, create_refresh_token

    return {
        "access_token": create_access_token(subject=str(sample_user.user_id)),
        "refresh_token": create_refresh_token(user_id=sample_user.user_id),
    }


@pytest.fixture
def mock_auth_db_cursor(mocker):
    """인증 관련 DB 작업을 위한 Mock 커서"""
    mock_conn = mocker.MagicMock()
    mock_cursor = mocker.MagicMock()

    # Context manager 지원
    mock_conn.__enter__ = mocker.MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = mocker.MagicMock(return_value=None)
    mock_conn.cursor.return_value.__enter__ = mocker.MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = mocker.MagicMock(return_value=None)

    # 기본 동작 설정
    mock_cursor.fetchone.return_value = None
    mock_cursor.fetchall.return_value = []
    mock_cursor.rowcount = 0

    return {
        "connection": mock_conn,
        "cursor": mock_cursor
    }
