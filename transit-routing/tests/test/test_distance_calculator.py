"""
DistanceCalculator 테스트
"""

import pytest
import math
from app.algorithms.distance_calculator import DistanceCalculator


class TestDistanceCalculator:
    """DistanceCalculator 테스트 클래스"""

    @pytest.fixture
    def calculator(self):
        """DistanceCalculator 인스턴스"""
        return DistanceCalculator()

    def test_calculate_distance_same_point(self, calculator):
        """동일한 지점 간 거리 계산 (0이어야 함)"""
        lat, lon = 37.5546788, 126.9706188  # 서울역

        distance = calculator.calculate_distance(lat, lon, lat, lon)

        assert distance == 0.0

    def test_calculate_distance_known_locations(self, calculator):
        """알려진 위치 간 거리 계산"""
        # 서울역 (37.5546788, 126.9706188)
        # 강남역 (37.4979462, 127.0276368)
        # 실제 거리: 약 7.3km

        seoul_lat, seoul_lon = 37.5546788, 126.9706188
        gangnam_lat, gangnam_lon = 37.4979462, 127.0276368

        distance = calculator.calculate_distance(
            seoul_lat, seoul_lon, gangnam_lat, gangnam_lon
        )

        # 대략 8.0km (±500m 오차 허용)
        assert 7500 < distance < 8500

    def test_haversine_formula_accuracy(self, calculator):
        """Haversine 공식 정확도 테스트"""
        # 역삼역 (37.5003706, 127.0363573)
        # 강남역 (37.4979462, 127.0276368)
        # 실제 거리: 약 750m

        yeoksam_lat, yeoksam_lon = 37.5003706, 127.0363573
        gangnam_lat, gangnam_lon = 37.4979462, 127.0276368

        distance = calculator.calculate_distance(
            yeoksam_lat, yeoksam_lon, gangnam_lat, gangnam_lon
        )

        # 750m ~ 850m 범위
        assert 750 < distance < 850

    def test_calculate_distance_short_distance(self, calculator):
        """짧은 거리 계산 (100m 이내)"""
        # 매우 가까운 두 지점
        lat1, lon1 = 37.5546788, 126.9706188
        lat2, lon2 = 37.5547788, 126.9707188  # 약 100m 차이

        distance = calculator.calculate_distance(lat1, lon1, lat2, lon2)

        # 10m ~ 150m 범위 (실제로는 약 14m)
        assert 10 < distance < 150

    def test_calculate_distance_long_distance(self, calculator):
        """긴 거리 계산"""
        # 서울 (37.5546788, 126.9706188)
        # 부산 (35.1796, 129.0756)
        # 실제 거리: 약 325km

        seoul_lat, seoul_lon = 37.5546788, 126.9706188
        busan_lat, busan_lon = 35.1796, 129.0756

        distance = calculator.calculate_distance(
            seoul_lat, seoul_lon, busan_lat, busan_lon
        )

        # 320km ~ 330km 범위
        assert 320000 < distance < 330000

    def test_distance_symmetry(self, calculator):
        """거리 계산의 대칭성 테스트 (A→B == B→A)"""
        lat1, lon1 = 37.5546788, 126.9706188  # 서울역
        lat2, lon2 = 37.4979462, 127.0276368  # 강남역

        distance1 = calculator.calculate_distance(lat1, lon1, lat2, lon2)
        distance2 = calculator.calculate_distance(lat2, lon2, lat1, lon1)

        assert distance1 == distance2

    def test_calculate_distance_returns_meters(self, calculator):
        """거리가 미터 단위로 반환되는지 확인"""
        lat1, lon1 = 37.5546788, 126.9706188
        lat2, lon2 = 37.4979462, 127.0276368

        distance = calculator.calculate_distance(lat1, lon1, lat2, lon2)

        # 결과가 미터 단위 (km가 아님)
        assert distance > 1000  # 7km 이상
        assert isinstance(distance, float)

    def test_distance_positive_values(self, calculator):
        """거리는 항상 양수여야 함"""
        test_coords = [
            (37.5546788, 126.9706188, 37.4979462, 127.0276368),
            (37.5, 127.0, 37.6, 127.1),
            (37.0, 126.5, 38.0, 127.5),
        ]

        for lat1, lon1, lat2, lon2 in test_coords:
            distance = calculator.calculate_distance(lat1, lon1, lat2, lon2)
            assert distance >= 0

    def test_radian_conversion(self, calculator):
        """각도→라디안 변환 테스트"""
        # Haversine 공식은 라디안을 사용해야 함
        # 테스트: 45도 = π/4 라디안

        degrees = 45
        radians = math.radians(degrees)

        assert abs(radians - (math.pi / 4)) < 0.0001

    def test_earth_radius_constant(self, calculator):
        """지구 반지름 상수 확인"""
        # Haversine 공식에서 사용하는 지구 반지름
        # 일반적으로 6371km 사용

        # DistanceCalculator 구현에서 사용하는 값 확인
        # (실제 구현을 보고 확인 필요)
        lat1, lon1 = 0, 0
        lat2, lon2 = 0, 1  # 경도 1도 차이

        distance = calculator.calculate_distance(lat1, lon1, lat2, lon2)

        # 적도에서 경도 1도 ≈ 111km
        assert 110000 < distance < 112000

    def test_multiple_calculations_consistency(self, calculator):
        """여러 번 계산해도 일관된 결과"""
        lat1, lon1 = 37.5546788, 126.9706188
        lat2, lon2 = 37.4979462, 127.0276368

        distances = [
            calculator.calculate_distance(lat1, lon1, lat2, lon2)
            for _ in range(10)
        ]

        # 모든 계산 결과가 동일해야 함
        assert len(set(distances)) == 1

    def test_north_south_distance(self, calculator):
        """남북 방향 거리 계산"""
        # 같은 경도, 위도만 다름
        lat1, lon = 37.0, 127.0
        lat2 = 38.0  # 위도 1도 차이

        distance = calculator.calculate_distance(lat1, lon, lat2, lon)

        # 위도 1도 ≈ 111km
        assert 110000 < distance < 112000

    def test_east_west_distance(self, calculator):
        """동서 방향 거리 계산"""
        # 같은 위도, 경도만 다름
        lat, lon1 = 37.5, 127.0
        lon2 = 128.0  # 경도 1도 차이

        distance = calculator.calculate_distance(lat, lon1, lat, lon2)

        # 위도 37.5도에서 경도 1도 ≈ 88km
        assert 85000 < distance < 91000

    def test_diagonal_distance(self, calculator):
        """대각선 방향 거리 계산"""
        lat1, lon1 = 37.0, 127.0
        lat2, lon2 = 38.0, 128.0

        distance = calculator.calculate_distance(lat1, lon1, lat2, lon2)

        # 대각선 거리는 남북 + 동서보다 작아야 함
        north_south = calculator.calculate_distance(lat1, lon1, lat2, lon1)
        east_west = calculator.calculate_distance(lat1, lon1, lat1, lon2)

        assert distance < (north_south + east_west)
        assert distance > max(north_south, east_west)
