import logging
from typing import Optional, Dict, Any

from app.db.redis_client import RedisSessionManager
from app.algorithms.distance_calculator import DistanceCalculator
from app.db.cache import get_stations_dict, get_station_name_by_code
from app.core.exceptions import SessionNotFoundException, InvalidLocationException

logger = logging.getLogger(__name__)


class GuidanceService:
    """실시간 경로 안내 서비스 클래스"""

    def __init__(self, redis_client: RedisSessionManager):
        self.redis_client = redis_client
        self.distance_calc = DistanceCalculator()
        # 캐시에서 역 정보 로드 (DB 쿼리 없음)
        self.stations = get_stations_dict()
        logger.info("GuidanceService 초기화 완료")

    def get_navigation_guidance(
        self, user_id: str, lat: float, lon: float
    ) -> Dict[str, Any]:
        """
        실시간 경로 안내 제공

        핵심 기능:
        - 현재 위치 파악
        - 경로 상 위치 확인
        - 다음 역까지 거리 계산
        - 환승 안내
        - 경로 이탈 감지
        - 도착 감지

        Args:
            user_id: 사용자 ID
            lat: 현재 위도
            lon: 현재 경도

        Returns:
            안내 정보 딕셔너리

        Raises:
            SessionNotFoundException: 세션이 없을 때
            InvalidLocationException: 유효하지 않은 위치일 때
        """
        # 세션 확인
        session = self.redis_client.get_session(user_id)
        if not session:
            raise SessionNotFoundException("활성 세션이 없습니다")

        # 현재 위치에서 가장 가까운 역 찾기
        current_station_cd = self._find_nearest_station(lat, lon)

        # 세션에서 경로 정보 추출
        route_sequence = session["route_sequence"]
        destination_cd = session["destination_cd"]
        transfer_stations = session.get("transfer_stations", [])
        transfer_info = session.get("transfer_info", [])

        logger.debug(
            f"안내 계산: user={user_id}, current={current_station_cd}, route_len={len(route_sequence)}"
        )

        # 경로 상에서 현재 위치 찾기
        try:
            current_idx = route_sequence.index(current_station_cd)
        except ValueError:
            # 경로 이탈 감지
            nearest_name = get_station_name_by_code(current_station_cd)
            logger.warning(f"경로 이탈: user={user_id}, nearest={nearest_name}")

            return {
                "recalculate": True,
                "message": "경로를 이탈했습니다. 경로를 다시 계산합니다.",
                "current_location": current_station_cd,
                "nearest_station": nearest_name,
            }

        # 목적지 도착 확인
        if current_station_cd == destination_cd:
            logger.info(
                f"목적지 도착: user={user_id}, destination={session['destination']}"
            )

            return {
                "arrived": True,
                "message": "목적지에 도착했습니다!",
                "destination": session["destination"],
                "destination_cd": destination_cd,
            }

        # 경로 안내 계산
        if current_idx < len(route_sequence) - 1:
            next_station_cd = route_sequence[current_idx + 1]
            next_station_info = self.stations.get(next_station_cd)

            if not next_station_info:
                raise InvalidLocationException("다음 역 정보를 찾을 수 없습니다")

            # 다음 역까지 거리 계산
            distance = self.distance_calc.calculate_distance(
                lat, lon, next_station_info["lat"], next_station_info["lng"]
            )

            # 역 이름 조회
            current_station_name = get_station_name_by_code(current_station_cd)
            next_station_name = next_station_info["name"]

            # 진행률 계산
            remaining = len(route_sequence) - current_idx - 1
            progress = int((current_idx / (len(route_sequence) - 1)) * 100)

            guidance = {
                "current_station": current_station_cd,
                "current_station_name": current_station_name,
                "next_station": next_station_cd,
                "next_station_name": next_station_name,
                "distance_to_next": round(distance, 2),
                "remaining_stations": remaining,
                "route_id": session["route_id"],
                "progress_percent": progress,
            }

            # 환승역 확인
            if next_station_cd in transfer_stations:
                # 환승 상세 정보 찾기
                transfer_detail = next(
                    (t for t in transfer_info if t[0] == next_station_cd), None
                )

                if transfer_detail:
                    from_line = transfer_detail[1]
                    to_line = transfer_detail[2]

                    guidance["is_transfer"] = True
                    guidance["transfer_from_line"] = from_line
                    guidance["transfer_to_line"] = to_line
                    guidance["message"] = (
                        f"{next_station_name}에서 {from_line} → {to_line} 환승하세요"
                    )

                    logger.info(
                        f"환승 안내: user={user_id}, station={next_station_name}, {from_line}→{to_line}"
                    )
                else:
                    guidance["is_transfer"] = False
                    guidance["message"] = (
                        f"{next_station_name} 방향으로 이동 중 (약 {int(distance)}m)"
                    )
            else:
                guidance["is_transfer"] = False
                guidance["message"] = (
                    f"{next_station_name} 방향으로 이동 중 (약 {int(distance)}m)"
                )

            # 세션에 현재 위치 업데이트
            self.redis_client.update_location(user_id, current_station_cd)

            logger.debug(
                f"안내 생성: user={user_id}, next={next_station_name}, dist={distance:.2f}m, progress={progress}%"
            )

            return guidance

        raise InvalidLocationException("경로가 올바르지 않습니다")

    def _find_nearest_station(self, lat: float, lon: float) -> str:
        """
        현재 위치에서 가장 가까운 역 찾기

        Args:
            lat: 위도
            lon: 경도

        Returns:
            가장 가까운 역의 station_cd
        """
        min_dist = float("inf")
        nearest_cd = None

        for station_cd, info in self.stations.items():
            dist = self.distance_calc.calculate_distance(
                lat, lon, info["lat"], info["lng"]
            )

            if dist < min_dist:
                min_dist = dist
                nearest_cd = station_cd

        logger.debug(f"가장 가까운 역: {nearest_cd} (거리: {min_dist:.2f}m)")

        return nearest_cd

    def _find_nearest_station_name(self, lat: float, lon: float) -> str:
        """
        현재 위치에서 가장 가까운 역 이름 반환

        Args:
            lat: 위도
            lon: 경도

        Returns:
            가장 가까운 역 이름
        """
        station_cd = self._find_nearest_station(lat, lon)
        return get_station_name_by_code(station_cd)
