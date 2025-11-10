# mc_raptor <- 최적화 적용한 라벨에 맞추어 수정, 역추적 로직 사용
# 환승 직후, 출발역 => 양방향 탐색 진행

# import heapq
from typing import List, Dict, Tuple, Optional, Set
from label import Label
from database import get_db_cursor
from distance_calculator import DistanceCalculator
from anp_weights import ANPWeightCalculator
from config import CIRCULAR_LINES, DEFAULT_TRANSFER_DISTANCE, WALKING_SPEED
import logging

logger = logging.getLogger(__name__)


class McRaptor:
    def __init__(self):
        self.distance_calculator = DistanceCalculator()
        self.anp_calculator = ANPWeightCalculator()

        self._load_station_data()
        self._load_line_data()
        self._load_transfer_data()

    # 데이터를 사전 적재하여 쿼리 반복 호출보다 메모리 효율적으로 동작
    def _load_station_data(self):
        """지하철 역 데이터 로드"""
        query = """
            SELECT station_cd, name, line, lat, lng
            FROM subway_station
        """

        self.stations = {}
        with get_db_cursor() as cursor:
            cursor.execute(query)
            for row in cursor.fetchall():
                station_cd = row["station_cd"]
                self.stations[station_cd] = {
                    "station_name": row["name"],
                    "line": row["line"],
                    "latitude": row["lat"],
                    "longitude": row["lng"],
                }

    def _load_line_data(self):
        """노선 데이터 로드"""
        query = """
            SELECT line, up_station_name, down_station_name, section_order
            FROM subway_section
            ORDER BY line, section_order
        """

        self.line_stations = {}
        with get_db_cursor() as cursor:
            cursor.execute(query)

            current_line = None
            up_sequence = []

            for row in cursor.fetchall():
                line = row["line"]

                if line != current_line:
                    if current_line and up_sequence:
                        self.line_stations[current_line] = {
                            "up": up_sequence,
                            "down": up_sequence[::-1],
                        }
                    current_line = line
                    up_sequence = []

                # station_cd 조회
                up_station_cd = self._get_station_cd_by_name(
                    row["up_station_name"], line
                )
                down_station_cd = self._get_station_cd_by_name(
                    row["down_station_name"], line
                )

                if up_station_cd and up_station_cd not in up_sequence:
                    up_sequence.append(up_station_cd)
                if down_station_cd and down_station_cd not in up_sequence:
                    up_sequence.append(down_station_cd)

            # 마지막 노선 처리
            if current_line and up_sequence:
                self.line_stations[current_line] = {
                    "up": up_sequence,
                    "down": up_sequence[::-1],
                }

    def _get_station_cd_by_name(self, station_name: str, line: str) -> Optional[str]:
        """역 이름과 노선으로 station_cd 조회"""
        for station_cd, info in self.stations.items():
            if info["name"] == station_name and info["line"] == line:
                return station_cd
            return None

    def _load_transfer_data(self):
        """환승데이터 로드"""
        query = """
            SELECT station_cd, line_num, transfer_line, distance, time
            FROM transfer_distance_time
        """

        self.transfers = {}
        with get_db_cursor() as cursor:
            cursor.execute(query)
            for row in cursor.fetchall():
                station_cd = row["station_cd"]
                from_line = row["line_num"]
                to_line = row["transfer_line"]

                key = (station_cd, from_line, to_line)
                self.transfers[key] = {
                    "transfer_time": row["time"] or 3.0,
                    "transfer_distance": row["distance"] or DEFAULT_TRANSFER_DISTANCE,
                }

    def _get_stations_on_line(self, station_cd: str, line: str) -> Dict[str, List[str]]:
        """노선의 역 목록 조회"""
        if line not in self.line_stations:
            return {"up": [], "down": []}

        result = {}
        for direction in ["up", "down"]:
            stations = self.line_stations[line][direction]
            if station_cd in stations:
                result[direction] = stations
            else:
                result[direction] = []

        return result

    def _get_available_lines(self, station_cd: str) -> List[str]:
        """역에서 이용 가능한 노선 목록"""
        lines = []
        for line, directions in self.line_stations.items():
            # 이 부분에선 순환선 처리X -> 직진 로직에서 처리함
            if station_cd in directions["up"] or station_cd in directions["down"]:
                lines.append(line)
        return lines

    def _calculate_travel_time(self, from_cd: str, to_cd: str) -> float:
        """두 역간 이동 시간 계산"""
        from_station = self.stations.get(from_cd)
        to_station = self.stations.get(to_cd)

        if not from_station or not to_station:
            return 2.0

        coord1 = (from_station["latitude"], from_station["longitude"])
        coord2 = (to_station["latitude"], to_station["longitude"])

        distance = self.distance_calculator.haversine(coord1, coord2)

        avg_speed = 33.0  # 서울 지하철 평균 속도(표정속도 기준) km/h
        travel_time = (distance / 1000 / avg_speed) * 60

        return max(travel_time, 1.0)

    def find_routes(
        self,
        origin_cd: str,
        destination_cd_set: Set[str],
        disability_type: str = "PHY",
        max_rounds: int = 5,
    ) -> List[Label]:
        """경로 탐색(경량화한 Label, 탐색 방향 로직 강화 적용)"""
        origin_lines = self._get_available_lines(origin_cd)
        if not origin_lines:
            return []

        origin_line = origin_lines[0]

        # 초기 라벨 생성
        initial_label = Label(
            arrival_time=0.0,
            transfers=0,
            convenience_sum=0.0,
            congestion_sum=0.0,
            max_transfer_difficulty=0,
            parent_label=None,
            current_station_cd=origin_cd,
            current_line=origin_line,
            current_direction="",  # up으로 정하지 말고 "" 빈값으로 세팅하기
            visited_stations=frozenset([origin_cd]),
            depth=1,
            transfer_info=None,
            is_first_move=True,
            created_num=0,
        )

        candidates = [initial_label]
        to_explore = [initial_label]
        best_per_state = {(origin_cd, origin_line, 0): initial_label}

        # 메인 탐색 루프
        for round_num in range(1, max_rounds + 1):
            if not to_explore:
                break

            to_explore_labels = to_explore[:]
            to_explore = []

            for label in to_explore_labels:
                current_line = label.current_line
                station_cd = label.current_station_cd

                # 목적지 도착 확인 -> 도착해도 탐색을 중지하진 않음, 경로 추가 탐색 필요
                if station_cd in destination_cd_set:
                    continue

                available_lines = self._get_available_lines(station_cd)

                for line in available_lines:
                    line_start_cd = station_cd
                    is_transfer = current_line != line

                    # 환승 시 => 환승 라벨 별도 생성
                    if is_transfer:
                        new_label = self._create_new_label(
                            label,
                            line_start_cd,
                            station_cd,
                            line_start_cd,
                            line,
                            round_num,
                            0.0,
                            "",
                            True,
                            disability_type,
                        )

                        state_key = (line_start_cd, line, new_label.transfers)

                        if state_key not in best_per_state:
                            best_per_state[state_key] = new_label
                            to_explore.append(new_label)
                            candidates.append(new_label)
                        else:
                            existing = best_per_state[state_key]
                            # 지배하는 것을 best로 저장
                            if new_label.dominates(existing):
                                best_per_state[state_key] = new_label
                                to_explore.append(new_label)
                                candidates.append(new_label)

                    # 직진 시 => 방향 판단이 필요
                    else:
                        directions_map = self._get_stations_on_line(line_start_cd, line)

                        # 방향 판단 로직
                        # 출발역 or 환승 직후 => 양방향
                        # 그외 => 단방향
                        if label.is_first_move or label.depth == 1:
                            direction_keys = (
                                ["up", "down"]
                                if line not in CIRCULAR_LINES
                                else ["in", "out"]
                            )
                        else:
                            direction_keys = [label.current_direction]

                        for direction in direction_keys:
                            if direction not in directions_map:
                                continue

                            stations_in_direction = directions_map[direction]
                            if (
                                not stations_in_direction
                                or station_cd not in stations_in_direction
                            ):
                                continue

                            current_idx = stations_in_direction.index(station_cd)
                            directions_to_explore = stations_in_direction[
                                current_idx + 1 :
                            ]

                            cumulative_travel_time = 0.0
                            previous_station_cd = station_cd

                            for next_station_cd in directions_to_explore:
                                # U턴 방지!!!
                                if next_station_cd in label.visited_stations:
                                    continue

                                segment_time = self._calculate_travel_time(
                                    previous_station_cd, next_station_cd
                                )
                                cumulative_travel_time += segment_time

                                new_label = self._create_new_label(
                                    label,
                                    station_cd,
                                    station_cd,  # 탑승역으로 고정
                                    next_station_cd,
                                    line,
                                    round_num,
                                    cumulative_travel_time,
                                    direction,
                                    False,
                                    disability_type,
                                )

                                state_key = (next_station_cd, line, new_label.transfers)

                                if state_key not in best_per_state:
                                    best_per_state[state_key] = new_label
                                    to_explore.append(new_label)
                                    candidates.append(new_label)
                                else:
                                    existing = best_per_state[state_key]
                                    if new_label.dominates(existing):
                                        best_per_state[state_key] = new_label
                                        to_explore.append(new_label)
                                        candidates.append(new_label)

                                previous_station_cd = next_station_cd

        final_routes = [
            label
            for label in candidates
            if label.current_station_cd in destination_cd_set
        ]

        return final_routes

    def _create_new_label(
        self,
        prev_label: Label,
        from_station_cd: str,
        prev_stop_cd: str,
        to_station_cd: str,
        line: str,
        created_round_num: int,
        cumulative_travel_time: float,
        direction: str,
        is_first_move: bool,
        disability_type: str,
    ) -> Label:
        """새 라벨 생성"""

        from config import WALKING_SPEED

        is_transfer = prev_label.current_line != line

        transfer_time = 0.0
        current_transfer_info = None
        new_max_difficulty = prev_label.max_transfer_difficulty

        if is_transfer:
            from_line = prev_label.current_line
            to_line = line

            current_transfer_info = (from_station_cd, from_line, to_line)

            transfer_key = (from_station_cd, from_line, to_line)

            # 환승 거리 조회
            if transfer_key in self.transfers:
                transfer_data = self.transfers[transfer_key]
                transfer_distance = transfer_data.get(
                    "transfer_distance", DEFAULT_TRANSFER_DISTANCE
                )
            else:
                transfer_distance = DEFAULT_TRANSFER_DISTANCE

            # 환승역 시설 점수 조회
            facility_scores = self._get_facility_scores(
                from_station_cd, disability_type
            )

            # ANP 환승 난이도 계산
            difficulty = self.anp_calculator.calculate_transfer_difficulty(
                transfer_distance, facility_scores, disability_type
            )
            new_max_difficulty = max(new_max_difficulty, difficulty)

            # 보행 속도로 환승 시간 계산 (m/s → m/min 변환)
            walking_speed_m_per_s = WALKING_SPEED.get(disability_type, 0.98)
            walking_speed_m_per_min = walking_speed_m_per_s * 60
            transfer_time = transfer_distance / walking_speed_m_per_min

        # visited_stations 갱신
        new_visited = prev_label.visited_stations | {to_station_cd}

        # ANP 편의성 계산 (anp_calculator 사용)
        to_station_facility_scores = self._get_facility_scores(
            to_station_cd, disability_type
        )
        convenience = self.anp_calculator.calculate_convenience_score(
            disability_type, to_station_facility_scores
        )

        # ANP 혼잡도 계산
        congestion = self.anp_calculator.calculate_route_congestion_score(
            to_station_cd, line
        )

        new_convenience_sum = prev_label.convenience_sum + convenience
        new_congestion_sum = prev_label.congestion_sum + congestion

        return Label(
            arrival_time=prev_label.arrival_time
            + cumulative_travel_time
            + transfer_time,
            transfers=prev_label.transfers + (1 if is_transfer else 0),
            convenience_sum=new_convenience_sum,
            congestion_sum=new_congestion_sum,
            max_transfer_difficulty=new_max_difficulty,
            parent_label=prev_label,
            current_station_cd=to_station_cd,
            current_line=line,
            current_direction=direction,
            visited_stations=new_visited,
            depth=prev_label.depth + 1,
            transfer_info=current_transfer_info,
            is_first_move=is_first_move,
            created_round=created_round_num,
        )

    def rank_routes(
        self, routes: List[Label], disability_type: str
    ) -> List[Tuple[Label, float]]:
        """경로 순위화 및 중복 제거"""
        anp_weights = self.anp_calculator.calculate_weights(disability_type)

        scored_routes = []
        for route in routes:
            # ANP 계산기로 점수 계산
            score = self.anp_calculator.calculate_route_score(route, anp_weights)
            scored_routes.append((route, score))

        scored_routes.sort(key=lambda x: x[1])

        # 중복 제거
        unique_routes = []
        seen_patterns = set()

        for route, score in scored_routes:
            transfer_context = route.reconstruct_transfer_context()
            pattern = tuple(transfer_context)

            if pattern not in seen_patterns:
                unique_routes.append((route, score))
                seen_patterns.add(pattern)

        return unique_routes
