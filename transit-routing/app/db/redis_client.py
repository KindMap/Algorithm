import redis
import json
from typing import Optional, Dict, Any, Tuple, List
from datetime import datetime
import logging

from app.core.config import settings, SESSION_TTL_SECONDS

logger = logging.getLogger(__name__)


class RedisSessionManager:
    def __init__(self):
        self.redis_client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=0,
            decode_responses=True,
        )

    def create_session(self, user_id: str, route_data: dict) -> bool:
        """session 생성 <- 에러 처리 추가"""
        try:
            session_key = f"session:{user_id}"

            # routes가 비어있거나 None일 경우 처리
            routes = route_data.get("routes", [])
            primary_route = routes[0] if routes else {}

            # 기본 경로는 1순위 경로 사용
            primary_route = route_data["routes"][0] if route_data.get("routes") else {}

            session_data = {
                "route_id": route_data.get("route_id"),
                "origin": route_data.get("origin"),
                "origin_cd": route_data.get("origin_cd"),
                "destination": route_data.get("destination"),
                "destination_cd": route_data.get("destination_cd"),
                # 1순위 경로 정보를 세션에 저장 (실시간 안내용)
                "route_sequence": json.dumps(primary_route.get("route_sequence", [])),
                "route_lines": json.dumps(primary_route.get("route_lines", [])),
                "transfer_stations": json.dumps(
                    primary_route.get("transfer_stations", [])
                ),
                "transfer_info": json.dumps(primary_route.get("transfer_info", [])),
                "total_time": primary_route.get("total_time", 0),
                "transfers": primary_route.get("transfers", 0),
                # 전체 경로 정보도 저장 (경로 변경 시 사용)
                "all_routes": json.dumps(route_data.get("routes", [])),
                "current_station": route_data.get("origin_cd"),
                "selected_route_rank": 1,  # 현재 선택된 경로 순위
                "last_update": datetime.now().isoformat(),
            }
            self.redis_client.setex(
                session_key, SESSION_TTL_SECONDS, json.dumps(session_data)
            )
            logger.debug(f"세션 생성: user_id = {user_id}")
            return True
        except redis.RedisError as e:
            logger.error(f"세션 생성 실패: user_id={user_id}, 오류: {e}")
            return False
        except Exception as e:
            logger.error(f"세션 생성 중 예상치 못한 오류: {e}", exc_info=True)
            return False

    def delete_session(self, user_id: str) -> bool:
        """
        delete session

        Args:
            user_id: 사용자 ID
        Returns:
            삭제 성공 여부
        """
        try:
            session_key = f"session:{user_id}"
            result = self.redis_client.delete(session_key)
            logger.debug(f"세션 삭제: user_id={user_id}")
            return bool(result)
        except redis.RedisError as e:
            logger.error(f"세션 삭제 실패: user_id={user_id}, 오류: {e}")
            return False

    def switch_route(self, user_id: str, target_rank: int) -> bool:
        """사용자가 1순위가 아닌 다른 순위의 경로를 선택하여 경로 변경"""
        session = self.get_session(user_id)
        if not session:
            return False

        all_routes = session.get("all_routes", [])

        # 순위 검증
        if target_rank < 1 or target_rank > len(all_routes):
            return False

        # 선택한 경로로 변경
        selected_route = all_routes[target_rank - 1]

        session["route_sequence"] = json.dumps(selected_route.get("route_sequence", []))
        session["route_lines"] = json.dumps(selected_route.get("route_lines", []))
        session["transfer_stations"] = json.dumps(
            selected_route.get("transfer_stations", [])
        )
        session["transfer_info"] = json.dumps(selected_route.get("transfer_info", []))
        session["total_time"] = selected_route.get("total_time", 0)
        session["transfers"] = selected_route.get("transfers", 0)
        session["selected_route_rank"] = target_rank
        session["all_routes"] = json.dumps(all_routes)
        session["last_update"] = datetime.now().isoformat()

        return self.redis_client.setex(
            f"session:{user_id}", SESSION_TTL_SECONDS, json.dumps(session)
        )

    def get_session(self, user_id: str) -> Optional[Dict]:
        """session 조회 및 역직렬화"""
        try:
            session_key = f"session:{user_id}"
            data = self.redis_client.get(session_key)

            if not data:
                return None

            session = json.loads(data)

            # JSON 필드 역직렬화 <- 안전을 위해 .get 사용
            json_fields = [
                "route_sequence",
                "route_lines",
                "transfer_stations",
                "transfer_info",
                "all_routes",
            ]

            for field in json_fields:
                if field in session and isinstance(session[field], str):
                    try:
                        session[field] = json.loads(session[field])
                    except json.JSONDecodeError:
                        session[field] = []  # parsing 실패 => 빈 리스트

            return session

        except redis.RedisError as e:
            logger.error(f"세션 조회 실패: user_id={user_id}, 오류:{e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"세션 데이터 파싱 실패: user_id={user_id}, 오류: {e}")
            return None

    def update_location(self, user_id: str, current_station: str):
        """현재 위치 업데이트 (TTL 갱신 포함)"""
        try:
            session = self.get_session(user_id)
            if session:
                session["current_station"] = current_station
                session["last_update"] = datetime.now().isoformat()

                # 다시 직렬화하여 저장
                # get_session에서 list로 변환된 필드들을 다시 json string으로 변환해야 함
                for field in [
                    "route_sequence",
                    "route_lines",
                    "transfer_stations",
                    "transfer_info",
                    "all_routes",
                ]:
                    if field in session:
                        session[field] = json.dumps(session[field])

                self.redis_client.setex(
                    f"session:{user_id}", SESSION_TTL_SECONDS, json.dumps(session)
                )
        except Exception as e:
            logger.error(f"위치 업데이트 실패: {e}")

    # cashing and analystics
    # 경로 캐싱을 위한 메서드 추가
    def get_cached_route(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """
        캐시된 경로 조회 => 캐시 hit/miss 로그로 기록
        """
        try:
            cached_data = self.redis_client.get(cache_key)
            if cached_data:
                logger.debug(f"캐시 HIT:{cache_key}")
                return json.loads(cached_data)
            logger.debug(f"캐시 MISS: {cache_key}")
            return None
        except redis.RedisError as e:
            logger.warning(f"Redis 캐시 조회 실패 (fallback: 재계산): {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"캐시 데이터 파싱 실패: {cache_key}, 오류: {e}")
            return None

    def cache_route(
        self, cache_key: str, route_data: Dict[str, Any], ttl: int = 1209600
    ) -> bool:
        """
        경로 계산 결과 redis에 캐싱
        """
        try:
            serialized_data = json.dumps(route_data, ensure_ascii=False)
            self.redis_client.setex(cache_key, ttl, serialized_data)

            try:
                # 실시간 통계 업데이트
                self._update_analytics(route_data)
            except Exception as e:
                logger.error(f"통계 집계 중 오류 발생 (캐싱은 성공함): {e}")

            logger.debug(f"경로 캐싱 및 통계 업데이트 성공: {cache_key}, TTL={ttl}")
            return True
        except redis.RedisError as e:
            logger.error(f"redis 캐싱 실패: {cache_key}, 오류: {e}")
            return False
        except (TypeError, ValueError) as e:
            logger.error(f"경로 데이터 직렬화 실패: {e}")
            return False

    def invalidate_route_cache(self, pattern: str = "route:*") -> int:
        """
        경로 캐시 무효화 <- 데이터 업데이트 시 사용, default : 모든 경로 캐시 삭제
        """
        try:
            keys = list(self.redis_client.scan_iter(match=pattern))
            if keys:
                deleted_count = self.redis_client.delete(*keys)
                logger.info(
                    f"캐시 무효화 완료: {deleted_count}개 삭제 -> 패턴: {pattern}"
                )
                return deleted_count
            logger.info(f"무효화할 캐시 없음 -> 패턴: {pattern}")
            return 0
        except redis.RedisError as e:
            logger.error(f"캐시 무효화 실패: {e}")
            return 0

    def _update_analytics(self, route_data: Dict[str, Any]):
        """
        ZSET을 이용한 실시간 트래픽 분석

        - 출발지/목적지/환승역 랭킹
        - (출발지, 목적지) pair 랭킹
        - 시간대별 트래픽
        """
        origin = route_data.get("origin")
        destination = route_data.get("destination")
        routes = route_data.get("routes", [])

        if not origin or not destination:
            return

        # pipeline => 여러 명령어를 한 번의 네트워크 요청으로 처리
        # => 성능 최적화
        pipe = self.redis_client.pipeline()

        # 출발지 & 목적지 랭킹
        pipe.zincrby("stats:origin", 1, origin)
        pipe.zincrby("stats:destination", 1, destination)

        # OD Pair (인기 이동 경로) 분석
        # 어떤 구간 수요가 많은지 파악
        od_pair = f"{origin}-{destination}"
        pipe.zincrby("stats:od_pair", 1, od_pair)

        # 시간대별 검색 트래픽 분석
        # 피크타임 파악 용도
        current_hour = datetime.now().strftime("%H")
        pipe.zincrby("stats:hourly_traffic", 1, current_hour)

        # 환승역 랭킹
        # 모든 추천 경로의 환승역을 집계
        processed_stations = set()  # 한 검색 결과 내에서 중복 카운트 방지
        for route in routes:
            transfer_stations = route.get("transfer_stations", [])
            for station in transfer_stations:
                if station not in processed_stations:
                    pipe.zincrby("stats:transfer", 1, station)
                    processed_stations.add(station)

        # 파이프라인 실행
        pipe.execute()
        logger.debug(f"통계 업데이트 완료: {origin} -> {destination}")

    # 통계 데이터 조회용 메서드 추가
    def get_top_origins(self, limit: int = 10) -> List[Tuple[str, float]]:
        """
        가장 많이 검색된 출발역 TOP 10 조회 => [('역이름', 점수), ...]
        """
        try:
            # ZREVRANGE: score(빈도)가 높은 순으로 내림차순 정렬하여 조회
            return self.redis_client.zrevrange(
                "stats:origin", 0, limit - 1, withscores=True
            )
        except Exception as e:
            logger.error(f"출발역 통계 조회 실패: {e}")
            return []

    def get_top_destinations(self, limit: int = 10) -> List[Tuple[str, float]]:
        """
        가장 많이 검색된 목적지 TOP 10 조회 => [('역이름', 점수), ...]
        """
        try:
            # ZREVRANGE: score(빈도)가 높은 순으로 내림차순 정렬하여 조회
            return self.redis_client.zrevrange(
                "stats:destination", 0, limit - 1, withscores=True
            )
        except Exception as e:
            logger.error(f"목적지 통계 조회 실패: {e}")
            return []

    def get_top_od_pairs(self, limit: int = 10) -> List[Tuple[str, float]]:
        """
        가장 인기 있는 경로(출발-도착 쌍) TOP N 조회
        Returns: [('사당-강남', 50.0), ('신도림-홍대입구', 45.0), ...]
        """
        try:
            return self.redis_client.zrevrange(
                "stats:od_pair", 0, limit - 1, withscores=True
            )
        except Exception as e:
            logger.error(f"OD Pair 통계 조회 실패: {e}")
            return []

    def get_hourly_traffic(self) -> Dict[str, int]:
        """
        시간대별 검색 트래픽 조회 (00시 ~ 23시)
        Returns: {'09': 150, '18': 300, ...}
        """
        try:
            # 시간대별 데이터는 Top N이 아니라 전체 시간대 데이터가 필요하므로 범위 전체(-1) 조회
            # ZRANGE는 점수 오름차순이지만, 여기서는 단순히 모든 데이터를 가져와 Dict로 변환하는 것이 목적
            data = self.redis_client.zrange(
                "stats:hourly_traffic", 0, -1, withscores=True
            )

            # List[Tuple] -> Dict[str, int] 변환
            # Redis 점수는 float로 반환되므로 int로 변환하여 깔끔하게 제공
            return {hour: int(score) for hour, score in data}
        except Exception as e:
            logger.error(f"시간대별 트래픽 조회 실패: {e}")
            return {}

    def get_top_transfer_stations(self, limit: int = 10) -> List[Tuple[str, float]]:
        """
        가장 환승이 많이 발생하는 역 TOP N 조회
        Returns: [('0205', 500.0), ('0422', 300.0), ...]
        => frontend에서 역코드 -> 역 이름 변환 로직 추가하기
        """
        try:
            return self.redis_client.zrevrange(
                "stats:transfer", 0, limit - 1, withscores=True
            )
        except Exception as e:
            logger.error(f"환승역 통계 조회 실패: {e}")
            return []


def init_redis():
    return RedisSessionManager()
