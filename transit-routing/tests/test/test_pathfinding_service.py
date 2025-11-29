"""
PathfindingService 테스트
"""

import pytest
from unittest.mock import MagicMock, patch, Mock
from datetime import datetime

from app.services.pathfinding_service import PathfindingService
from app.core.exceptions import StationNotFoundException, RouteNotFoundException


class TestPathfindingService:
    """PathfindingService 테스트 클래스"""

    @pytest.fixture
    def mock_cache_functions(self, mock_cache):
        """캐시 함수 Mock"""
        with patch("app.services.pathfinding_service.get_stations_dict") as mock_get_stations, \
             patch("app.services.pathfinding_service.get_station_cd_by_name") as mock_get_cd:

            mock_get_stations.return_value = mock_cache["stations"]
            mock_get_cd.side_effect = lambda name: mock_cache["station_name_map"].get(name)

            yield {
                "get_stations_dict": mock_get_stations,
                "get_station_cd_by_name": mock_get_cd,
            }

    @pytest.fixture
    def mock_raptor(self):
        """Mock McRaptor"""
        mock = MagicMock()

        # Mock Label 객체
        mock_label = MagicMock()
        mock_label.arrival_time = 25.5
        mock_label.transfers = 1
        mock_label.avg_convenience = 0.85
        mock_label.avg_congestion = 0.57
        mock_label.max_transfer_difficulty = 0.42
        mock_label.reconstruct_route.return_value = ["1000000100", "2000000201"]
        mock_label.reconstruct_lines.return_value = ["1호선", "2호선"]
        mock_label.reconstruct_transfer_info.return_value = [["1000000100", "1호선", "2호선"]]

        mock.find_routes.return_value = [mock_label]
        mock.rank_routes.return_value = [(mock_label, 0.3542)]

        return mock

    @pytest.fixture
    def service(self, mock_cache_functions, mock_raptor):
        """PathfindingService 인스턴스"""
        with patch("app.services.pathfinding_service.McRaptor") as mock_raptor_class:
            mock_raptor_class.return_value = mock_raptor
            service = PathfindingService()
            return service

    def test_service_initialization(self, service):
        """서비스 초기화 테스트"""
        assert service is not None
        assert service.stations is not None
        assert service.raptor is not None

    def test_calculate_route_success(self, service, mock_cache_functions):
        """정상적인 경로 계산 테스트"""
        result = service.calculate_route("서울역", "강남역", "PHY")

        assert result is not None
        assert result["origin"] == "서울역"
        assert result["destination"] == "강남역"
        assert result["origin_cd"] == "1000000100"
        assert result["destination_cd"] == "2000000201"
        assert len(result["routes"]) == 1
        assert result["routes"][0]["rank"] == 1
        assert result["routes"][0]["total_time"] == 25.5
        assert result["routes"][0]["transfers"] == 1

    def test_calculate_route_invalid_origin(self, service, mock_cache_functions):
        """유효하지 않은 출발지로 경로 계산 시도"""
        mock_cache_functions["get_station_cd_by_name"].side_effect = lambda name: None

        with pytest.raises(StationNotFoundException) as exc_info:
            service.calculate_route("존재하지않는역", "강남역", "PHY")

        assert "출발지 역을 찾을 수 없습니다" in str(exc_info.value.message)

    def test_calculate_route_invalid_destination(self, service, mock_cache_functions):
        """유효하지 않은 목적지로 경로 계산 시도"""
        def get_cd_side_effect(name):
            if name == "서울역":
                return "1000000100"
            return None

        mock_cache_functions["get_station_cd_by_name"].side_effect = get_cd_side_effect

        with pytest.raises(StationNotFoundException) as exc_info:
            service.calculate_route("서울역", "존재하지않는역", "PHY")

        assert "목적지 역을 찾을 수 없습니다" in str(exc_info.value.message)

    def test_calculate_route_no_routes_found(self, service, mock_raptor):
        """경로를 찾을 수 없는 경우"""
        mock_raptor.find_routes.return_value = []

        with pytest.raises(RouteNotFoundException) as exc_info:
            service.calculate_route("서울역", "강남역", "PHY")

        assert "경로를 찾을 수 없습니다" in str(exc_info.value.message)

    def test_calculate_route_multiple_routes(self, service, mock_raptor):
        """여러 경로 반환 테스트"""
        # 3개의 Mock 라벨 생성
        mock_labels = []
        for i in range(3):
            label = MagicMock()
            label.arrival_time = 25.5 + i * 5
            label.transfers = i
            label.avg_convenience = 0.85 - i * 0.05
            label.avg_congestion = 0.57 + i * 0.05
            label.max_transfer_difficulty = 0.42 + i * 0.1
            label.reconstruct_route.return_value = [f"station_{j}" for j in range(i + 2)]
            label.reconstruct_lines.return_value = [f"{i + 1}호선"] * (i + 2)
            label.reconstruct_transfer_info.return_value = [[f"transfer_{i}", f"{i}호선", f"{i + 1}호선"]]
            mock_labels.append(label)

        mock_raptor.find_routes.return_value = mock_labels
        mock_raptor.rank_routes.return_value = [(label, 0.3 + i * 0.1) for i, label in enumerate(mock_labels)]

        result = service.calculate_route("서울역", "강남역", "PHY")

        assert len(result["routes"]) == 3
        assert result["routes"][0]["rank"] == 1
        assert result["routes"][1]["rank"] == 2
        assert result["routes"][2]["rank"] == 3

    def test_calculate_route_all_disability_types(self, service):
        """모든 장애 유형에 대한 경로 계산 테스트"""
        disability_types = ["PHY", "VIS", "AUD", "ELD"]

        for disability_type in disability_types:
            result = service.calculate_route("서울역", "강남역", disability_type)
            assert result is not None
            assert len(result["routes"]) > 0

    def test_calculate_route_max_rounds(self, service, mock_raptor):
        """최대 라운드 설정 확인"""
        service.calculate_route("서울역", "강남역", "PHY")

        # find_routes가 max_rounds=5로 호출되었는지 확인
        call_args = mock_raptor.find_routes.call_args
        assert call_args[1]["max_rounds"] == 5

    def test_route_info_rounding(self, service):
        """경로 정보의 반올림 처리 확인"""
        result = service.calculate_route("서울역", "강남역", "PHY")
        route = result["routes"][0]

        # 반올림 확인
        assert isinstance(route["total_time"], float)
        assert isinstance(route["score"], float)
        assert isinstance(route["avg_convenience"], float)
        assert isinstance(route["avg_congestion"], float)
        assert isinstance(route["max_transfer_difficulty"], float)

        # 소수점 자릿수 확인
        assert len(str(route["total_time"]).split(".")[-1]) <= 1
        assert len(str(route["score"]).split(".")[-1]) <= 4
        assert len(str(route["avg_convenience"]).split(".")[-1]) <= 2

    def test_route_transfer_info(self, service):
        """환승 정보 구성 테스트"""
        result = service.calculate_route("서울역", "강남역", "PHY")
        route = result["routes"][0]

        assert "transfer_stations" in route
        assert "transfer_info" in route
        assert len(route["transfer_stations"]) == len(route["transfer_info"])
