from distance_calculator import DistanceCalculator
from database import get_all_stations
from mc_raptor import McRaptor
from anp_weights import ANPWeightCalculator
from redis_client import RedisSessionManager
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class NavigationService:
    def __init__(self, redis_client):
        self.redis_client = RedisSessionManager()
        self.distance_calc = DistanceCalculator()
        self.stations = get_all_stations()
        self.raptor = McRaptor()
        self.anp = ANPWeightCalculator()

    def calculate_route(self, start, destination, disability_type):
        try:
            departure_time = self._get_current_minutes()  # 함수 호출 시간 => 출발 시각
            routes = self.raptor.find_routes(
                origin=start,
                destination=destination,
                departure_time=departure_time,
                disability_type=disability_type,
                max_rounds=5,  # 하드 코딩된 부분 나중에 환경변수로 수정하기
            )

            if routes:
                ranked = self.raptor.rank_routes(routes, disability_type)
                best_route = ranked[0][0]

                return {
                    "start": start,
                    "destination": destination,
                    "route_sequence": best_route.route,
                    "total_time": best_route.arrival_time,
                    "transfers": best_route.transfers,
                    "transfer_stations": list(best_route.transfer_stations),
                }
        except Exception as e:
            logger.error(f"Route calculation error: {e}")
            return None

    def _get_current_minutes(self):
        """현재 시각을 분 단위로 반환(자정 기준 => 00:00)"""
        now = datetime.now()
        return now.hour * 60 + now.minute

    def get_navigation_guide(self, user_id, lat, lon):
        """실시간 경로 안내 제공"""
        session = self.redis_client.get_session(user_id)
        if not session:
            return {"error": "존재하지 않는 세션입니다."}
        # 존재하지 않는 session => error
        # 추후 에러 처리 추가하기

        current_station = self._find_nearest_station(lat, lon)
        route_sequence = session["route_sequence"]
        destination = session["destination"]
        transfer_stations = session.get("transfer_stations", [])

        # 경로에서 현재 위치 확인
        try:
            current_idx = route_sequence.index(current_station)
        except ValueError:
            return {
                "recalculate": True,
                "message": "경로를 이탈했습니다. 경로를 다시 계산합니다.",
                "current_location": current_station,
            }

        # 목적지 도착 확인
        if current_station == destination:
            return {
                "arrived": True,
                "message": "목적지에 도착했습니다!",
                "current_station": current_station,
            }

        # 다음 역 정보
        if current_idx < len(route_sequence) - 1:
            next_station = route_sequence[current_idx + 1]

            # 다음 역까지의 거리 계산
            next_station_info = self.stations.get(next_station)
            if not next_station_info:
                return {"error": "역 정보를 찾을 수 없습니다"}

            distance = self.distance_calc.calculate_distance(
                lat, lon, next_station_info["lat"], next_station_info["lng"]
            )

            # 안내 메시지 생성
            guidance = {
                "current_station": current_station,
                "next_station": next_station,
                "distance_to_next": round(distance, 2),
                "remaining_stations": len(route_sequence) - current_idx - 1,
                "route_id": session["route_id"],
            }

            # 환승역 확인
            if next_station in transfer_stations:
                guidance["is_transfer"] = True
                guidance["message"] = f"{next_station}에서 환승하세요"
            else:
                guidance["is_transfer"] = False
                guidance["message"] = f"{next_station} 방향으로 이동 중"

            # 현재 위치 업데이트
            self.redis_client.update_location(user_id, current_station)

            return guidance

        return {"error": "경로가 올바르지 않습니다. 다시 탐색을 시도해주세요."}

    def _find_nearest_station(self, lat, lon):
        """현재 위치에서 가장 가까운 지하철 역 찾기"""
        min_dist = float("inf")
        nearest = None
        for name, info in self.stations.items():
            dist = self.distance_calc.calculate_distance(
                lat, lon, info["lat"], info["lng"]
            )
            if dist < min_dist:
                min_dist = dist
                nearest = name
        # 추후 어느 정도 차이 이내에 몇 가지 역이 존재할 경우
        # 각 역의 편의성을 조사 => 직접 선택받기 로직 추가하기
        return nearest

    def _is_transfer_station(self, next_station, route_date):
        return next_station in route_date.get("transfer_stations", set())
