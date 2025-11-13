# 최적화 적용 mc_raptor
import heapq
from typing import List, Dict, Tuple, Optional, Set
from collections import defaultdict
from datetime import datetime, timedelta

from label import Label
from database import (
    get_db_cursor,
    get_transfer_distance,
    get_all_transfer_station_conv_scores,
)
from distance_calculator import DistanceCalculator
from anp_weights import ANPWeightCalculator
from config import (
    CIRCULAR_LINES,
    DEFAULT_TRANSFER_DISTANCE,
    WALKING_SPEED,
    EPSILON_CONFIG,
)
import logging

logger = logging.getLogger(__name__)


class McRaptor:
    def __init__(self):
        self.distance_calculator = DistanceCalculator()
        self.anp_calculator = ANPWeightCalculator()

        # key : (staiton_cd, from_line, to_line) -> values: {transfer_distance, facility_scores}
        self.transfers = {}

        # context manager 사용
        self._load_station_data()  # =>  FROM subway_station -> SELECT station_cd, name, line, lat, lng
        self._load_line_data()  # => SELECT line, up_station_name, down_station_name, section_order

        # 종종 station_cd가 다르다는 이유로 환승이 중복되어 발생
        # station_name이 동일한데, line이 변경되는 경우만 환승으로 인정
        # 이를 위한 cache memory => station_name : {station_cd1, station_cd2, ...}
        self._load_transfers()

        # ANP 계산에 사용하는 헬퍼
        self.disability_type = "PHY"
        self.departure_time = datetime.now()

        # Bounded Pareto 설정
        self.max_labels_per_state = 50
        logger.info("epsilon-pruning activated")

    def _load_station_data(self):
        """지하철 역 데이터 로드"""
        query = """
            SELECT station_cd, name, line, lat, lng
            FROM subway_station
        """
        self.stations = {}
        # get_db_cursor 사용 <- cleanup 자동
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
        logger.info(f"McRaptor: 역 {len(self.stations)}개 로드")

    def _load_line_data(self):
        """노선 데이터 로드 (U턴 방지 방향성 구축)"""
        query = """
            SELECT line, up_station_name, down_station_name, section_order
            FROM subway_section
            ORDER BY line, section_order
        """
        self.line_stations = defaultdict(dict)

        # (station_cd, line) -> order 맵
        self.station_order_map = {}
        # (line) -> {order: station_cd} 임시 맵
        temp_line_orders = defaultdict(dict)

        with get_db_cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()

        if not rows:
            logger.error("DB에서 'subway_section' 데이터를 로드하지 못했습니다.")
            return

        # _get_station_cd_by_name 호출 전 self.stations 로드 보장
        if not self.stations:
            logger.error("노선 데이터 로드 전 역 데이터가 로드되어야 합니다.")
            return

        for row in rows:
            line = row["line"]
            order = row["section_order"]

            up_cd = self._get_station_cd_by_name(row["up_station_name"], line)
            down_cd = self._get_station_cd_by_name(row["down_station_name"], line)

            if up_cd:
                if (up_cd, line) not in self.station_order_map:
                    self.station_order_map[(up_cd, line)] = order
                    temp_line_orders[line][order] = up_cd
            if down_cd:
                # down_cd가 up_cd 리스트에 중복 추가되는 것 방지
                if (down_cd, line) not in self.station_order_map:
                    self.station_order_map[(down_cd, line)] = order + 1
                    temp_line_orders[line][order + 1] = down_cd

        # 정렬된 리스트로 변환
        line_to_stations_ordered = {}
        for line, orders_map in temp_line_orders.items():
            sorted_orders = sorted(orders_map.keys())
            line_to_stations_ordered[line] = [
                orders_map[order] for order in sorted_orders
            ]

        # 최종 방향 맵 구축
        for line, ordered_stations in line_to_stations_ordered.items():
            for i, station_cd in enumerate(ordered_stations):
                up_stations = ordered_stations[:i][::-1]  # 0부터 i-1까지 (역순)
                down_stations = ordered_stations[i + 1 :]  # i+1부터 끝까지

                is_circular = line in CIRCULAR_LINES
                # line_stations의 키를 (station_cd, line) 튜플로 설정
                self.line_stations[(station_cd, line)] = {
                    "up": up_stations,
                    "down": down_stations,
                    "in": down_stations if is_circular else [],
                    "out": up_stations if is_circular else [],
                }
        logger.info(f"McRaptor: 방향성 노선 맵 {len(self.line_stations)} 개 구축")

    def _get_station_cd_by_name(self, station_name: str, line: str) -> Optional[str]:
        """역 이름과 노선으로 station_cd 조회 (초기화 시에만 사용)"""
        # (self.stations가 로드된 이후에 호출되어야 함)
        for station_cd, info in self.stations.items():
            if info["station_name"] == station_name and info["line"] == line:
                return station_cd
        # 루프가 끝난 후 None 반환
        return None

    def _load_transfers(self):
        """환승 데이터 통합 로딩 (조합 키 => 거리 + 편의시설 점수)"""

        distance_query = """
            SELECT station_cd, line_num, transfer_line, distance
            FROM transfer_distance_time
            ORDER BY station_cd, line_num, transfer_line
        """
        with get_db_cursor() as cursor:
            cursor.execute(distance_query)
            distance_rows = cursor.fetchall()

        # transfers dictionary 구축
        for row in distance_rows:
            transfer_key = (row["station_cd"], row["line_num"], row["transfer_line"])
            self.transfers[transfer_key] = {
                "transfer_distance": float(row["distance"]),
                "facility_scores": {},
            }

        # 편의시설 점수 로딩 <- database의 함수 사용
        convenience_data = get_all_transfer_station_conv_scores()

        convenience_by_station = {}
        for conv_row in convenience_data:
            station_cd = conv_row["station_cd"]
            convenience_by_station[station_cd] = {
                "PHY": {
                    "elevator": conv_row.get("elevator_phy"),
                    "escalator": conv_row.get("escalator_phy"),
                    "transfer_walk": conv_row.get("transfer_walk_phy"),
                    "other_facil": conv_row.get("other_facil_phy"),
                    "staff_help": conv_row.get("staff_help_phy"),
                },
                "VIS": {
                    "elevator": conv_row.get("elevator_vis"),
                    "escalator": conv_row.get("escalator_vis"),
                    "transfer_walk": conv_row.get("transfer_walk_vis"),
                    "other_facil": conv_row.get("other_facil_vis"),
                    "staff_help": conv_row.get("staff_help_vis"),
                },
                "AUD": {
                    "elevator": conv_row.get("elevator_aud"),
                    "escalator": conv_row.get("escalator_aud"),
                    "transfer_walk": conv_row.get("transfer_walk_aud"),
                    "other_facil": conv_row.get("other_facil_aud"),
                    "staff_help": conv_row.get("staff_help_aud"),
                },
                "ELD": {  # 고령자 - 휠체어 데이터 재사용
                    "elevator": conv_row.get("elevator_phy"),
                    "escalator": conv_row.get("escalator_phy"),
                    "transfer_walk": conv_row.get("transfer_walk_phy"),
                    "other_facil": conv_row.get("other_facil_phy"),
                    "staff_help": conv_row.get("staff_help_phy"),
                },
            }

        # 각 역의 모든 환승에 편의시설 점수 적용
        for transfer_key, transfer_data in self.transfers.items():
            station_cd = transfer_key[0]
            if station_cd in convenience_by_station:
                transfer_data["facility_scores"] = convenience_by_station[station_cd]

        logger.info(f"McRaptor: 환승 데이터 {len(self.transfers)}개 로드 완료")

    def _get_stations_on_line(self, station_cd: str, line: str) -> Dict[str, List[str]]:
        """노선의 역 목록 조회 (사전 구축된 맵)"""
        return self.line_stations.get(
            (station_cd, line), {"up": [], "down": [], "in": [], "out": []}
        )

    def _get_available_lines(self, station_cd: str) -> List[str]:
        """역에서 이용 가능한 노선 목록 (사전 구축된 맵)"""
        station_info = self.stations.get(station_cd)
        if not station_info:
            return []

        station_name = station_info.get("station_name")
        lines = []
        for cd, info in self.stations.items():
            if info["station_name"] == station_name:
                lines.append(info["line"])
        return list(set(lines))  # 중복 제거

    def _calculate_travel_time(self, from_cd: str, to_cd: str) -> float:
        """두 역간 이동 시간 계산 (분)"""
        from_station = self.stations.get(from_cd)
        to_station = self.stations.get(to_cd)

        if not from_station or not to_station:
            return 2.0  # 기본값

        coord1 = (from_station["latitude"], from_station["longitude"])
        coord2 = (to_station["latitude"], to_station["longitude"])

        distance_m = self.distance_calculator.haversine(coord1, coord2)

        # 표정속도 33km/h (약 550m/min) 기준 <- 서울 교통공사 참고
        avg_speed_m_per_min = 550.0
        travel_time = distance_m / avg_speed_m_per_min

        return max(travel_time, 1.0)  # 최소 1분

    def find_routes(
        self,
        origin_cd: str,
        destination_cd_set: Set[str],
        departure_time: datetime,  # 혼잡도를 더욱 정확히 계산하기 위함
        disability_type: str = "PHY",
        max_rounds: int = 5,
    ) -> List[Label]:
        """경로 탐색 <- 파레토 최적화 및 메모리 최적화 적용"""

        self.disability_type = disability_type
        self.departure_time = departure_time

        origin_lines = self._get_available_lines(origin_cd)
        if not origin_lines:
            return []

        # key(station_cd, line, transfers) -> List[Label]
        labels = defaultdict(list)
        # marking
        Q = set()

        # 모든 출발(가능한) 노선에 대해 초기 라벨 생성
        for origin_line in origin_lines:
            origin_convenience = self._get_convenience_score(origin_cd, disability_type)
            origin_congestion = self._get_congestion_score(
                origin_cd, origin_line, "up", departure_time
            )  # 출발역에서 방향은 일단 up으로 세팅

            initial_label = Label(
                arrival_time=0.0,
                transfers=0,
                convenience_sum=origin_convenience,
                congestion_sum=origin_congestion,
                max_transfer_difficulty=0.0,
                parent_label=None,
                current_station_cd=origin_cd,
                current_line=origin_line,
                current_direction="",
                visited_stations=frozenset([origin_cd]),
                depth=1,
                transfer_info=None,
                is_first_move=True,
                created_round=0,
            )
            # transfer state
            state_key = (origin_cd, origin_line, 0)
            labels[state_key].append(initial_label)
            # 출발역 마킹
            Q.add(origin_cd)

        for round_num in range(1, max_rounds + 1):
            if not Q:
                break

            logger.info(f"=== Round {round_num}: 마킹 {len(Q)}개 시작 ===")
            logger.info(f"현재 전체 라벨 수: {sum(len(v) for v in labels.values())}개")

            Q_next_round = set()

            # 마킹한 역만 탐색
            current_round_labels_to_explore = []
            for state_key, state_labels in labels.items():
                station_cd, line, transfers = state_key
                if station_cd in Q:
                    for l in state_labels:
                        # 이전 라운드 라벨만 탐색
                        if l.created_round < round_num:
                            current_round_labels_to_explore.append(l)
            for label in current_round_labels_to_explore:
                current_line = label.current_line
                station_cd = label.current_station_cd

                # 목적지에 도착한 라벨은 더 이상 확장하지 않음
                if station_cd in destination_cd_set:
                    continue

                availables_lines = self._get_available_lines(station_cd)

                for line in availables_lines:
                    line_start_cd = station_cd
                    # 현재 환승 판단 기준 => 호선만 비교
                    # 출발역에서의 노선 선택 => 환승 아님
                    if label.depth == 1:
                        is_transfer = False
                    else:
                        is_transfer = current_line != line

                    if label.transfers + (1 if is_transfer else 0) > round_num:
                        continue

                    if is_transfer:
                        # 환승 직후 같은 역에서 연속 환승 방지 로직 추가!!!
                        if label.is_first_move and label.parent_label is not None:
                            continue  # 환승 시도 차단

                        transfer_station_name = self.stations[station_cd][
                            "station_name"
                        ]
                        line_start_cd_found = self._get_station_cd_by_name(
                            transfer_station_name, line
                        )
                        if not line_start_cd_found:
                            continue
                        line_start_cd = line_start_cd_found

                        # 환승 목적지가 도착역일 경우
                        if line_start_cd in destination_cd_set:
                            continue  # 도착했으므로 환승할 필요 없음

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

                        # 파레토 프론티어 갱신!!!
                        state_key = (line_start_cd, line, new_label.transfers)
                        updated = self._update_pareto_frontier(
                            new_label, labels[state_key]
                        )
                        if updated:
                            Q_next_round.add(line_start_cd)

                    # 직진 로직
                    else:
                        directions_map = self._get_stations_on_line(line_start_cd, line)

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

                            cumulative_travel_time = 0.0

                            previous_station_cd_for_direction = station_cd

                            for next_station_cd in stations_in_direction:
                                if next_station_cd in label.visited_stations:
                                    continue

                                segment_time = self._calculate_travel_time(
                                    previous_station_cd_for_direction, next_station_cd
                                )

                                # 병렬 누적 시간
                                # 이전 역까지의 누적 시간이 아닌, 탑승역부터의 누적 시간
                                cumulative_travel_time += segment_time

                                new_label = self._create_new_label(
                                    label,
                                    station_cd,
                                    previous_station_cd_for_direction,
                                    next_station_cd,
                                    line,
                                    round_num,
                                    cumulative_travel_time,  # 병렬 누적 시간
                                    direction,
                                    False,
                                    disability_type,
                                )

                                # 파레토 프론티어 갱신!!!
                                state_key = (next_station_cd, line, new_label.transfers)
                                updated = self._update_pareto_frontier(
                                    new_label, labels[state_key]
                                )
                                if updated:
                                    Q_next_round.add(next_station_cd)

                                previous_station_cd_for_direction = next_station_cd

            Q = Q_next_round  # 다음 라운드 마킹 갱신

        # 최종 경로 필터링
        final_routes = []
        for (station_cd, line, transfers), state_labels in labels.items():
            if station_cd in destination_cd_set:
                final_routes.extend(state_labels)

        return list(final_routes)  # => set으로 중복 라벨 제거

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
        """새 라벨 생성 (ANP 점수 계산 포함)"""

        # 환승 판단 : prev_label의 parent_label이 없으면(출발역에서의 이동) => 환승 아님
        if prev_label.parent_label is None:
            is_transfer = False
        else:
            is_transfer = prev_label.current_line != line

        transfer_time = 0.0
        current_transfer_info = None
        new_max_difficulty = prev_label.max_transfer_difficulty

        if is_transfer:  # 탑승 시에만 !!! 계산 !!!
            from_line = prev_label.current_line
            to_line = line
            current_transfer_info = (from_station_cd, from_line, to_line)
            transfer_key = (from_station_cd, from_line, to_line)

            if transfer_key in self.transfers:
                transfer_data = self.transfers[transfer_key]
                transfer_distance = transfer_data.get(
                    "transfer_distance", DEFAULT_TRANSFER_DISTANCE
                )

                facility_scores = transfer_data.get("facility_scores", {}).get(
                    disability_type, {}
                )
            else:
                transfer_distance = DEFAULT_TRANSFER_DISTANCE
                facility_scores = {}  # 기본값

            difficulty = self.anp_calculator.calculate_transfer_difficulty(
                transfer_distance, facility_scores, disability_type
            )
            new_max_difficulty = max(new_max_difficulty, float(difficulty))

            walking_speed_m_per_s = WALKING_SPEED.get(disability_type, 0.98)
            walking_speed_m_per_min = walking_speed_m_per_s * 60
            if walking_speed_m_per_min == 0:
                transfer_time = 5.0
            else:
                transfer_time = transfer_distance / walking_speed_m_per_min

        # visited_stations 갱신
        new_visited = prev_label.visited_stations | {to_station_cd}

        # ANP 편의성 계산
        convenience = self._get_convenience_score(to_station_cd, disability_type)

        # ANP 혼잡도 계산
        congestion_time = self.departure_time + timedelta(
            minutes=(prev_label.arrival_time + cumulative_travel_time)
        )
        congestion = self._get_congestion_score(
            to_station_cd, line, direction, congestion_time
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

    def _get_convenience_score(self, station_cd: str, disability_type: str) -> float:
        """ANP 계산 헬퍼 함수"""
        facility_scores = {}

        station_name = self.stations.get(station_cd, {}).get("station_name")
        if not station_name:
            # MVP에선 임시로 리스트에 존재하지 않을 경우 => 기본점수 2.5
            return 2.5  # 추후 편의 시설 db 추가로 구축한 다음, 로직 전체 수정하기

        for (key_cd, from_line, to_line), data in self.transfers.items():
            if key_cd == station_cd:
                ## 검토 필요
                facility_scores = data.get("facility_scores", {}).get(
                    disability_type, {}
                )
                if facility_scores and any(
                    v is not None for v in facility_scores.values()
                ):
                    break
        if not facility_scores or not any(
            v is not None for v in facility_scores.values()
        ):
            return 2.5

        return self.anp_calculator.calculate_convenience_score(
            disability_type, facility_scores
        )

    def _get_congestion_score(
        self, station_cd: str, line: str, direction: str, time: datetime
    ) -> float:
        """역의 혼잡도 점수 계산"""
        return self.anp_calculator.get_congestion_from_rds(
            station_cd, line, direction, time
        )

    def _update_pareto_frontier(
        self, new_label: Label, existing_labels: List[Label]
    ) -> bool:
        """pareto frontier를 갱신
        새로운 라벨이 지배되지 않고 추가되었을 때 => True
        이는 단순한 추가뿐만 아니라, 기존 라벨 중 새라벨에 의해 지배되는 것들을 제거하는 것까지 포함
        => 파레토 최적해를 만족하며 라벨 폭증을 막음 and pareto frontier는 비지배 집합이어야 함
        + epsilon-pruning + Bounded Pareto"""

        # 유형별 epsilon 값 가져오기
        epsilon = EPSILON_CONFIG.get(self.disability_type, 0.05)

        # ANP 가중치 가져오기
        anp_weights = self.anp_calculator.calculate_weights(self.disability_type)

        is_dominated_by_existing = False
        was_updated = False

        # 엄격한 파레토 지배 체크
        for existing in existing_labels:
            if existing.dominates(new_label):
                is_dominated_by_existing = True
                return False

        # epsilon-similarity check
        similar_label_found = False
        label_to_remove = None

        for existing in existing_labels:
            if new_label.epsilon_similar(existing, epsilon, anp_weights):
                # 유사할 경우 -> 더 나은 것만 유지
                new_score = new_label.calculate_weighted_score(anp_weights)
                existing_score = existing.calculate_weighted_score(anp_weights)

                if new_score >= existing_score:
                    return False
                else:
                    label_to_remove = existing
                    similar_label_found = True
                    break

        if similar_label_found and label_to_remove is not None:
            existing_labels.remove(label_to_remove)

        # 기존 라벨 중 new_label에게 지배당하는 것을 제거
        for i in range(len(existing_labels) - 1, -1, -1):
            if new_label.dominates(
                existing_labels[i]
            ):  # new_label에 의해 지배당할 경우
                existing_labels.pop(i)  # 기존 라벨 제거

        # 새 라벨 추가
        existing_labels.append(new_label)

        # Bounded Pareto
        if len(existing_labels) > self.max_labels_per_state:
            existing_labels.sort(key=lambda l: l.calculate_weighted_score(anp_weights))
            del existing_labels[self.max_labels_per_state :]

        return True

    def rank_routes(
        self, routes: List[Label], disability_type: str
    ) -> List[Tuple[Label, float]]:
        """페널티 오름차순 정렬 및 중복 제거"""
        anp_weights = self.anp_calculator.calculate_weights(disability_type)

        scored_routes = []
        for route in routes:
            score = route.calculate_weighted_score(anp_weights)
            scored_routes.append((route, score))

        scored_routes.sort(key=lambda x: x[1])

        # 환승 패턴 기준 중복 제거
        unique_routes = []
        seen_patterns = set()

        for route, score in scored_routes:
            transfer_info = route.reconstruct_transfer_info()
            pattern = tuple(transfer_info)

            if pattern not in seen_patterns:
                unique_routes.append((route, score))
                seen_patterns.add(pattern)

        return unique_routes

    def _determine_direction(
        self, from_station_cd: str, to_station_cd: str, line: str
    ) -> str:
        from_order = self.station_order_map.get((from_station_cd, line))
        to_order = self.station_order_map.get((to_station_cd, line))

        if from_order is not None and to_order is not None:
            if line in CIRCULAR_LINES:
                return "in" if to_order > from_order else "out"
            else:
                return "down" if to_order > from_order else "up"
        # 환승 직후 from_order가 None일 수 있음
        # 이 경우 기본값 'up' 반환 (어차피 is_first_move=True에서 양방향 탐색함)
        return "up"
