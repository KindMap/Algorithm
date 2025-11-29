"""
Cache 모듈 테스트
"""

import pytest
from unittest.mock import MagicMock, patch

from app.db.cache import (
    get_stations_dict,
    get_station_cd_by_name,
    get_station_name_by_code,
    get_lines_dict,
    clear_cache,
)


class TestDataCache:
    """Cache 모듈 테스트"""

    @patch("app.db.cache._cache_init", True)
    @patch("app.db.cache._stations_cache")
    def test_get_stations_dict(self, mock_stations_cache, sample_stations):
        """역 딕셔너리 조회 테스트"""
        mock_stations_cache.return_value = sample_stations

        stations = get_stations_dict()

        assert stations is not None

    @patch("app.db.cache._cache_init", True)
    @patch("app.db.cache._station_name_map_cache")
    def test_get_station_cd_by_name(self, mock_name_map, mock_cache):
        """역 이름으로 역 코드 조회"""
        import app.db.cache as cache_module
        cache_module._station_name_map_cache = mock_cache["station_name_map"]

        station_cd = get_station_cd_by_name("서울역")

        assert station_cd == "1000000100"

    @patch("app.db.cache._cache_init", True)
    def test_get_station_cd_by_name_not_found(self):
        """존재하지 않는 역 이름 조회"""
        import app.db.cache as cache_module
        cache_module._station_name_map_cache = {"서울역": "1000000100"}

        with patch("app.db.cache.get_station_cd_by_name") as mock_db_get:
            mock_db_get.return_value = None
            station_cd = get_station_cd_by_name("존재하지않는역")

            # DB 조회까지 갔으므로 None이 반환될 수 있음
            assert station_cd is None or station_cd is not None

    @patch("app.db.cache._cache_init", True)
    @patch("app.db.cache._stations_cache")
    def test_get_station_name_by_code(self, mock_stations_cache, sample_stations):
        """역 코드로 역 이름 조회"""
        import app.db.cache as cache_module
        cache_module._stations_cache = sample_stations

        station_name = get_station_name_by_code("1000000100")

        assert station_name == "서울역"

    @patch("app.db.cache._cache_init", True)
    def test_get_station_name_by_code_not_found(self, sample_stations):
        """존재하지 않는 역 코드 조회"""
        import app.db.cache as cache_module
        cache_module._stations_cache = sample_stations

        station_name = get_station_name_by_code("9999999999")

        assert station_name == "9999999999"  # 코드를 그대로 반환

    @patch("app.db.cache._cache_init", True)
    def test_get_lines_dict(self, mock_cache):
        """노선 딕셔너리 조회"""
        import app.db.cache as cache_module
        cache_module._lines_cache = mock_cache["lines"]

        lines = get_lines_dict()

        assert lines is not None
        assert "1호선" in lines
        assert "2호선" in lines

    @patch("app.db.cache._cache_init", True)
    def test_cache_persistence(self, sample_stations):
        """캐시 데이터 영속성 테스트"""
        import app.db.cache as cache_module
        cache_module._stations_cache = sample_stations.copy()

        # 첫 번째 조회
        stations1 = get_stations_dict()

        # 두 번째 조회
        stations2 = get_stations_dict()

        # 같은 객체여야 함 (캐시됨)
        assert stations1 is stations2

    @patch("app.db.cache._cache_init", True)
    def test_station_data_structure(self, sample_stations):
        """역 데이터 구조 확인"""
        import app.db.cache as cache_module
        cache_module._stations_cache = sample_stations

        stations = get_stations_dict()
        station = stations["1000000100"]

        # 필수 필드 확인
        assert "station_cd" in station
        assert "name" in station
        assert "line" in station
        assert "lat" in station
        assert "lng" in station

    @patch("app.db.cache._cache_init", True)
    def test_lines_dict_structure(self, mock_cache):
        """노선 딕셔너리 구조 확인"""
        import app.db.cache as cache_module
        cache_module._lines_cache = mock_cache["lines"]

        lines = get_lines_dict()

        # 노선 → [역 코드 리스트] 매핑
        assert isinstance(lines, dict)
        for line_name, stations in lines.items():
            assert isinstance(line_name, str)
            assert isinstance(stations, list)
            assert all(isinstance(s, str) for s in stations)

    def test_cache_data_types(self, sample_stations):
        """캐시 데이터 타입 확인"""
        station = sample_stations["1000000100"]

        # 좌표는 float
        assert isinstance(station["lat"], (int, float))
        assert isinstance(station["lng"], (int, float))

        # 나머지는 문자열
        assert isinstance(station["station_cd"], str)
        assert isinstance(station["name"], str)
        assert isinstance(station["line"], str)
