from typing import List, Dict, Set, Tuple, Optional
from collections import defaultdict
from datetime import datetime, timedelta
import logging

from label import Label
from anp_weights import ANPWeightCalculator
from database import get_station_info, get_transfer_distance
from config import CIRCULAR_LINES

logger = logging.getLogger(__name__)


class McRaptor:
    def __init__(
        self,
        stations: List[Dict],
        sections: List[Dict],
        convenience_scores: List[Dict],
        anp_calculator: Optional[ANPWeightCalculator] = None,
    ):
        self.stations = {s["station_id"]: s for s in stations}
        self.sections = sections
        self.convenience_scores = {c["station_cd"]: c for c in convenience_scores}

        # ANP 계산기
        self.anp_calculator = anp_calculator or ANPWeightCalculator()

        # 역 연결 그래프 구축
        self.graph = self._build_graph()

        # 역 정보 캐시
        self.station_info_cache = {}

        # 현재 탐색 중인 장애 유형 및 출발 시각
        self.disability_type = None
        self.departure_time = None

    def _build_graph(self) -> Dict:
        """역 연결 그래프 구축"""
        graph = defaultdict(list)

        for section in self.sections:
            up_station = section["up_station_name"]
            down_station = section["down_station_name"]
            line = section["line"]

            graph[up_station].append(
                {"to": down_station, "line": line, "order": section["section_order"]}
            )
            graph[down_station].append(
                {"to": up_station, "line": line, "order": section["section_order"]}
            )

        return graph

    def find_routes(
        self,
        origin: str,
        destination: str,
        departure_time: datetime,
        disability_type: str,
        max_rounds: int = 4,
    ) -> List[Label]:
        """
        Mc-RAPTOR 알고리즘으로 파레토 최적 경로 탐색

        Args:
            origin: 출발역 이름
            destination: 도착역 이름
            departure_time: 출발 시각
            disability_type: 장애 유형 (PHY/VIS/AUD/ELD)
            max_rounds: 최대 환승 횟수

        Returns:
            List[Label]: 파레토 최적 경로들
        """

        # 전역 상태 설정
        self.disability_type = disability_type
        self.departure_time = departure_time

        # 파레토 프론티어
        labels = defaultdict(list)

        # 출발역 정보 찾기
        origin_info = self._get_station_info_by_name(origin)
        if not origin_info:
            raise ValueError(f"출발역 '{origin}'을 찾을 수 없습니다.")

        # 출발역의 초기 혼잡도
        origin_line = None
        for station in self.stations.values():
            if station["name"] == origin:
                origin_line = station["line"]
                break

        initial_congestion = self.anp_calculator.get_congestion_from_rds(
            origin_info.get("station_cd", ""),
            origin_line,
            "up",  # 초기 방향은 임의 설정
            departure_time,
        )

        # 출발역의 편의도
        origin_convenience = self._calculate_convenience_score(origin)

        # 초기 라벨 생성
        labels[origin].append(
            Label(
                arrival_time=0.0,
                transfers=0,
                transfer_difficulty=0.0,
                convenience_score=origin_convenience,
                congestion_score=initial_congestion,
                route=[origin],
                lines=[origin_line],
                created_round=0,
            )
        )

        # Round별 탐색
        for round_num in range(max_rounds):
            logger.info(f"=== Round {round_num} 시작 ===")
            updated = False

            for station_name, station_labels in list(labels.items()):
                if station_name not in self.graph:
                    continue

                for label in station_labels:
                    # 이미 최대 환승수를 초과한 라벨은 스킵
                    if label.transfers > round_num:
                        continue

                    current_line = label.lines[-1] if label.lines else None
                    available_lines = set(
                        neighbor["line"] for neighbor in self.graph[station_name]
                    )

                    for line in available_lines:
                        is_transfer = line != current_line

                        # 환승이 필요한데 이미 round 제한에 도달했으면 스킵
                        if is_transfer and label.transfers >= round_num:
                            continue

                        # 해당 노선으로 갈 수 있는 역들
                        reachable_stations = self._get_stations_on_line(
                            station_name, line
                        )

                        for next_station in reachable_stations:
                            # 새 라벨 생성
                            new_label = self._create_new_label(
                                label,
                                station_name,
                                next_station,
                                line,
                                round_num,
                            )

                            # 파레토 최적성 검사
                            if self._is_pareto_optimal(new_label, labels[next_station]):
                                labels[next_station].append(new_label)
                                updated = True

                                # 새 라벨에 의해 지배되는 기존 라벨 제거
                                labels[next_station] = [
                                    l
                                    for l in labels[next_station]
                                    if not new_label.dominates(l)
                                ]

            if not updated:
                logger.info(f"Round {round_num}에서 업데이트 없음. 탐색 종료.")
                break

        return labels.get(destination, [])

    def rank_routes(
        self, routes: List[Label], disability_type: str
    ) -> List[Tuple[Label, float]]:
        """
        경로를 ANP 점수로 순위 매김

        Args:
            routes: 경로 라벨 리스트
            disability_type: 장애 유형

        Returns:
            List[Tuple[Label, float]]: (경로, 점수) 튜플 리스트 (점수 오름차순)
        """
        anp_weights = self.anp_calculator.calculate_weights(disability_type)

        scored_routes = []
        for route in routes:
            score = route.calculate_weighted_score(anp_weights)
            scored_routes.append((route, score))

        # 점수가 낮을수록 좋음
        scored_routes.sort(key=lambda x: x[1])

        return scored_routes

    def _create_new_label(
        self,
        prev_label: Label,
        from_station: str,
        to_station: str,
        line: str,
        created_round_num: int,
    ) -> Label:
        """새로운 라벨 생성"""
        # 이동 시간 (MVP: 2분 고정)
        travel_time = 2.0

        # 환승 여부 확인
        is_transfer = (prev_label.lines[-1] != line) if prev_label.lines else False

        # 환승 난이도 및 시간 계산
        transfer_difficulty_delta = 0.0
        transfer_time = 0.0

        if is_transfer:  # 환승이 발생할 때에만 계산!!!
            from_info = self._get_station_info_by_name(from_station)

            # 환승 거리 조회
            transfer_distance = get_transfer_distance(
                from_info.get("station_cd", ""),
                prev_label.lines[-1],
                line,
            )

            # 환승역 시설 점수 조회
            facility_scores = self._get_facility_scores(from_station)

            # 환승 난이도 계산
            transfer_difficulty_delta = (
                self.anp_calculator.calculate_transfer_difficulty(
                    transfer_distance, facility_scores, self.disability_type
                )
            )

            # 환승 보행시간 계산
            transfer_time = self.anp_calculator.calculate_transfer_walking_time(
                transfer_distance, self.disability_type
            )

            logger.debug(
                f"환승: {from_station}({prev_label.lines[-1]}→{line}) "
                f"거리={transfer_distance:.1f}m, "
                f"난이도={transfer_difficulty_delta:.3f}, "
                f"시간={transfer_time:.1f}초"
            )

        # 도착역 편의도 계산
        new_convenience = self._calculate_convenience_score(to_station)
        avg_convenience = (
            prev_label.convenience_score * len(prev_label.route) + new_convenience
        ) / (len(prev_label.route) + 1)

        # 현재 구간 혼잡도 계산
        to_info = self._get_station_info_by_name(to_station)
        from_info = self._get_station_info_by_name(from_station)
        direction = self._determine_direction(
            from_info.get("station_num", 0), to_info.get("station_num", 0), line
        )

        current_time = self.departure_time + timedelta(minutes=prev_label.arrival_time)
        segment_congestion = self.anp_calculator.get_congestion_from_rds(
            to_info.get("station_cd", ""), line, direction, current_time
        )

        # 혼잡도 평균 계산
        avg_congestion = (
            prev_label.congestion_score * len(prev_label.route) + segment_congestion
        ) / (len(prev_label.route) + 1)

        # 환승역 집합 업데이트
        new_transfer_stations = prev_label.transfer_stations.copy()
        if is_transfer:
            new_transfer_stations.add(from_station)

        return Label(
            arrival_time=prev_label.arrival_time + travel_time + (transfer_time / 60.0),
            transfers=prev_label.transfers + (1 if is_transfer else 0),
            transfer_difficulty=prev_label.transfer_difficulty
            + transfer_difficulty_delta,
            convenience_score=avg_convenience,
            congestion_score=avg_congestion,
            route=prev_label.route + [to_station],
            lines=prev_label.lines + [line],
            transfer_stations=new_transfer_stations,
            created_round=created_round_num,
        )

    def _get_stations_on_line(self, start_station: str, line: str) -> List[str]:
        """특정 노선으로 갈 수 있는 모든 역 반환"""
        reachable = []
        for neighbor in self.graph[start_station]:
            if neighbor["line"] == line:
                reachable.append(neighbor["to"])
        return reachable

    def _get_station_info_cached(self, station_id: str) -> Dict:
        """역 정보 조회 (캐싱)"""
        if station_id not in self.station_info_cache:
            info = get_station_info(station_id)
            if info:
                self.station_info_cache[station_id] = info
            else:
                self.station_info_cache[station_id] = {
                    "station_cd": (
                        station_id[-4:] if len(station_id) >= 4 else station_id
                    ),
                    "station_num": 0,
                    "station_name": station_id,
                }

        return self.station_info_cache[station_id]

    def _get_station_info_by_name(self, station_name: str) -> Dict:
        """역 이름으로 정보 조회"""
        for station in self.stations.values():
            if station["name"] == station_name:
                return self._get_station_info_cached(station["station_id"])

        return {
            "station_cd": "",
            "station_num": 0,
            "station_name": station_name,
        }

    def _get_facility_scores(self, station_name: str) -> Dict[str, float]:
        """역의 시설별 편의도 점수 조회"""
        station_cd = None
        for station in self.stations.values():
            if station["name"] == station_name:
                station_cd = station.get("station_cd")
                break

        if not station_cd:
            return {}

        scores = self.convenience_scores.get(station_cd, {})
        if not scores:
            return {}

        # 장애 유형별 시설 점수 추출
        dtype_suffix = self.disability_type.lower()
        facility_scores = {
            "elevator": scores.get(f"elevator_{dtype_suffix}", 0.0),
            "escalator": scores.get(f"escalator_{dtype_suffix}", 0.0),
            "transfer_walk": scores.get(f"transfer_walk_{dtype_suffix}", 0.0),
            "other_facil": scores.get(f"other_facil_{dtype_suffix}", 0.0),
            "staff_help": scores.get(f"staff_help_{dtype_suffix}", 0.0),
        }

        return facility_scores

    def _calculate_convenience_score(self, station_name: str) -> float:
        """역 편의성 점수 계산"""
        facility_scores = self._get_facility_scores(station_name)

        if not facility_scores:
            return 2.5  # 기본값

        return self.anp_calculator.calculate_convenience_score(
            self.disability_type, facility_scores
        )

    def _determine_direction(
        self, from_station_num: int, to_station_num: int, line_id: str
    ) -> str:
        """방향 결정"""
        if line_id in CIRCULAR_LINES:
            return self._determine_circular_direction(
                from_station_num, to_station_num, line_id
            )

        return "up" if to_station_num > from_station_num else "down"

    def _determine_circular_direction(
        self, from_station_num: int, to_station_num: int, line_id: str
    ) -> str:
        """순환선 방향 결정"""
        if line_id == "2":
            # 2호선 내선/외선 로직 (간단 버전) -> 추후 내/외선 구별 방법 정확히 찾아서 수정하기
            return "in" if to_station_num > from_station_num else "out"

        # 기타 순환선
        return "in" if to_station_num > from_station_num else "out"

    def _is_pareto_optimal(
        self, new_label: Label, existing_labels: List[Label]
    ) -> bool:
        """파레토 최적성 검사"""
        for existing in existing_labels:
            if existing.dominates(new_label):
                return False
        return True
