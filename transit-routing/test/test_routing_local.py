import os
from dotenv import load_dotenv

# 환경변수 로드 => database 모듈 생성 이전에 호출해야 함
load_dotenv()

from database import (
    initialize_pool,
    close_pool,
    get_all_stations,
    get_all_sections,
    get_all_transfer_station_conv_scores,
    get_distance_calculator,
)
from mc_raptor import McRAPTOR
from anp_weights import ANPWeightCalculator
import logging


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_routing_local():
    """로컬에서 경로 찾기 테스트"""

    # 1. DB 연결
    logger.info("DB 연결 초기화...")
    initialize_pool()

    # 2. 데이터 로드
    logger.info("데이터 로딩...")
    stations = get_all_stations()
    sections = get_all_sections()
    convenience_scores = get_all_transfer_station_conv_scores()
    distance_calc = get_distance_calculator()

    logger.info(f"Loaded {len(stations)} stations")
    logger.info(f"Loaded {len(sections)} sections")

    # 3. McRAPTOR 초기화
    logger.info("McRAPTOR 초기화...")
    anp_calculator = ANPWeightCalculator()
    mc_raptor = McRAPTOR(
        stations=stations,
        sections=sections,
        convenience_scores=convenience_scores,
        distance_calc=distance_calc,
        anp_calculator=anp_calculator,
    )

    # 4. 그래프 확인
    logger.info(f"Graph keys count: {len(mc_raptor.graph)}")
    logger.info(f"First 5 graph keys: {list(mc_raptor.graph.keys())[:5]}")

    # 5. 테스트할 역 확인
    origin = "충무로"
    destination = "동묘앞"

    logger.info(f"\n=== 경로 탐색 테스트 ===")
    logger.info(f"출발: {origin}, 도착: {destination}")
    # logger.info(f"'{origin}' in graph: {origin in mc_raptor.graph}")
    # logger.info(f"'{destination}' in graph: {destination in mc_raptor.graph}")

    # if origin in mc_raptor.graph:
    #     logger.info(f"'{origin}' neighbors: {mc_raptor.graph[origin][:3]}")
    
    # logger.info(f"'군자' in graph: {'군자' in mc_raptor.graph}")
    # if '군자' in mc_raptor.graph:
    #     logger.info(f"'군자' neighbors: {mc_raptor.graph['군자']}")

    # 6. 경로 찾기
    try:
        routes = mc_raptor.find_routes(
            origin=origin,
            destination=destination,
            departure_time=540.0,
            disability_type="PHY",
            max_rounds=4,
        )

        logger.info(f"\n찾은 경로 수: {len(routes)}")

        if routes:
            ranked = mc_raptor.rank_routes(routes, "PHY")
            for i, (route, score) in enumerate(ranked[:3], 1):
                logger.info(f"\n=== Route {i} ===")
                logger.info(f"Score: {score:.4f}")
                logger.info(f"Transfers: {route.transfers}")
                logger.info(f"Route: {' -> '.join(route.route)}")
        else:
            logger.warning("경로를 찾지 못했습니다.")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)

    # 7. 정리
    close_pool()
    logger.info("\n테스트 완료")


if __name__ == "__main__":
    test_routing_local()
