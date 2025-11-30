import redis
import json
from typing import Optional, Dict, Any
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
        """user_id를 받아 세션 가져오기 <- 에러 처리 추가"""
        try:
            session_key = f"session:{user_id}"
            data = self.redis_client.get(session_key)
            if data:  # 역직렬화 로직
                session = json.loads(data)
                session["route_sequence"] = json.loads(
                    session.get("route_sequence", "[]")
                )
                session["route_lines"] = json.loads(session.get("route_lines", "[]"))
                session["transfer_stations"] = json.loads(
                    session.get("transfer_stations", "[]")
                )
                session["transfer_info"] = json.loads(
                    session.get("transfer_info", "[]")
                )
                session["all_routes"] = json.loads(
                    session.get("all_routes", "[]")
                )  # 추가
                return session
            return None
        except redis.RedisError as e:
            logger.error(f"세션 조회 실패: user_id={user_id}, 오류:{e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"세션 데이터 파싱 실패: user_id={user_id}, 오류: {e}")
            return None

    def update_location(self, user_id: str, current_station: str):
        session = self.get_session(user_id)
        if session:
            session["current_station"] = current_station
            session["last_update"] = datetime.now().isoformat()
            session["route_sequence"] = json.dumps(session["route_sequence"])
            session["route_lines"] = json.dumps(session["route_lines"])
            session["transfer_stations"] = json.dumps(session["transfer_stations"])
            session["transfer_info"] = json.dumps(session["transfer_info"])
            self.redis_client.setex(
                f"session:{user_id}", SESSION_TTL_SECONDS, json.dumps(session)
            )

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
        self, cache_key: str, route_data: Dict[str, Any], ttl: int = 3600
    ) -> bool:
        """
        경로 계산 결과 redis에 캐싱
        """
        try:
            serialized_data = json.dumps(route_data, ensure_ascii=False)
            self.redis_client.setex(cache_key, ttl, serialized_data)
            logger.debug(f"경로 캐싱 성공: {cache_key}, TTL={ttl}")
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
            keys = self.redis_client.keys(pattern)
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


def init_redis():
    return RedisSessionManager()
