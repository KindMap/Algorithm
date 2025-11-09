import os
import sys
from datetime import datetime
from dotenv import load_dotenv
import logging

# 프로젝트 루트 경로 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

load_dotenv()

from database import (
    initialize_pool,
    close_pool,
    get_all_stations,
    get_all_sections,
    get_all_transfer_station_conv_scores,
)
from mc_raptor import McRaptor
from anp_weights import ANPWeightCalculator

# 로깅 설정
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def test_routing_direct():
    """서버 없이 직접 경로 탐색 테스트"""

    logger.info("=" * 80)
    logger.info("경로 탐색 직접 테스트")
    logger.info("=" * 80)

    try:
        # 1. DB 연결 및 데이터 로드
        logger.info("\n[초기화] DB 연결 및 데이터 로딩...")
        initialize_pool()

        stations = get_all_stations()
        sections = get_all_sections()
        convenience_scores = get_all_transfer_station_conv_scores()

        logger.info(
            f"역: {len(stations)}개, 구간: {len(sections)}개, 편의점수: {len(convenience_scores)}개"
        )

        # 2. ANP 계산기 및 McRaptor 초기화
        anp_calculator = ANPWeightCalculator()
        mc_raptor = McRaptor(
            stations=stations,
            sections=sections,
            convenience_scores=convenience_scores,
            anp_calculator=anp_calculator,
        )
        logger.info(f"초기화 완료 (노드: {len(mc_raptor.graph)}개)")

        # 3. 테스트 케이스
        test_cases = [
            ("광화문", "남성", "PHY"),
            ("충무로", "동묘앞", "VIS"),
            ("구반포", "서울", "AUD"),
            ("청구", "숙대입구", "ELD"),
        ]

        logger.info("\n[경로 탐색 시작]")
        logger.info("=" * 80)

        success_count = 0

        # 4. 경로 탐색 실행
        for idx, (origin, destination, disability_type) in enumerate(test_cases, 1):
            logger.info(
                f"\n[{idx}/{len(test_cases)}] {origin} → {destination} ({disability_type})"
            )

            try:
                departure_time = datetime.now().replace(
                    hour=9, minute=0, second=0, microsecond=0
                )

                routes = mc_raptor.find_routes(
                    origin=origin,
                    destination=destination,
                    departure_time=departure_time,
                    disability_type=disability_type,
                    max_rounds=4,
                )

                if routes:
                    ranked_routes = mc_raptor.rank_routes(routes, disability_type)
                    logger.info(f"✓ {len(routes)}개 경로 발견")

                    # 상위 3개 경로 출력
                    for rank, (route, score) in enumerate(ranked_routes[:3], 1):
                        # station_cd를 station_name으로 변환
                        route_names = [
                            mc_raptor.get_station_info_from_cd(cd).get("name", cd)
                            for cd in route.route
                        ]

                        # 환승역 이름 추출
                        transfer_names = []
                        for station_cd, from_line, to_line in route.transfer_context:
                            station_name = mc_raptor.get_station_info_from_cd(
                                station_cd
                            ).get("name", "Unknown")
                            transfer_names.append(
                                f"{station_name}({from_line}→{to_line})"
                            )

                        logger.info(
                        f"  [{rank}위] {route.arrival_time:.1f}분 | "
                        f"환승{route.transfers}회 | "
                        # [!!! 수정 !!!] route.convenience_score -> route.avg_convenience
                        f"편의{route.avg_convenience:.1f} | " 
                        # [!!! 수정 !!!] route.congestion_score -> route.avg_congestion
                        f"혼잡{route.avg_congestion:.2f}"
                        )
                        logger.info(f"       {' → '.join(route_names)}")
                        if transfer_names:
                            logger.info(f"       환승: {', '.join(transfer_names)}")

                    success_count += 1
                else:
                    logger.warning("✗ 경로 없음")

            except Exception as e:
                logger.error(f"✗ 오류: {e}")

        # 5. 결과 요약
        logger.info("\n" + "=" * 80)
        logger.info(f"[완료] 성공: {success_count}/{len(test_cases)}")
        logger.info("=" * 80)

    except Exception as e:
        logger.error(f"초기화 오류: {e}")
        logger.exception("상세:")

    finally:
        close_pool()
        logger.info("정리 완료")


if __name__ == "__main__":
    test_routing_direct()
