# C++ 엔진 기반 경로 찾기 서비스

import logging
import time
import json
from datetime import datetime
from typing import Optional, Dict, Any

from app.db.redis_client import RedisSessionManager
from app.db.cache import (
    get_stations_dict,
    get_station_cd_by_name,
    get_lines_dict,
    get_facility_info_by_name,
    get_facility_info_by_cd,
    get_congestion_data,
)
from app.db.database import (
    get_all_stations,
    get_all_facility_data,
    get_all_congestion_data,
    get_all_sections,
)
from app.core.exceptions import RouteNotFoundException, StationNotFoundException
from app.core.config import settings

logger = logging.getLogger(__name__)

# 유효한 장애 유형 정의
VALID_DISABILITY_TYPES = {"PHY", "VIS", "AUD", "ELD"}


class PathfindingServiceCPP:
    """
    C++ pathfinding_cpp 모듈을 사용하는 고성능 경로 탐색 서비스

    Python 버전의 PathfindingService와 동일한 인터페이스를 제공하지만,
    핵심 알고리즘은 C++로 구현된 McRaptorEngine을 사용합니다.
    """

    def __init__(self):
        """
        PathfindingServiceCPP 초기화

        1. C++ pathfinding_cpp 모듈 import
        2. DataContainer에 데이터 로드
        3. McRaptorEngine 초기화
        4. Redis 캐시 클라이언트 초기화
        """
        try:
            # C++ 모듈 import
            import pathfinding_cpp

            self.cpp_module = pathfinding_cpp
            logger.info("pathfinding_cpp 모듈 로드 성공")

        except ImportError as e:
            logger.error(
                f"pathfinding_cpp 모듈을 찾을 수 없습니다: {e}\n"
                "C++ 엔진을 빌드해야 합니다: cd cpp_src && mkdir build && cd build && cmake .. && make"
            )
            raise RuntimeError("C++ pathfinding_cpp 모듈이 설치되지 않았습니다") from e

        # Python 캐시에서 기본 데이터 가져오기
        self.stations = get_stations_dict()
        self.redis_client = RedisSessionManager()

        # C++ 데이터 컨테이너 초기화 및 데이터 로드
        logger.info("C++ DataContainer 초기화 시작...")
        self.data_container = self._initialize_cpp_data()

        # C++ 엔진 초기화
        # logger.info("C++ McRaptorEngine 초기화 시작...")
        # self.cpp_engine = pathfinding_cpp.McRaptorEngine(self.data_container)
        # => labels_pools_를 공유하게 되므로 이와 같은 싱글톤 패턴 사용 시, 반드시 크래시 발생
        # => request마다 엔진을 생성하는 팩토리 패턴으로 변경 적용

        logger.info("PathfindingServiceCPP 초기화 완료 (C++ 엔진 + 캐싱 활성화)")

    def _initialize_cpp_data(self):
        """
        C++ DataContainer에 필요한 모든 데이터 로드

        Returns:
            pathfinding_cpp.DataContainer: 초기화된 데이터 컨테이너
        """
        start_time = time.time()

        # DataContainer 생성
        data_container = self.cpp_module.DataContainer()

        # 1. 역 정보 준비
        stations_dict = {}
        all_stations = get_all_stations()

        for station in all_stations:
            station_cd = station["station_cd"]
            stations_dict[station_cd] = {
                "name": station["name"],
                "line": station["line"],
                "latitude": station["lat"],
                "longitude": station["lng"],
                "station_name": station["name"],
                "station_cd": station_cd,
                "line": station["line"],
            }

        logger.debug(f"역 정보 로드 완료: {len(stations_dict)}개 역")

        # 2. 노선별 역 순서 (line_stations)
        line_stations_dict = {}
        lines_dict = get_lines_dict()
        # sections = get_all_sections()

        # line_stations 구조 생성
        # {(station_cd, line): {"up": [station_cds...], "down": [station_cds...]}}
        for line, station_cds in lines_dict.items():
            for station_cd in station_cds:
                key = (station_cd, line)

                # sections에서 해당 역의 상하행 정보 찾기
                # 실제 구현은 sections 데이터 구조에 따라 달라질 수 있음
                # 여기서는 간단히 전체 노선 순서를 사용
                line_stations_dict[key] = {
                    "up": station_cds,
                    "down": list(reversed(station_cds)),
                }

        logger.debug(
            f"노선 토폴로지 로드 완료: {len(line_stations_dict)}개 (역, 노선) 쌍"
        )

        # 3. 역 순서 맵 (station_order)
        station_order_dict = {}

        for line, station_cds in lines_dict.items():
            for idx, station_cd in enumerate(station_cds):
                key = (station_cd, line)
                station_order_dict[key] = idx

        logger.debug(f"역 순서 맵 로드 완료: {len(station_order_dict)}개 항목")

        # 4. 환승 정보 (transfers)
        # C++는 (station_cd, from_line, to_line) 튜플 키를 기대합니다
        transfers_dict = {}

        # 역 이름별로 그룹화: {역이름: [(station_cd, line), ...]}
        station_name_map = {}
        for station_cd, station_info in stations_dict.items():
            station_name = station_info["name"]
            if station_name not in station_name_map:
                station_name_map[station_name] = []
            station_name_map[station_name].append((station_cd, station_info["line"]))

        # 환승역(2개 이상 노선이 있는 역)에 대해 환승 조합 생성
        for station_name, station_line_pairs in station_name_map.items():
            if len(station_line_pairs) < 2:
                continue  # 환승역이 아님

            # 모든 노선 조합에 대해 환승 정보 생성
            for from_cd, from_line in station_line_pairs:
                for to_cd, to_line in station_line_pairs:
                    if from_line != to_line:  # 다른 노선으로 환승
                        # from_line의 station_cd를 키로 사용
                        key = (from_cd, from_line, to_line)
                        transfers_dict[key] = {
                            "distance": 133.09,  # 기본 환승 거리 (미터)
                        }

        logger.debug(f"환승 정보 로드 완료: {len(transfers_dict)}개 환승 조합")

        # 5. 혼잡도 정보 (congestion)
        congestion_dict = {}
        all_congestion = get_all_congestion_data()

        for cong in all_congestion:
            key = (
                cong["station_cd"],
                cong["line"],
                cong.get("direction", "up"),
                cong.get("day_type", "weekday"),
            )

            # 시간대별 혼잡도 (t_0, t_30, t_60, ... t_1410)
            # DB 값은 0-100 퍼센트, C++ 엔진은 0.0-1.0 정규화 값 기대
            time_slots = {}
            for i in range(0, 1440, 30):  # 0분부터 1410분까지 30분 간격
                slot_key = f"t_{i}"
                raw_value = cong.get(slot_key, 57)  # 기본값 57%
                # 정규화: 0-100 -> 0.0-1.0
                time_slots[slot_key] = (
                    float(raw_value) / 100.0 if raw_value is not None else 0.57
                )

            congestion_dict[key] = time_slots

        logger.debug(f"혼잡도 정보 로드 완료: {len(congestion_dict)}개 항목")

        # C++ DataContainer에 데이터 로드
        logger.info("C++ DataContainer에 데이터 전송 중...")
        data_container.load_from_python(
            stations_dict,
            line_stations_dict,
            station_order_dict,
            transfers_dict,
            congestion_dict,
        )

        # 6. 편의시설 데이터 로드 및 편의성 점수 계산
        logger.info("편의시설 데이터 로드 및 점수 계산 중...")
        facility_data = get_all_facility_data()

        # C++ 엔진이 기대하는 형식으로 변환
        facility_rows = []
        for facility in facility_data:
            facility_row = {
                "station_cd_list": facility.get("station_cd_list", []),
                "charger_count": float(facility.get("charger_count", 0)),
                "elevator_count": float(facility.get("elevator_count", 0)),
                "escalator_count": float(facility.get("escalator_count", 0)),
                "lift_count": float(facility.get("lift_count", 0)),
                "movingwalk_count": float(facility.get("movingwalk_count", 0)),
                "safe_platform_count": float(facility.get("safe_platform_count", 0)),
                "sign_phone_count": float(facility.get("sign_phone_count", 0)),
                "toilet_count": float(facility.get("toilet_count", 0)),
                "helper_count": float(facility.get("helper_count", 0)),
            }
            facility_rows.append(facility_row)

        logger.debug(f"편의시설 데이터 {len(facility_rows)}개 행 준비 완료")

        # C++ DataContainer에 편의시설 점수 업데이트
        # C++에서 장애 유형별 가중치를 적용하여 자동으로 점수 계산
        data_container.update_facility_scores(facility_rows)
        logger.info("편의시설 기반 편의성 점수 계산 완료")

        elapsed_time = time.time() - start_time
        logger.info(f"C++ 데이터 로드 완료: {elapsed_time:.2f}초")

        return data_container

    def calculate_route(
        self, origin_name: str, destination_name: str, disability_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        C++ 엔진을 사용한 경로 계산 및 상위 3개 경로 반환 + factory pattern

        Args:
            origin_name: 출발지 역 이름
            destination_name: 목적지 역 이름
            disability_type: 장애 유형 (PHY/VIS/AUD/ELD)

        Returns:
            경로 데이터 딕셔너리 (상위 3개 경로 포함)

        Raises:
            ValueError: 유효하지 않은 장애 유형
            StationNotFoundException: 역을 찾을 수 없을 때
            RouteNotFoundException: 경로를 찾을 수 없을 때
        """
        start_time = time.time()

        try:
            # 장애 유형 유효성 검증
            if disability_type not in VALID_DISABILITY_TYPES:
                raise ValueError(
                    f"유효하지 않은 장애 유형: {disability_type}. "
                    f"유효한 값: {', '.join(VALID_DISABILITY_TYPES)}"
                )

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
                f"[C++] 경로 계산 요청: {origin_name}({origin_cd}) → "
                f"{destination_name}({destination_cd}), 유형={disability_type}"
            )

            # 캐시 키 생성
            cache_key = f"route:cpp:{origin_cd}:{destination_cd}:{disability_type}"

            # 캐시 확인
            cached_result = self.redis_client.get_cached_route(cache_key)

            if cached_result:
                elapsed_time = time.time() - start_time
                logger.info(
                    f"[C++] 캐시에서 경로 반환: {origin_name} → {destination_name}, "
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

            # 캐시 미스 -> C++ 엔진으로 경로 계산
            logger.debug(f"[C++] 캐시 미스, 경로 계산 시작: {cache_key}")
            calculation_start = time.time()

            departure_time = datetime.now().timestamp()  # Unix timestamp

            # 요청마다 새로운 엔진 인스턴스 생성 Thread-Safe 보장
            # DataContainer는 공유되지만 Read-Only이므로 안전
            engine = self.cpp_module.McRaptorEngine(self.data_container)

            # C++ 엔진 호출
            logger.debug(
                f"[C++] find_routes 호출: {origin_cd} → {destination_cd}, "
                f"type={disability_type}"
            )

            # local variable 사용
            routes = engine.find_routes(
                origin_cd,
                {destination_cd},
                departure_time,
                disability_type,
                5,
            )

            if not routes:
                raise RouteNotFoundException(
                    f"{origin_name}에서 {destination_name}까지 경로를 찾을 수 없습니다"
                )

            # C++ 엔진으로 경로 정렬
            ranked_routes = engine.rank_routes(routes, disability_type)

            calculation_time = time.time() - calculation_start
            logger.debug(
                f"[C++] 경로 계산 완료: {len(ranked_routes)}개 발견, "
                f"계산시간={calculation_time:.2f}s"
            )

            # 상위 3개 경로 선택
            top_3_routes = ranked_routes[:3]

            # 각 경로 정보 생성
            routes_info = []
            for rank, (label, score) in enumerate(top_3_routes, start=1):
                # C++ Label 객체에서 정보 추출
                route_sequence = engine.reconstruct_route(
                    label, self.data_container
                )
                route_lines = engine.reconstruct_lines(label)

                # 환승 정보 추출 (Label 객체를 역추적하여 구성)
                transfer_info = self._extract_transfer_info(label, engine)
                transfer_stations = [t[0] for t in transfer_info]

                route_info = {
                    "rank": rank,
                    "route_sequence": route_sequence,
                    "route_lines": route_lines,
                    "total_time": round(label.arrival_time, 1),
                    "transfers": label.transfers,
                    "transfer_stations": transfer_stations,
                    "transfer_info": transfer_info,
                    "score": round(score, 4),
                    "avg_convenience": round(label.avg_convenience, 2),
                    "avg_congestion": round(label.avg_congestion, 2),
                    "max_transfer_difficulty": round(label.max_transfer_difficulty, 2),
                }
                routes_info.append(route_info)

            result = {
                "origin": origin_name,
                "origin_cd": origin_cd,
                "destination": destination_name,
                "destination_cd": destination_cd,
                "routes": routes_info,
                "total_routes_found": len(routes),
                "routes_returned": len(routes_info),
            }

            # Redis 캐싱
            cache_success = self.redis_client.cache_route(
                cache_key, result, ttl=settings.ROUTE_CACHE_TTL_SECONDS
            )

            if cache_success:
                logger.debug(f"[C++] 경로 캐싱 완료: {cache_key}")
            else:
                logger.warning(f"[C++] 경로 캐싱 실패 (계속 진행): {cache_key}")

            # 메트릭 로깅
            elapsed_time = time.time() - start_time
            logger.info(
                f"[C++] 경로 계산 및 반환: {origin_name} → {destination_name}, "
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

            return result

        except (StationNotFoundException, RouteNotFoundException) as e:
            logger.error(f"[C++] 경로 계산 실패: {e.message}")
            raise
        except Exception as e:
            logger.error(f"[C++] 경로 계산 오류: {e}", exc_info=True)
            raise

    def _extract_transfer_info(self, label, engine) -> list:
        """
        C++ Label 객체에서 환승 정보 추출

        Note: C++ bindings.cpp에서 transfer_info를 직접 노출하지 않는 경우,
        reconstruct_route와 reconstruct_lines를 비교하여 환승 지점을 찾습니다.

        Args:
            label: C++ Label 객체
            engine: McRaptorEngine 인스턴스 (팩토리 패턴으로 요청마다 생성)

        Returns:
            List[Tuple[str, str, str]]: [(station_cd, from_line, to_line), ...]
        """
        try:
            # 경로 및 노선 재구성
            route_sequence = engine.reconstruct_route(
                label, self.data_container
            )
            route_lines = engine.reconstruct_lines(label)

            # 길이 검증: route_sequence와 route_lines의 길이가 일치해야 함
            if len(route_sequence) != len(route_lines):
                logger.warning(
                    f"경로 시퀀스({len(route_sequence)})와 노선({len(route_lines)}) 길이 불일치"
                )
                return []

            # 환승 지점 찾기 (노선이 변경되는 지점)
            transfer_info = []

            for i in range(len(route_lines) - 1):
                if route_lines[i] != route_lines[i + 1]:
                    # 환승 발생
                    # 인덱스 범위 검증
                    if i + 1 < len(route_sequence):
                        transfer_station = route_sequence[i + 1]  # 환승역
                        from_line = route_lines[i]
                        to_line = route_lines[i + 1]

                        transfer_info.append((transfer_station, from_line, to_line))
                    else:
                        logger.warning(f"환승역 인덱스 {i + 1}이 범위를 벗어남")

            return transfer_info

        except Exception as e:
            logger.warning(f"환승 정보 추출 실패: {e}, 빈 리스트 반환")
            return []

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
        캐시 메트릭 로깅 (ELK Stack, CloudWatch 등 분석용)
        """
        if not settings.ENABLE_CACHE_METRICS:
            return

        metrics = {
            "event": "route_calculation_cpp",
            "engine": "cpp",
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
