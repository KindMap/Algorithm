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

        # 섹션 순서 인덱스 구축 => 방향 결정
        self.section_order_map = self._build_section_order_map()

        # 역 정보 캐시
        self.station_info_cache = {}

        # 최적화를 위해 신규 캐시 추가
        self._transfer_distance_cache = {}
        self._congestion_cache = {}
        self._convenience_cache = {}
        self._facility_scores_cache = {}
        self._line_stations_cache = {}
        self._station_order_cache = {}

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

    def _build_section_order_map(self) -> Dict:
        """section order map 구축 (from_station, to_station, line) -> section_order"""
        order_map = {}

        for section in self.sections:
            up_station = section["up_station_name"]
            down_station = section["down_station_name"]
            line = section["line"]
            order = section["section_order"]

            # 양방향 저장
            key_up_to_down = (up_station, down_station, line)
            key_down_to_up = (down_station, up_station, line)

            order_map[key_up_to_down] = order
            order_map[key_down_to_up] = order

        return order_map

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
        origin_convenience = self._calculate_convenience_score_cached(origin)

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

            # 이번 라운드에서 생성된 라벨만 탐색
            stations_to_explore = []
            for station_name, station_labels in list(labels.items()):
                if station_name not in self.graph:
                    continue

                if round_num == 0:
                    # Round 0: created_round=0인 라벨만 (초기 라벨)
                    relevant_labels = [
                        l for l in station_labels 
                        if l.created_round == 0
                    ]
                else:
                    # Round 1+: 이전 라운드에서 생성된 라벨만
                    relevant_labels = [
                        l for l in station_labels 
                        if l.created_round == round_num - 1
                    ]

                if relevant_labels:
                    stations_to_explore.append((station_name, relevant_labels))
            
            logger.info(f"탐색 대상: {len(stations_to_explore)}개 역, "
                    f"{sum(len(lbls) for _, lbls in stations_to_explore)}개 라벨")

            for station_name, station_labels in stations_to_explore:
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

                        # 목적지 방향 우선으로 역 탐색
                        reachable_stations = self._get_stations_on_line(
                            station_name, line, destination
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

    # 캐싱 적용하여 수정
    def _create_new_label(
        self,
        prev_label: Label,
        from_station: str,
        to_station: str,
        line: str,
        created_round_num: int,
    ) -> Label:
        """새로운 라벨 생성"""
        # 지하철 역간 이동 시간 (MVP: 2분 고정)
        travel_time = 2.0

        # 환승 여부 확인
        is_transfer = (prev_label.lines[-1] != line) if prev_label.lines else False

        # 환승 난이도 및 시간 계산
        transfer_difficulty_delta = 0.0
        transfer_time = 0.0

        if is_transfer:  # 환승이 발생할 때에만 계산!!!
            from_info = self._get_station_info_by_name(from_station)

            # 환승 거리 조회 <- 캐싱 적용
            transfer_distance = self._get_transfer_distance_cached(
                from_info.get("station_cd", ""),
                prev_label.lines[-1],
                line,
            )

            # 환승역 시설 점수 조회 <- 캐싱 적용
            facility_scores = self._get_facility_scores_cached(from_station)

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

        # 도착역 편의도 계산 <- 캐싱 적용
        new_convenience = self._calculate_convenience_score_cached(to_station)
        avg_convenience = (
            prev_label.convenience_score * len(prev_label.route) + new_convenience
        ) / (len(prev_label.route) + 1)

        # 현재 구간 혼잡도 계산
        to_info = self._get_station_info_by_name(to_station)
        from_info = self._get_station_info_by_name(from_station)
        direction = self._determine_direction(from_station, to_station, line)

        current_time = self.departure_time + timedelta(minutes=prev_label.arrival_time)
        # 캐싱 적용
        segment_congestion = self._get_congestion_cached(
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

    def _get_stations_on_line(
        self, start_station: str, line: str, destination: str = None
    ) -> List[str]:
        """
        특정 노선으로 갈 수 있는 역 반환(BFS)
        목적지가 있으면 section_order 기준으로 목적지 방향 우선 정렬
        """
        cache_key = (start_station, line)
        
        # 전체 역 리스트 캐싱
        if cache_key not in self._line_stations_cache:
            visited = set([start_station])
            queue = [start_station]
            all_reachable = []
            
            while queue:
                current = queue.pop(0)
                
                for neighbor in self.graph.get(current, []):
                    if neighbor["line"] == line and neighbor["to"] not in visited:
                        visited.add(neighbor["to"])
                        all_reachable.append(neighbor["to"])
                        queue.append(neighbor["to"])
            
            self._line_stations_cache[cache_key] = all_reachable
        
        all_reachable = self._line_stations_cache[cache_key]
        
        # 목적지가 주어지면 section_order를 기준으로 정렬
        if destination:
            # 시작역과 목적지 역의 order 조회
            start_order = self._get_station_order(start_station, line)
            dest_order = self._get_station_order(destination, line)
            
            if start_order is None or dest_order is None:
                # 순서 정보를 못 찾으면 기본 BFS 순서 반환
                return all_reachable
            
            # 목적지가 더 큰 order면 ascending 정렬, 작으면 descending 정렬
            ascending = dest_order > start_order
            
            # 각 역의 section_order 값 가져오기
            stations_with_order = []
            for station in all_reachable:
                order = self._get_station_order(station, line)
                if order is not None:
                    stations_with_order.append((station, order))
                else:
                    # 순서 정보 없는 역은 max값으로(뒤로 보내기)
                    stations_with_order.append((station, float('inf')))
            
            # 정렬
            stations_with_order.sort(key=lambda x: x[1], reverse=not ascending)
            
            return [s for s, _ in stations_with_order]
        
        return all_reachable

    def _get_station_info_cached(self, station_id: int) -> Dict:
        """역 정보 조회 (캐싱)"""
        if station_id not in self.station_info_cache:
            info = get_station_info(station_id)
            if info:
                self.station_info_cache[station_id] = info
            else:
                raise ValueError(f"역 정보를 찾을 수 없습니다: station_id={station_id}")

        return self.station_info_cache[station_id]

    def _get_station_info_by_name(self, station_name: str) -> Dict:
        """역 이름으로 정보 조회"""
        for station in self.stations.values():
            if station["name"] == station_name:
                return self._get_station_info_cached(station["station_id"])

        return {
            "station_cd": "",
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
    self, from_station: str, to_station: str, line: str
    ) -> str:
        """
        section_order를 이용한 방향 결정
        
        Args:
            from_station: 출발역 이름
            to_station: 도착역 이름
            line: 호선
        
        Returns:
            'up' | 'down' | 'in' | 'out'
        """
        # 1. 직접 연결 확인 (인접역)
        for section in self.sections:
            if section["line"] == line:
                if (section["up_station_name"] == from_station 
                    and section["down_station_name"] == to_station):
                    return "in" if line in CIRCULAR_LINES else "down"
                elif (section["down_station_name"] == from_station 
                    and section["up_station_name"] == to_station):
                    return "out" if line in CIRCULAR_LINES else "up"
        
        # 2. 비인접 역의 경우 section_order로 방향 추론
        from_order = self._get_station_order(from_station, line)
        to_order = self._get_station_order(to_station, line)
        
        if from_order is not None and to_order is not None:
            if to_order > from_order:
                return "in" if line in CIRCULAR_LINES else "down"
            else:
                return "out" if line in CIRCULAR_LINES else "up"
        
        # 3. 방향 결정 실패
        logger.warning(f"방향 결정 실패: {from_station} → {to_station} ({line})")
        return "up"  # 기본값

    def _is_pareto_optimal(
        self, new_label: Label, existing_labels: List[Label]
    ) -> bool:
        """파레토 최적성 검사"""
        for existing in existing_labels:
            if existing.dominates(new_label):
                return False
        return True

    # 최적화를 위한 캐싱 메서드 추가
    def _get_transfer_distance_cached(
        self, station_cd: str, from_line: str, to_line: str
    ) -> float:
        """환승 거리 조회 (캐싱)"""
        cache_key = (station_cd, from_line, to_line)

        if cache_key not in self._transfer_distance_cache:
            distance = get_transfer_distance(station_cd, from_line, to_line)
            self._transfer_distance_cache[cache_key] = distance
            logger.debug(
                f"캐시 미스: 환승거리 {station_cd} {from_line}→{to_line} = {distance}m"
            )
        else:
            logger.debug(f"캐시 히트: 환승거리 {cache_key}")

        return self._transfer_distance_cache[cache_key]

    def _get_congestion_cached(
        self, station_cd: str, line: str, direction: str, current_time: datetime
    ) -> float:
        """혼잡도 조회 (캐싱) - 시간은 시간대로만 캐싱"""
        # 분 단위 무시하고 시간대만 사용 -> 캐싱 성능을 확인하면서 추후 조정하기
        time_key = current_time.replace(minute=0, second=0, microsecond=0)
        cache_key = (station_cd, line, direction, time_key)

        if cache_key not in self._congestion_cache:
            congestion = self.anp_calculator.get_congestion_from_rds(
                station_cd, line, direction, current_time
            )
            self._congestion_cache[cache_key] = congestion
            logger.debug(
                f"캐시 미스: 혼잡도 {station_cd} {line} {direction} = {congestion}"
            )
        else:
            logger.debug(f"캐시 히트: 혼잡도 {cache_key}")

        return self._congestion_cache[cache_key]

    def _get_facility_scores_cached(self, station_name: str) -> Dict[str, float]:
        """역의 시설별 편의도 점수 조회 (캐싱)"""
        cache_key = (station_name, self.disability_type)

        if cache_key not in self._facility_scores_cache:
            scores = self._get_facility_scores(station_name)  # 기존 메서드 호출
            self._facility_scores_cache[cache_key] = scores
            logger.debug(f"캐시 미스: 편의시설 {station_name}")
        else:
            logger.debug(f"캐시 히트: 편의시설 {cache_key}")

        return self._facility_scores_cache[cache_key]

    def _calculate_convenience_score_cached(self, station_name: str) -> float:
        """역 편의성 점수 계산 (캐싱)"""
        cache_key = (station_name, self.disability_type)

        if cache_key not in self._convenience_cache:
            facility_scores = self._get_facility_scores_cached(station_name)

            if not facility_scores:
                score = 2.5  # 기본값
            else:
                score = self.anp_calculator.calculate_convenience_score(
                    self.disability_type, facility_scores
                )

            self._convenience_cache[cache_key] = score
            logger.debug(f"캐시 미스: 편의도 {station_name} = {score}")
        else:
            logger.debug(f"캐시 히트: 편의도 {cache_key}")

        return self._convenience_cache[cache_key]
    
    def _get_station_order(self, station_name: str, line: str) -> Optional[int]:
        """역의 section_order 조회 (캐싱)"""
        cache_key = (station_name, line)
        
        if cache_key in self._station_order_cache:
            return self._station_order_cache[cache_key]
        
        for section in self.sections:
            if section["line"] == line:
                if section["up_station_name"] == station_name:
                    order = section["section_order"]
                    self._station_order_cache[cache_key] = order
                    return order
                elif section["down_station_name"] == station_name:
                    # down_station의 order는 section_order보다 1 큼
                    order = section["section_order"] + 1
                    self._station_order_cache[cache_key] = order
                    return order
        
        return None
    

