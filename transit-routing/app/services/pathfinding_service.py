# 경로 찾기 서비스

import logging
import time
import json
from datetime import datetime
from typing import Optional, Dict, Any

from app.db.redis_client import RedisSessionManager
from app.db.cache import get_stations_dict, get_station_cd_by_name
from app.algorithms.mc_raptor import McRaptor
from app.core.exceptions import RouteNotFoundException, StationNotFoundException
from app.core.config import settings

logger = logging.getLogger(__name__)


class PathfindingService:

    def __init__(self):
        # cache에서 직접 가져오기
        self.stations = get_stations_dict()
        self.raptor = McRaptor()
        self.redis_client = RedisSessionManager()  # 경로 캐싱을 위해 redis client 추가
        logger.info("PathfindingService 초기화 완료 + 캐싱 활성화")

    def calculate_route(
        self, origin_name: str, destination_name: str, disability_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        경로 계산 및 상위 3개 경로 반환

        Args:
            origin_name: 출발지 역 이름
            destination_name: 목적지 역 이름
            disability_type: 장애 유형 (PHY/VIS/AUD/ELD)

        Returns:
            경로 데이터 딕셔너리 (상위 3개 경로 포함)

        Raises:
            StationNotFoundException: 역을 찾을 수 없을 때
            RouteNotFoundException: 경로를 찾을 수 없을 때
        """
        start_time = time.time()

        try:
            # 캐시 함수 사용
            # 역 코드 조회
            origin_cd = get_station_cd_by_name(origin_name)
            destination_cd = get_station_cd_by_name(destination_name)

            if not origin_cd:
                raise StationNotFoundException(
                    f"출발지 역을 찾을 수 없습니다: {origin_name}"
                )

            if not destination_cd:
                raise StationNotFoundException(
                    f"목적지 역을 찾을 수 없습니다: {destination_name}"
                )

            logger.info(
                f"경로 계산 요청: {origin_name}({origin_cd}) → "
                f"{destination_name}({destination_cd}), 유형={disability_type}"
            )

            # 캐시 키 생성 => 출발지, 도착역, 교통약자 유형
            # 경로 탐색 시각이 해당 키에서 제외되는 이유
            # => 현재 혼잡도는 30분을 기준으로 측정됨. 경로 탐색 결과 캐시는 30분의 TTL을 가지기 때문에
            # => 굳이 시각을 포함하지 않아도 됨
            cache_key = f"route:{origin_cd}:{destination_cd}:{disability_type}"

            # 캐시 확인
            cached_result = self.redis_client.get_cached_route(cache_key)

            # 캐시 HIT
            if cached_result:
                elapsed_time = time.time() - start_time
                logger.info(
                    f"캐시에서 경로 반환: {origin_name} → {destination_name}, "
                    f"응답시간={elapsed_time*1000:.1f}ms"
                )
                self._log_cache_metrics(
                    cache_hit=True,
                    response_time_ms=elapsed_time * 1000,
                    origin=origin_name,
                    destination=destination_name,
                    disability_type=disability_type,
                )
                return cached_result

            # 캐시 미스 -> 경로 계산 수행
            logger.debug(f"캐시 미스, 경로 계산 시작: {cache_key}")
            calculation_start = time.time()

            departure_time = datetime.now()

            logger.debug(
                f"경로 탐색: {origin_cd} → {destination_cd}, type={disability_type}"
            )

            # mc_raptor => find_routes
            routes = self.raptor.find_routes(
                origin_cd=origin_cd,
                destination_cd_set={destination_cd},
                departure_time=departure_time,
                disability_type=disability_type,
                max_rounds=5,
            )

            if not routes:
                raise RouteNotFoundException(
                    f"{origin_name}에서 {destination_name}까지 경로를 찾을 수 없습니다"
                )

            ranked_routes = self.raptor.rank_routes(routes, disability_type)

            calculation_time = time.time() - calculation_start
            logger.debug(
                f"경로 계산 완료: {len(ranked_routes)}개 발견, "
                f"계산시간={calculation_time:.2f}s"
            )

            # 상위 3개 경로 선택
            top_3_routes = ranked_routes[:3]

            # 각 경로 정보 생성
            routes_info = []
            for rank, (route, score) in enumerate(top_3_routes, start=1):
                route_sequence = route.reconstruct_route()
                route_lines = route.reconstruct_lines()
                transfer_info = route.reconstruct_transfer_info()
                transfer_stations = [t[0] for t in transfer_info]

                route_info = {  # round 처리한 값으로 제공하기
                    "rank": rank,
                    "route_sequence": route_sequence,
                    "route_lines": route_lines,
                    "total_time": round(route.arrival_time, 1),
                    "transfers": route.transfers,
                    "transfer_stations": transfer_stations,
                    "transfer_info": transfer_info,
                    "score": round(score, 4),
                    "avg_convenience": round(route.avg_convenience, 2),
                    "avg_congestion": round(route.avg_congestion, 2),
                    "max_transfer_difficulty": round(route.max_transfer_difficulty, 2),
                }
                routes_info.append(route_info)

            result = {
                "origin": origin_name,
                "origin_cd": origin_cd,
                "destination": destination_name,
                "destination_cd": destination_cd,
                "routes": routes_info,
                "total_routes_found": len(routes),  # 발견된 총 경로 수
                "routes_returned": len(routes_info),  # 반환된 경로 수
            }

            # redis에 캐싱
            cache_success = self.redis_client.cache_route(
                cache_key, result, ttl=settings.ROUTE_CACHE_TTL_SECONDS
            )

            if cache_success:
                logger.debug(f"경로 캐싱 완료: {cache_key}")
            else:
                logger.warning(f"경로 캐싱 실패 (계속 진행): {cache_key}")

            # metric logging
            elapsed_time = time.time() - start_time
            logger.info(
                f"경로 계산 및 반환: {origin_name} → {destination_name}, "
                f"총 응답시간={elapsed_time:.2f}s, 계산시간={calculation_time:.2f}s"
            )

            self._log_cache_metrics(
                cache_hit=False,
                response_time_ms=elapsed_time * 1000,
                calculation_time_ms=calculation_time * 1000,
                origin=origin_name,
                destination=destination_name,
                disability_type=disability_type,
                routes_found=len(ranked_routes),
            )

            logger.debug(
                f"경로 계산 완료: {len(routes)}개 발견, 상위 {len(routes_info)}개 반환"
            )
            return result

        except (StationNotFoundException, RouteNotFoundException) as e:
            logger.error(f"경로 계산 실패: {e.message}")
            raise
        except Exception as e:
            logger.error(f"경로 계산 오류: {e}", exc_info=True)
            raise

    def _log_cache_metrics(
        self,
        cache_hit: bool,
        response_time_ms: float,
        origin: str,
        destination: str,
        disability_type: str,
        calculation_time_ms: Optional[float] = None,
        routes_found: Optional[int] = None,
    ) -> None:
        """
        캐시 메트릭 로깅 => ELK Stack, CloudWatch 등에서 분석하기
        """
        if not settings.ENABLE_CACHE_METRICS:
            return

        metrics = {
            "event": "route_calculation",
            "cache_hit": cache_hit,
            "response_time_ms": round(response_time_ms, 2),
            "origin": origin,
            "destination": destination,
            "disability_type": disability_type,
        }

        if calculation_time_ms is not None:
            metrics["calculation_time_ms"] = round(calculation_time_ms, 2)

        if routes_found is not None:
            metrics["routes_found"] = routes_found

        logger.info(f"METRICS: {json.dumps(metrics, ensure_ascii=False)}")
