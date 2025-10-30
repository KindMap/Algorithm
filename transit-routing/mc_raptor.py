from typing import List, Dict, Set, Tuple, Optional
from dataclasses import dataclass, field
from collections import defaultdict
import heapq
import logging
from anp_weights import ANPWeightCalculator

logger = logging.getLogger(__name__)


@dataclass
class Label:
    """경로 라벨 (파레토 최적해)"""

    arrival_time: float
    transfers: int
    walking_distance: float
    convenience_score: float
    route: List[str] = field(default_factory=list)
    lines: List[str] = field(default_factory=list)
    # 지나가는 역들의 line 정보를 담는 list -> 환승 여부 및 횟수 파악
    # 경로는 지나가야 하는 지하철역의 list형태

    def dominates(self, other: "Label") -> bool:
        """파레토 우위 판단"""
        better_in_one = False
        criteria = [  # 소요시간, 환승 횟수, 보행거리 -> 작을 수록 좋음 | 편의도 -> 클 수록 좋음
            (self.arrival_time, other.arrival_time, False),
            (self.transfers, other.transfers, False),
            (self.walking_distance, other.walking_distance, False),
            (self.convenience_score, other.convenience_score, True),
        ]

        for self_val, other_val, maximize in criteria:
            if maximize:
                if self_val < other_val:
                    return False
                elif self_val > other_val:
                    better_in_one = True
            else:
                if self_val > other_val:
                    return False
                elif self_val < other_val:
                    better_in_one = True

        return better_in_one

    def calculate_weighted_score(self, anp_weights: Dict[str, float]) -> float:
        """
        ANP 가중치를 적용한 종합 점수(페널티) 계산

        Args:
            anp_weights (Dict[str, float]): {'travel_time': 0.1, ...}

        Returns:
            float: 가중 종합 페널티 -> 값이 작을 수록 좋음
        """
        # normalize(0-1)
        # 정규화 -> 결과 보면서 조정하기
        norm_time = self.arrival_time / 120.0  # 120분 기준
        norm_transfers = self.transfers / 4.0  # 최대 4회 환승 기준
        norm_walking = self.walking_distance / 2000.0  # 2km 기준
        norm_convenience = 1.0 - (self.convenience_score / 5.0)  # 5점 만점 기준, 역전

        # 가중 종합 페널티
        score = (
            anp_weights.get("travel_time", 0.25) * norm_time
            + anp_weights.get("transfers", 0.25) * norm_transfers
            + anp_weights.get("walking_distance", 0.25) * norm_walking
            + anp_weights.get("convenience", 0.25) * norm_convenience
        )

        return score


