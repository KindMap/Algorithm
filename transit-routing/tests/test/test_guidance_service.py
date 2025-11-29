"""
GuidanceService 테스트
"""

import pytest
import numpy as np
from unittest.mock import MagicMock, patch, Mock
from scipy.spatial import KDTree

from app.services.guidance_service import GuidanceService
from app.core.exceptions import SessionNotFoundException, InvalidLocationException


class TestGuidanceService:
    """GuidanceService 테스트 클래스"""

    @pytest.fixture
    def mock_distance_calc(self):
        """Mock DistanceCalculator"""
        mock = MagicMock()
        # 기본적으로 100m 거리 반환
        mock.calculate_distance.return_value = 100.0
        return mock

    @pytest.fixture
    def service(self, mock_redis_session_manager, mock_cache, mock_distance_calc):
        """GuidanceService 인스턴스"""
        with patch(
            "app.services.guidance_service.get_stations_dict"
        ) as mock_get_stations, patch(
            "app.services.guidance_service.get_station_name_by_code"
        ) as mock_get_name, patch(
            "app.services.guidance_service.DistanceCalculator"
        ) as mock_calc_class:

            mock_get_stations.return_value = mock_cache["stations"]
            mock_get_name.side_effect = lambda cd: next(
                (
                    s["name"]
                    for s in mock_cache["stations"].values()
                    if s["station_cd"] == cd
                ),
                cd,
            )
            mock_calc_class.return_value = mock_distance_calc

            service = GuidanceService(mock_redis_session_manager)
            return service

    def test_service_initialization(self, service):
        """서비스 초기화 테스트"""
        assert service is not None
        assert service.redis_client is not None
        assert service.distance_calc is not None
        assert service.stations is not None
        assert service.kdtree is not None
        assert isinstance(service.kdtree, KDTree)

    def test_find_nearest_station(self, service, seoul_gps_coords):
        """가장 가까운 역 찾기 테스트"""
        # 서울역 좌표로 검색
        coords = seoul_gps_coords["valid"]["seoul_station"]
        nearest = service.find_nearest_station(coords["lat"], coords["lon"])

        assert nearest is not None
        assert isinstance(nearest, str)
        # KDTree가 가장 가까운 역을 반환하는지 확인
        assert nearest in service.stations

    def test_find_nearest_station_name(self, service, seoul_gps_coords):
        """가장 가까운 역 이름 찾기 테스트"""
        coords = seoul_gps_coords["valid"]["seoul_station"]
        with patch(
            "app.services.guidance_service.get_station_name_by_code"
        ) as mock_get_name:
            mock_get_name.return_value = "서울역"
            name = service.find_nearest_station_name(coords["lat"], coords["lon"])
            assert name == "서울역"

    def test_is_valid_location_valid_coords(self, service, seoul_gps_coords):
        """유효한 GPS 좌표 검증 테스트"""
        for location_name, coords in seoul_gps_coords["valid"].items():
            assert service._is_valid_location(coords["lat"], coords["lon"]) is True

    def test_is_valid_location_invalid_coords(self, service, seoul_gps_coords):
        """유효하지 않은 GPS 좌표 검증 테스트"""
        for location_name, coords in seoul_gps_coords["invalid"].items():
            assert service._is_valid_location(coords["lat"], coords["lon"]) is False

    def test_is_valid_location_boundary_cases(self, service):
        """경계값 테스트"""
        # GPS 범위 벗어남
        assert service._is_valid_location(91.0, 127.0) is False  # 위도 초과
        assert service._is_valid_location(-91.0, 127.0) is False  # 위도 미만
        assert service._is_valid_location(37.5, 181.0) is False  # 경도 초과
        assert service._is_valid_location(37.5, -181.0) is False  # 경도 미만

        # 서울 권역 벗어남
        assert service._is_valid_location(35.0, 127.0) is False  # 서울 남쪽
        assert service._is_valid_location(40.0, 127.0) is False  # 서울 북쪽
        assert service._is_valid_location(37.5, 125.0) is False  # 서울 서쪽
        assert service._is_valid_location(37.5, 128.0) is False  # 서울 동쪽

    def test_get_navigation_guidance_invalid_location(
        self, service, seoul_gps_coords, mock_redis_session_manager, sample_session_data
    ):
        """유효하지 않은 위치로 안내 요청"""
        mock_redis_session_manager.get_session.return_value = sample_session_data
        invalid_coords = seoul_gps_coords["invalid"]["out_of_bounds"]

        with pytest.raises(InvalidLocationException):
            service.get_navigation_guidance(
                "user123", invalid_coords["lat"], invalid_coords["lon"]
            )

    def test_get_navigation_guidance_no_session(
        self, service, seoul_gps_coords, mock_redis_session_manager
    ):
        """세션 없이 안내 요청"""
        mock_redis_session_manager.get_session.return_value = None
        coords = seoul_gps_coords["valid"]["seoul_station"]

        with pytest.raises(SessionNotFoundException):
            service.get_navigation_guidance("user123", coords["lat"], coords["lon"])

    def test_get_navigation_guidance_on_route(
        self, service, seoul_gps_coords, mock_redis_session_manager, sample_session_data
    ):
        """경로 상에 있을 때 안내"""
        mock_redis_session_manager.get_session.return_value = sample_session_data
        coords = seoul_gps_coords["valid"]["seoul_station"]

        # find_nearest_station이 경로의 첫 번째 역 반환하도록 Mock
        with patch.object(service, "find_nearest_station") as mock_find:
            mock_find.return_value = sample_session_data["route_sequence"][0]

            guidance = service.get_navigation_guidance(
                "user123", coords["lat"], coords["lon"]
            )

            assert guidance is not None
            assert "current_station" in guidance
            assert "next_station" in guidance
            assert "distance_to_next" in guidance
            assert "progress_percent" in guidance
            assert "message" in guidance

    def test_get_navigation_guidance_route_deviation(
        self, service, seoul_gps_coords, mock_redis_session_manager, sample_session_data
    ):
        """경로 이탈 감지"""
        mock_redis_session_manager.get_session.return_value = sample_session_data
        coords = seoul_gps_coords["valid"]["gangnam_station"]

        # 경로에 없는 역 반환
        with patch.object(service, "find_nearest_station") as mock_find:
            mock_find.return_value = "9999999999"  # 경로에 없는 역

            guidance = service.get_navigation_guidance(
                "user123", coords["lat"], coords["lon"]
            )

            assert guidance["recalculate"] is True
            assert "message" in guidance
            assert "경로를 이탈" in guidance["message"]

    def test_get_navigation_guidance_arrival(
        self, service, seoul_gps_coords, mock_redis_session_manager, sample_session_data
    ):
        """목적지 도착 감지"""
        mock_redis_session_manager.get_session.return_value = sample_session_data
        coords = seoul_gps_coords["valid"]["gangnam_station"]

        # 목적지 역 반환
        with patch.object(service, "find_nearest_station") as mock_find:
            mock_find.return_value = sample_session_data["destination_cd"]

            guidance = service.get_navigation_guidance(
                "user123", coords["lat"], coords["lon"]
            )

            assert guidance["arrived"] is True
            assert "도착" in guidance["message"]
            assert guidance["destination"] == sample_session_data["destination"]

    def test_get_navigation_guidance_transfer_station(
        self, service, seoul_gps_coords, mock_redis_session_manager, sample_session_data
    ):
        """환승역에서 안내"""
        # 환승 정보가 있는 경로 데이터 설정
        session_with_transfer = sample_session_data.copy()
        session_with_transfer["route_sequence"] = ["1000000100", "2000000201"]
        session_with_transfer["transfer_stations"] = ["2000000201"]
        session_with_transfer["transfer_info"] = [["2000000201", "1호선", "2호선"]]

        mock_redis_session_manager.get_session.return_value = session_with_transfer
        coords = seoul_gps_coords["valid"]["seoul_station"]

        with patch.object(service, "find_nearest_station") as mock_find:
            mock_find.return_value = "1000000100"  # 첫 번째 역

            guidance = service.get_navigation_guidance(
                "user123", coords["lat"], coords["lon"]
            )

            assert guidance["is_transfer"] is True
            assert "transfer_from_line" in guidance
            assert "transfer_to_line" in guidance
            assert "환승" in guidance["message"]

    def test_get_navigation_guidance_progress_calculation(
        self, service, seoul_gps_coords, mock_redis_session_manager, mocker
    ):
        """진행률 계산 테스트"""
        # 5개 역이 있는 경로
        session = {
            "route_id": "test-123",
            "origin": "역1",
            "origin_cd": "cd1",
            "destination": "역5",
            "destination_cd": "cd5",
            "route_sequence": ["cd1", "cd2", "cd3", "cd4", "cd5"],
            "route_lines": ["1호선"] * 5,
            "transfer_stations": [],
            "transfer_info": [],
        }

        # 2. 가짜 역 정보 (self.stations를 덮어쓸 데이터)
        fake_stations_dict = {
            station_cd: {
                "station_cd": station_cd,
                "name": f"역{station_cd[-1]}",
                "lat": 37.0 + i * 0.01, # KDTree가 동일 좌표를 갖지 않도록 약간씩 다르게 설정
                "lng": 127.0 + i * 0.01,
            }
            for i, station_cd in enumerate(["cd1", "cd2", "cd3", "cd4", "cd5"])
        }

        # --- 여기가 핵심 수정 ---
        # 3. 서비스의 'self.stations'를 가짜 데이터로 직접 덮어쓰기
        service.stations = fake_stations_dict

        # 4. 'self.stations'가 바뀌었으므로 KDTree와 리스트도 다시 빌드
        station_coords = []
        service.station_cd_list = []
        for station_cd, info in service.stations.items():
            station_coords.append([info["lat"], info["lng"]])
            service.station_cd_list.append(station_cd)
        service.kdtree = KDTree(np.array(station_coords))
        # ------------------------

        # 5. Redis Mock 설정
        mock_redis_session_manager.get_session.return_value = session
        coords = seoul_gps_coords["valid"]["seoul_station"] # 이 좌표는 어차피 Mocking됨

        # 6. 'find_nearest_station' Mock (현재 역)
        #    (이제 service.kdtree가 "cd" 코드를 반환하므로 patch.object가 필요 없을 수도 있으나,
        #     테스트의 일관성을 위해 "cd3"을 반환하도록 명시하는 것이 좋습니다.)
        with patch.object(service, "find_nearest_station") as mock_find:
            mock_find.return_value = "cd3" # 현재 역을 "cd3"으로 설정

            # 7. 테스트 실행
            guidance = service.get_navigation_guidance("user123", coords["lat"], coords["lon"])

            # 8. 검증
            assert guidance["progress_percent"] == 50
            assert guidance["remaining_stations"] == 2

    def test_get_navigation_guidance_updates_location(
        self, service, seoul_gps_coords, mock_redis_session_manager, sample_session_data
    ):
        """위치 업데이트 확인"""
        mock_redis_session_manager.get_session.return_value = sample_session_data
        coords = seoul_gps_coords["valid"]["seoul_station"]

        with patch.object(service, "find_nearest_station") as mock_find:
            mock_find.return_value = sample_session_data["route_sequence"][0]

            service.get_navigation_guidance("user123", coords["lat"], coords["lon"])

            # update_location이 호출되었는지 확인
            mock_redis_session_manager.update_location.assert_called_once()

    def test_kdtree_performance(self, service):
        """KD-Tree 성능 테스트 (빠른 검색)"""
        import time

        coords = (37.5546788, 126.9706188)  # 서울역 좌표

        # 100번 검색 수행
        start_time = time.time()
        for _ in range(100):
            service.find_nearest_station(coords[0], coords[1])
        end_time = time.time()

        # 100번 검색이 1초 이내에 완료되어야 함 (충분히 빠름)
        assert (end_time - start_time) < 1.0

    def test_distance_to_next_calculation(
        self,
        service,
        seoul_gps_coords,
        mock_redis_session_manager,
        sample_session_data,
        mock_distance_calc,
    ):
        """다음 역까지 거리 계산 테스트"""
        mock_redis_session_manager.get_session.return_value = sample_session_data
        coords = seoul_gps_coords["valid"]["seoul_station"]

        # 거리 계산 mock 설정
        mock_distance_calc.calculate_distance.return_value = 250.5

        with patch.object(service, "find_nearest_station") as mock_find:
            mock_find.return_value = sample_session_data["route_sequence"][0]

            guidance = service.get_navigation_guidance(
                "user123", coords["lat"], coords["lon"]
            )

            # 거리가 반올림되어 반환되는지 확인
            assert guidance["distance_to_next"] == 250.5
            assert isinstance(guidance["distance_to_next"], float)
