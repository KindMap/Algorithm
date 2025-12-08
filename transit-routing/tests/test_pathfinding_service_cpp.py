# PathfindingServiceCPP 테스트

import pytest
import logging
from datetime import datetime

from app.services.pathfinding_service_cpp import PathfindingServiceCPP
from app.core.exceptions import StationNotFoundException, RouteNotFoundException

logger = logging.getLogger(__name__)


class TestPathfindingServiceCPP:
    """PathfindingServiceCPP 통합 테스트"""

    @pytest.fixture(scope="class")
    def service(self):
        """테스트용 PathfindingServiceCPP 인스턴스"""
        try:
            service = PathfindingServiceCPP()
            logger.info("PathfindingServiceCPP 초기화 성공")
            return service
        except RuntimeError as e:
            pytest.skip(f"C++ 모듈을 사용할 수 없습니다: {e}")

    def test_service_initialization(self, service):
        """서비스 초기화 테스트"""
        assert service is not None
        assert service.cpp_engine is not None
        assert service.data_container is not None
        assert service.stations is not None
        assert service.redis_client is not None
        logger.info("✓ 서비스 초기화 테스트 통과")

    def test_calculate_route_basic(self, service):
        """기본 경로 계산 테스트"""
        result = service.calculate_route(
            origin_name="강남",
            destination_name="서울역",
            disability_type="PHY",
        )

        assert result is not None
        assert "routes" in result
        assert len(result["routes"]) > 0
        assert result["origin"] == "강남"
        assert result["destination"] == "서울역"

        # 첫 번째 경로 검증
        route = result["routes"][0]
        assert route["rank"] == 1
        assert "route_sequence" in route
        assert "route_lines" in route
        assert "total_time" in route
        assert "transfers" in route
        assert "score" in route

        logger.info(f"✓ 기본 경로 계산 테스트 통과: {len(result['routes'])}개 경로 발견")

    def test_calculate_route_all_disability_types(self, service):
        """모든 장애 유형별 경로 계산 테스트"""
        disability_types = ["PHY", "VIS", "AUD", "ELD"]

        for dtype in disability_types:
            result = service.calculate_route(
                origin_name="강남", destination_name="잠실", disability_type=dtype
            )

            assert result is not None
            assert len(result["routes"]) > 0

            # 장애 유형별로 다른 경로가 나올 수 있음 (ANP 가중치 차이)
            logger.info(
                f"✓ {dtype} 경로 계산 성공: "
                f"{len(result['routes'])}개 경로, "
                f"최적 경로 점수={result['routes'][0]['score']}"
            )

    def test_calculate_route_with_transfers(self, service):
        """환승이 포함된 경로 테스트"""
        result = service.calculate_route(
            origin_name="강남", destination_name="홍대입구", disability_type="PHY"
        )

        assert result is not None
        assert len(result["routes"]) > 0

        # 환승 정보 검증
        route = result["routes"][0]
        if route["transfers"] > 0:
            assert "transfer_stations" in route
            assert "transfer_info" in route
            assert len(route["transfer_stations"]) == route["transfers"]
            assert len(route["transfer_info"]) == route["transfers"]

            # 환승 정보 구조 검증
            for transfer in route["transfer_info"]:
                assert len(transfer) == 3  # (station_cd, from_line, to_line)
                assert isinstance(transfer[0], str)  # station_cd
                assert isinstance(transfer[1], str)  # from_line
                assert isinstance(transfer[2], str)  # to_line

            logger.info(
                f"✓ 환승 경로 테스트 통과: {route['transfers']}회 환승, "
                f"환승역={route['transfer_stations']}"
            )
        else:
            logger.info("✓ 직통 경로 (환승 없음)")

    def test_calculate_route_performance(self, service):
        """성능 테스트 (캐시 미스)"""
        import time

        # 캐시를 우회하기 위해 매번 다른 경로 테스트
        test_cases = [
            ("강남", "서울역"),
            ("잠실", "홍대입구"),
            ("신림", "종로3가"),
        ]

        for origin, destination in test_cases:
            start_time = time.time()

            result = service.calculate_route(
                origin_name=origin, destination_name=destination, disability_type="PHY"
            )

            elapsed_time = (time.time() - start_time) * 1000  # ms

            assert result is not None
            logger.info(
                f"✓ 성능 테스트: {origin} → {destination}, "
                f"응답시간={elapsed_time:.1f}ms, "
                f"경로 수={len(result['routes'])}"
            )

            # 성능 기준: 첫 계산은 2초 이내 (C++ 최적화)
            assert elapsed_time < 2000, f"응답시간 초과: {elapsed_time:.1f}ms > 2000ms"

    def test_calculate_route_cache_hit(self, service):
        """캐시 히트 성능 테스트"""
        import time

        # 첫 번째 호출 (캐시 미스)
        _ = service.calculate_route(
            origin_name="강남", destination_name="역삼", disability_type="PHY"
        )

        # 두 번째 호출 (캐시 히트)
        start_time = time.time()
        result = service.calculate_route(
            origin_name="강남", destination_name="역삼", disability_type="PHY"
        )
        elapsed_time = (time.time() - start_time) * 1000  # ms

        assert result is not None
        logger.info(f"✓ 캐시 히트 성능: {elapsed_time:.1f}ms")

        # 캐시 히트는 50ms 이내 (Redis 조회)
        assert elapsed_time < 50, f"캐시 응답시간 초과: {elapsed_time:.1f}ms > 50ms"

    def test_station_not_found(self, service):
        """존재하지 않는 역 테스트"""
        with pytest.raises(StationNotFoundException) as exc_info:
            service.calculate_route(
                origin_name="존재하지않는역",
                destination_name="서울역",
                disability_type="PHY",
            )

        assert "출발지 역을 찾을 수 없습니다" in str(exc_info.value)
        logger.info("✓ 출발지 역 없음 예외 처리 성공")

        with pytest.raises(StationNotFoundException) as exc_info:
            service.calculate_route(
                origin_name="강남",
                destination_name="존재하지않는역",
                disability_type="PHY",
            )

        assert "목적지 역을 찾을 수 없습니다" in str(exc_info.value)
        logger.info("✓ 목적지 역 없음 예외 처리 성공")

    def test_route_metrics(self, service):
        """경로 메트릭 검증"""
        result = service.calculate_route(
            origin_name="강남", destination_name="서울역", disability_type="PHY"
        )

        route = result["routes"][0]

        # 메트릭 범위 검증
        assert route["total_time"] > 0, "총 소요시간은 0보다 커야 함"
        assert route["transfers"] >= 0, "환승 횟수는 0 이상이어야 함"
        assert 0 <= route["avg_convenience"] <= 5, "평균 편의도는 0~5 범위"
        assert route["avg_congestion"] >= 0, "평균 혼잡도는 0 이상"
        assert (
            0 <= route["max_transfer_difficulty"] <= 1
        ), "환승 난이도는 0~1 범위"
        assert route["score"] > 0, "ANP 점수는 0보다 커야 함"

        logger.info(
            f"✓ 메트릭 검증 통과: "
            f"시간={route['total_time']}분, "
            f"환승={route['transfers']}회, "
            f"편의도={route['avg_convenience']}, "
            f"혼잡도={route['avg_congestion']}, "
            f"난이도={route['max_transfer_difficulty']}, "
            f"점수={route['score']}"
        )

    def test_top_3_routes(self, service):
        """상위 3개 경로 반환 검증"""
        result = service.calculate_route(
            origin_name="강남", destination_name="홍대입구", disability_type="PHY"
        )

        # 최대 3개 경로 반환
        assert len(result["routes"]) <= 3

        # 순위 검증
        for i, route in enumerate(result["routes"], start=1):
            assert route["rank"] == i

        # 점수 순서 검증 (오름차순 - 낮을수록 좋음)
        if len(result["routes"]) > 1:
            for i in range(len(result["routes"]) - 1):
                assert (
                    result["routes"][i]["score"] <= result["routes"][i + 1]["score"]
                ), "경로는 점수 오름차순으로 정렬되어야 함"

        logger.info(
            f"✓ 상위 3개 경로 테스트 통과: {len(result['routes'])}개 경로, "
            f"점수 범위=[{result['routes'][0]['score']}, "
            f"{result['routes'][-1]['score']}]"
        )

    def test_compare_with_python_version(self, service):
        """Python 버전과 결과 비교 (선택적)"""
        try:
            from app.services.pathfinding_service import PathfindingService

            python_service = PathfindingService()

            # 동일한 경로 계산
            cpp_result = service.calculate_route(
                origin_name="강남", destination_name="서울역", disability_type="PHY"
            )

            python_result = python_service.calculate_route(
                origin_name="강남", destination_name="서울역", disability_type="PHY"
            )

            # 기본 구조 비교
            assert cpp_result["origin"] == python_result["origin"]
            assert cpp_result["destination"] == python_result["destination"]

            # 경로 수가 비슷해야 함 (완전히 동일하지 않을 수 있음 - 부동소수점 차이)
            assert abs(len(cpp_result["routes"]) - len(python_result["routes"])) <= 1

            logger.info(
                f"✓ Python 버전 비교: "
                f"C++={len(cpp_result['routes'])}개, "
                f"Python={len(python_result['routes'])}개 경로"
            )

        except ImportError:
            pytest.skip("Python PathfindingService를 사용할 수 없습니다")


# 통합 테스트 실행 함수
def test_full_integration():
    """전체 통합 테스트"""
    logger.info("=" * 60)
    logger.info("PathfindingServiceCPP 통합 테스트 시작")
    logger.info("=" * 60)

    try:
        service = PathfindingServiceCPP()

        # 여러 경로 테스트
        test_routes = [
            ("강남", "서울역", "PHY"),
            ("잠실", "홍대입구", "VIS"),
            ("신림", "종로3가", "AUD"),
            ("역삼", "신촌", "ELD"),
        ]

        for origin, destination, dtype in test_routes:
            result = service.calculate_route(origin, destination, dtype)
            logger.info(
                f"✓ {origin} → {destination} ({dtype}): "
                f"{len(result['routes'])}개 경로, "
                f"최적={result['routes'][0]['total_time']}분"
            )

        logger.info("=" * 60)
        logger.info("모든 통합 테스트 통과!")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"통합 테스트 실패: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    # 직접 실행 시 통합 테스트만 수행
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    test_full_integration()