class McRAPTOR:

    def __init__(
        self,
        stations: List[Dict],
        sections: List[Dict],
        convenience_scores: List[Dict],
        distance_calc,
        anp_calculator: Optional[ANPWeightCalculator] = None,
    ):
        self.stations = {s["station_id"]: s for s in stations}
        self.sections = sections
        self.convenience_scores = {c["station_cd"]: c for c in convenience_scores}
        self.distance_calc = distance_calc

        # ANP 계산기 (없으면 새로 생성)
        self.anp_calculator = anp_calculator or ANPWeightCalculator()

        # 역 연결 그래프 구축
        self.graph = self._build_graph()

    def _build_graph(self) -> Dict:
        """역 연결 그래프 구축"""
        graph = defaultdict(list)

        for section in self.sections:
            up_station = section["up_station_name"]
            down_station = section["down_station_name"]
            line = section["line"]

            # 양방향 그래프이므로 양방향 연결
            # 상행/하행
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
        departure_time: float,
        disability_type: str,
        max_rounds: int = 4,
    ) -> List[Label]:
        """
        Mc-RAPTOR 알고리즘으로 파레토 최적 경로 탐색

        Args:
            origin (str): 출발역(name)
            destination (str): 도착역
            departure_time (float): 출발 시각
            disability_type (str): user 유형(PHY/VIS/AUD/ELD)
            max_rounds (int, optional): 최대 환승 횟수(default=4)

        Returns:
            List[Label]: 파레토 최적해(경로 리스트)
        """
        # 파레토 프론티어
        labels = defaultdict(list)

        # 출발역의 노선 찾기 -> 프론티어 초기화에 사용
        line_num = None
        for station in self.stations.values():
            if station["name"] == origin:
                line_num = station["line"]
                break

        # 출발역 노선이 없을 경우
        if line_num is None:
            raise ValueError(f"출발역 '{origin}'을 찾을 수 없습니다.")

        # 파레토 프론티어 초기화
        labels[origin].append(
            Label(
                arrival_time=departure_time,
                transfers=0,
                walking_distance=0,
                convenience_score=5.0,
                route=[origin],
                lines=[line_num],  # 출발역의 노선 번호로 초기화
            )
        )

        # round별 탐색
        for round_num in range(max_rounds):
            updated = False
            
            for station_name, station_labels in list(labels.items()):
                if station_name not in self.graph:
                    continue
                
                for label in station_labels:
                    # 현재 역에서 탈 수 있는 노선 전부 확인
                    current_line = label.lines[-1] if label.lines else None
                    
                    # 같은 노선을 따라 갈 수 있는 모든 역 찾기
                    reachable_stations = self._get_stations_on_line(
                        station_name, current_line
                    )
                    
                    for next_station in reachable_stations:
                        new_label = self._create_new_label(
                            label, station_name, next_station,current_line,disability_type
                        )
                        
                        if self._is_pareto_optimal(new_label, labels[next_station]):
                            labels[next_station].append(new_label)
                            updated=True
                            labels[next_station] = [
                                l for l in labels[next_station]
                                if not new_label.dominates()
                            ]
            if not updated:
                break
            
        return labels.get(destination, [])
    
    def _get_stations_on_line(self, start_station: str, line: str) -> List[str]:
        """
        같은 노선을 타고 갈 수 있는 모든 역 반환

        Args:
            start_station (str): 출발역
            line (str): 노선

        Returns:
            List[str]: 같은 노선으로 도달 가능한 역 리스트
        """
        reachable = []
        visited = {start_station}
        queue = [start_station]
        
        while queue:
            current = queue.pop(0)
            
            if current not in self.graph:
                continue
            for neighbor in self.graph[current]:
                next_station = neighbor["to"]
                neighbor_line = neighbor["line"]
                
                # 같은 노선이고 아직 방문하지 않은 역
                if neighbor_line == line and next_station not in visited:
                    reachable.append(next_station)
                    visited.add(next_station)
                    queue.append(next_station)
        
        return reachable

    def rank_routes(
        self, routes: List[Label], disability_type: str
    ) -> List[Tuple[Label, float]]:
        """
        ANP 가중치로 경로 순위 결정

        Args:
            routes (List[Label]): 파레토 최적 경로 리스트
            disability_type (str): 교통약자 유형 (PHY/VIS/AUD/ELD)

        Returns:
            List[Tuple[Label, float]]: (경로, 점수) 튜플리스트 -> 페널티 기준 오름차순 정렬
        """

        # ANP 가중치 조회
        anp_weights = self.anp_calculator.calculate_weights(disability_type)

        # 각 경로에 점수 부여
        scored_routes = []
        for route in routes:
            score = route.calculate_weighted_score(anp_weights)
            scored_routes.append((route, score))

        # 점수 오름차순 정렬
        scored_routes.sort(key=lambda x: x[1])

        return scored_routes

    def _create_new_label(
        self,
        prev_label: Label,
        from_station: str,
        to_station: str,
        line: str,  # int로 변경?? -> X, DB에서 varchar(20)임
        disability_type: str,
    ) -> Label:
        """새로운 라벨 생성"""
        # 이동 시간 계산
        # 추후 실제 역간 운행 시간 db에 추가하여 수정하기
        # MVP에서 임의로 2분으로 고정
        travel_time = 2.0

        # 보행거리 계산
        # 추후 disability_type에 따라 보행 속도를 다르게 적용시켜 시간으로 계산하기
        from_coords = self._get_station_coords(from_station)
        to_coords = self._get_station_coords(to_station)
        walking = self.distance_calc.haversine(from_coords, to_coords) * 0.1

        # 시설 가중치 적용하여 편의도 계산
        convenience = self._calculate_convenience_score(to_station, disability_type)

        # 환승 여부/횟수 확인

        # for i in range(len(prev_label.lines) - 1):
        #     if prev_label.lines[i] != prev_label.lines[i+1]:
        #         transfer_num += 1 -> 이전 환승 횟수까지 세버림

        # 마지막 역의 노선과 새로운 라벨의 출발역의 노선만 비교
        # 구조상 불가능하지만 prev_label.lines가 빈 리스트일 경우 대비
        is_transfer = (prev_label.lines[-1] != line) if prev_label.lines else False
        transfer_num = 1 if is_transfer else 0

        return Label(
            arrival_time=prev_label.arrival_time + travel_time,
            transfers=prev_label.transfers + transfer_num,  # 환승 횟수 추가
            walking_distance=prev_label.walking_distance + walking,
            convenience_score=min(prev_label.convenience_score, convenience),
            route=prev_label.route + [to_station],
            lines=prev_label.lines + [line],  # lines(리스트임)
        )  # list.append() -> return None이므로(in-place 수정 함수) append함수 쓰면 안됨

    def _get_station_coords(self, station_name: str) -> Tuple[float, float]:
        """역 좌표 조회"""
        for station in self.stations.values():
            if station["name"] == station_name:
                return (station["lat"], station["lng"])
        return (0, 0)  # 역 이름 매칭 실패

    def _calculate_convenience_score(
        self, station_name: str, disability_type: str
    ) -> float:
        """
        disability_type을 고려하여 역 편의성 점수 계산

        Args:
            station_name (str): 역 이름
            disability_type (str): 교통약자 유형

        Returns:
            float: 편의도 점수(0.0 ~ 5.0)
        """
        # 역 코드 찾기
        station_cd = None
        for station in self.stations.values():
            if station["name"] == station_name:
                station_cd = station.get("station_cd")
                break

        if not station_cd:
            return 2.5  # 정보 없음 시 중간값

        # 편의시설 점수 조회
        scores = self.convenience_scores.get(station_cd)
        if not scores:
            return 2.5  # 편의시설 정보 없음

        # 장애 유형별 시설 점수 추출
        dtype_suffix = disability_type.lower()
        facility_scores = {
            "elevator": scores.get(f"elevator_{dtype_suffix}", 0.0),
            "escalator": scores.get(f"escalator_{dtype_suffix}", 0.0),
            "transfer_walk": scores.get(f"transfer_walk_{dtype_suffix}", 0.0),
            "other_facil": scores.get(f"other_facil_{dtype_suffix}", 0.0),
            "staff_help": scores.get(f"staff_help_{dtype_suffix}", 0.0),
        }

        # ANP 시설 가중치로 종합 점수 계산
        convenience_score = self.anp_calculator.calculate_convenience_score(
            disability_type, facility_scores
        )

        return convenience_score

    def _is_pareto_optimal(
        self, new_label: Label, existing_labels: List[Label]
    ) -> bool:
        """파레토 최적성 검사"""
        for existing in existing_labels:
            if existing.dominates(new_label):
                return False
        return True

    # def _is_different_line(self, station1: str, station2: str) -> bool

    #     station1_line = None
    #     station2_line = None
    #     for station in self.stations.values():
    #         if station['name'] == station1:
    #             station1_line = station.get('line')
    #         elif station['name'] == station2:
    #             station2_line = station.get('line')

    #     return station1_line != station2_line
