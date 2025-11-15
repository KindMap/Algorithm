from dotenv import load_dotenv

load_dotenv()
import logging
import time
from datetime import datetime
from database import initialize_pool, close_pool, get_db_cursor
from mc_raptor import McRaptor
from anp_weights import ANPWeightCalculator


# 로깅 설정
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def get_station_cd_by_name(station_name: str) -> str:
    """역 이름으로 station_cd 조회 (유연한 검색)"""

    # 입력값 전처리 (앞뒤 공백 제거)
    station_name = station_name.strip()

    # 1단계: 정확히 일치하는 역 찾기 (TRIM 적용)
    query_exact = """
    SELECT station_cd, name, line
    FROM subway_station
    WHERE TRIM(name) = %(station_name)s
    LIMIT 1
    """

    with get_db_cursor() as cursor:
        cursor.execute(query_exact, {"station_name": station_name})
        result = cursor.fetchone()

        if result:
            logger.debug(
                f"역 찾음 (정확 일치): {result['name']} ({result['line']}) - {result['station_cd']}"
            )
            return result["station_cd"]

        # 2단계: 부분 일치 검색 (LIKE 사용)
        query_like = """
        SELECT station_cd, name, line
        FROM subway_station
        WHERE TRIM(name) LIKE %(pattern)s
        LIMIT 1
        """

        cursor.execute(query_like, {"pattern": f"%{station_name}%"})
        result = cursor.fetchone()

        if result:
            logger.debug(
                f"역 찾음 (부분 일치): {result['name']} ({result['line']}) - {result['station_cd']}"
            )
            return result["station_cd"]
        else:
            raise ValueError(f"역을 찾을 수 없음: {station_name}")


def get_station_name_by_cd(raptor: McRaptor, station_cd: str) -> str:
    """station_cd로 역 이름 조회"""
    station_info = raptor.stations.get(station_cd, {})
    return station_info.get("station_name", station_cd)


def print_route_details(raptor: McRaptor, route, route_num: int, score: float):
    """경로 상세 정보 출력 (출발역, 환승역, 도착역만)"""

    # 전체 경로 재구성
    full_route = route.reconstruct_route()
    route_lines = route.reconstruct_lines()
    transfer_info = route.reconstruct_transfer_info()

    if not full_route:
        logger.warning(f"경로 {route_num}: 경로 정보를 재구성할 수 없습니다.")
        return

    # 출발역
    origin_cd = full_route[0]
    origin_name = get_station_name_by_cd(raptor, origin_cd)
    origin_line = route_lines[0] if route_lines else "알 수 없음"

    # 도착역
    destination_cd = full_route[-1]
    destination_name = get_station_name_by_cd(raptor, destination_cd)
    destination_line = route_lines[-1] if route_lines else "알 수 없음"

    logger.info("-" * 60)
    logger.info(f"경로 {route_num}:")
    logger.info(f"  출발역: {origin_name} ({origin_line})")

    # 환승역 출력
    if transfer_info:
        for idx, (transfer_station_cd, from_line, to_line) in enumerate(
            transfer_info, 1
        ):
            transfer_name = get_station_name_by_cd(raptor, transfer_station_cd)
            logger.info(f"  환승역 {idx}: {transfer_name} ({from_line} → {to_line})")
    else:
        logger.info(f"  환승역: 없음 (직통)")

    logger.info(f"  도착역: {destination_name} ({destination_line})")
    logger.info(f"")
    logger.info(f"  환승 횟수: {route.transfers}회")
    logger.info(f"  소요 시간: {route.arrival_time:.1f}분")
    logger.info(f"  평균 편의도: {route.avg_convenience:.2f}")
    logger.info(f"  평균 혼잡도: {route.avg_congestion:.2f}")
    logger.info(f"  최대 환승 난이도: {route.max_transfer_difficulty:.2f}")
    logger.info(f"  총 점수 (페널티): {score:.3f}")


def test_single_route(
    raptor: McRaptor,
    origin_name: str,
    destination_name: str,
    disability_type: str = "PHY",
):
    """단일 경로 테스트"""

    logger.info("=" * 60)
    logger.info(f"테스트 케이스: {origin_name} → {destination_name}")
    logger.info("=" * 60)

    try:
        # 1. 출발지/목적지 station_cd 조회
        origin_cd = get_station_cd_by_name(origin_name)
        destination_cd = get_station_cd_by_name(destination_name)

        logger.info(f"출발지: {origin_name} ({origin_cd})")
        logger.info(f"목적지: {destination_name} ({destination_cd})")

        # 2. 경로 탐색 실행
        departure_time = datetime.now()

        logger.info(f"장애 유형: {disability_type}")
        logger.info(f"출발 시각: {departure_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"최대 라운드: 4")

        start_time = time.time()

        routes = raptor.find_routes(
            origin_cd=origin_cd,
            destination_cd_set={destination_cd},
            departure_time=departure_time,
            disability_type=disability_type,
            max_rounds=5, # 5의 경우 라벨 폭증
        )

        end_time = time.time()
        elapsed_time = end_time - start_time

        # 3. 결과 출력
        logger.info("")
        logger.info(f"알고리즘 수행 시간: {elapsed_time:.3f}초")
        logger.info(f"발견된 경로 수: {len(routes)}개")

        if routes:
            # 경로를 점수순으로 정렬
            ranked_routes = raptor.rank_routes(routes, disability_type)

            logger.info(f"정렬 후 고유 경로 수: {len(ranked_routes)}개")
            logger.info("")

            # 상위 3개 경로만 출력
            for idx, (route, score) in enumerate(ranked_routes[:3], 1):
                print_route_details(raptor, route, idx, score)
        else:
            logger.warning("경로를 찾을 수 없습니다.")

        logger.info("")

    except Exception as e:
        logger.error(f"경로 탐색 중 오류 발생: {e}", exc_info=True)


def test_route_finding():
    """경로 찾기 테스트 - 4가지 케이스"""

    # 테스트 케이스 정의
    test_cases = [
        ("광화문", "남성"),
        ("충무로", "동묘앞"),
        ("구반포", "서울"),
        ("청구", "숙대입구"),
    ]

    # DB 연결 풀 초기화
    initialize_pool()

    try:
        # 알고리즘 초기화 (한 번만)
        logger.info("=" * 60)
        logger.info("알고리즘 초기화 중...")
        logger.info("=" * 60)

        raptor = McRaptor()

        logger.info("초기화 완료")
        logger.info("")

        # 각 테스트 케이스 실행
        disability_type = "PHY"  # 휠체어 사용자

        for origin, destination in test_cases:
            test_single_route(raptor, origin, destination, disability_type)

        logger.info("=" * 60)
        logger.info("모든 테스트 완료")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"테스트 실행 중 오류 발생: {e}", exc_info=True)

    finally:
        # DB 연결 풀 종료
        close_pool()
        logger.info("테스트 종료")


if __name__ == "__main__":
    test_route_finding()
