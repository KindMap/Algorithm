from typing import List, Dict, Set, Tuple, Optional
from collections import defaultdict
from datetime import datetime, timedelta
import logging

from label import Label
from anp_weights import ANPWeightCalculator
from database import get_transfer_distance # get_station_info 직접 사용하지 않도록 수정
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
        # station_cd -> db 전체에 존재 + unique => 내부 연산을 station_cd로 수행하도록 수정
        # station_cd를 키로 하는 역 정보 맵
        self.stations: Dict[str, Dict] = {s["station_cd"]: s for s in stations}
        self.sections = sections
        self.convenience_scores = {c["station_cd"]: c for c in convenience_scores}
        # ANP 계산기
        self.anp_calculator = anp_calculator or ANPWeightCalculator()

        # 초기화 성능 최적화
        # 그래프 구성에 사용할 사전 연산 맵
        # (name,line) -> station_cd 맵
        self.name_line_to_cd: Dict[Tuple[str,str], str] = {
            (s["name"], s["line"]): s["station_cd"] for s in self.stations.values()
        }
        # (name) -> [station_cd list] map
        self.station_name_to_cds: Dict[str, List[str]] = defaultdict(list)
        for s in self.stations.values():
            self.station_name_to_cds[s["name"]].append(s["station_cd"]) 

        # 역 연결 그래프 구축 <- 사전 연산 맵 사용
        self.graph = self._build_graph()

        # 섹션 순서 인덱스 구축 => 방향 결정 <- 사전 연산 맵 사용
        self.section_order_map = self._build_section_order_map()

        # station_cd, line -> 인접 역에 대해 방향 역 리스트 맵
        self.line_stations_map = self._build_line_stations_map()
        logger.info(f"McRaptor: 방향성 노선 맵 {len(self.line_stations_map)} 개 구축 완료")

        # 최적화를 위해 신규 캐시 추가
        self._transfer_distance_cache = {}
        self._congestion_cache = {}
        self._convenience_cache = {}
        self._facility_scores_cache = {}

        # 현재 탐색 중인 장애 유형 및 출발 시각
        self.disability_type = None
        self.departure_time = None

    def _build_graph(self) -> Dict:
        """역 연결 그래프 구축 <- 사전 연산 맵 활용하여 초기화 성능 향상"""
        graph = defaultdict(list)

        for section in self.sections:
            line = section["line"]
            up_name = section["up_station_name"]
            down_name = section["down_station_name"]

            # 순회하는 대신 사전 연산 맵에서 바로 조회
            up_cd = self.name_line_to_cd.get((up_name, line))
            down_cd = self.name_line_to_cd.get((down_name, line))

            if not up_cd or not down_cd:
                logger.warning(f"graph build: {section["section_id"]}의 역 code 없음: {up_name}, {down_name}")
                continue

            graph[up_cd].append({"to": down_cd, "line": line, "order": section["section_order"]})
            graph[down_cd].append({"to": up_cd, "line": line, "order": section["section_order"]})

        return graph

    def _build_station_order_map(self) -> Dict:
        """station order map 구축 (from_station, to_station, line) -> section_order"""
        order_map = {}
        for section in self.sections:
            line = section["line"]

            # 순회 대신 사전 연산 맵에서 바로 조회
            up_cd = self.name_line_to_cd((section["up_station_name"], line))
            down_cd = self.name_line_to_cd((section["down_station_name"], line))

            if not up_cd or not down_cd:
                continue

            order = section["section_order"]
            order_map[(up_cd, line)] = order
            order_map[(down_cd, line)] = order + 1

        return order_map
    
    # station_cd가 방향과 관련이 있는 것이 맞는지 확인하기
    def _build_line_stations_map(self) -> Dict[Tuple[str, str], Dict[str, List[str]]]:
        """
        (station_cd, line) -> {'up': [...], 'down': [...], 'in': [...], 'out': [...]}
        방향성을 고려하여 각 station_cd, line별 인접 역 리스트 저장
        """
        # line -> station_cd 순서 정렬 사전 생성
        line_to_stations_ordered: Dict[str, List[str]] = defaultdict(list)
        # (line) -> {station_cd: order} 맵 임시 저장
        line_station_orders: Dict[str, Dict[str, int]] = defaultdict(dict)
        for (station_cd, line), order in self.station_order_map.items():
            line_station_orders[line][station_cd] = order
        
        for line, stations_orders in line_station_orders.items():
            # order(x[1]) 기준으로 정렬
            sorted_stations = sorted(stations_orders.items(), key=lambda x: x[1])
            # station_cd(st[0])만 리스트로 저장
            line_to_stations_ordered[line] = [st[0] for st in sorted_stations]

        line_map = {}
        for line, ordered_stations in line_to_stations_ordered.items():
            for i, station_cd in enumerate(ordered_stations):
                up_stations = ordered_stations[:i][::-1]  # 0부터 i-1까지 (역순)
                down_stations = ordered_stations[i+1:]  # i+1부터 끝까지

                is_circular = line in CIRCULAR_LINES
                line_map[(station_cd, line)] = {
                    "up": up_stations,
                    "down": down_stations,
                    "in": down_stations if is_circular else [], # 순환선 'in'을 'down'으로 매핑
                    "out": up_stations if is_circular else [], # 순환선 'out'을 'up'으로 매핑
                }
        return line_map

    def find_routes(
        self,
        origin: str,
        destination: str,
        departure_time: datetime,
        disability_type: str,
        max_rounds: int = 4,
    ) -> List[Label]:
        """
        Mc-RAPTOR 알고리즘(Marking 기법, station_cd 활용)
        최적화 적용

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

        # 순회 대신 맵 조회
        origin_cds = self.station_name_to_cds.get(origin, [])
        destination_cds = self.station_name_to_cds.get(destination, [])

        if not origin_cds:
            raise ValueError(f"출발역 {origin}을 찾을 수 없습니다.")
        if not destination_cds:
            raise ValueError(f"도착역 {destination}을 찾을 수 없습니다.")
        destination_cd_set = set(destination_cds)

        # Marking 기법 적용
        Q = set()

        # 초기 라벨 생성
        for origin_cd in origin_cds:
            origin_info = self.get_station_info_from_cd(origin_cd)
            if not origin_info:
                continue
            origin_line = origin_info.get("line")

            # 초기 혼잡도 (메모리 캐시 조회)
            initial_congestion = self._get_congestion_cached(origin_cd, origin_line, "up", departure_time)
            origin_convenience = self._calculate_convenience_score_cached(origin_cd)

            initial_label = Label(
                arrival_time=0.0,
                transfers=0,
                transfer_difficulty=0.0,
                convenience_score=origin_convenience,
                congestion_score=initial_congestion,
                route=[origin_cd],
                lines=[origin_line],
                created_round=0,
            )
            labels[origin_cd].append(initial_label)
            
            # 출발역 마킹
            Q.add(origin_cd)

        # Round별 탐색
        for round_num in range(1, max_rounds + 1):
            logger.info(f"=== Round {round_num}: 마킹 {len(Q)}개 시작 ===")
            Q_next_round = set()

            # Marking된 역만 탐색
            for station_cd in Q:
                station_labels = labels[station_cd]
                # 이전 라운드까지 생성된 라벨만 탐색
                to_explore_labels = [l for l in station_labels if l.created_round < round_num]
                if not to_explore_labels:
                    continue

                for label in to_explore_labels:
                    current_line = label.lines[-1] if label.lines else None

                    # 현재 역에서 이용 가능한 모든 호선
                    available_lines = {neighbor["line"] for neighbor in self.graph.get(station_cd, [])}

                    for line in available_lines:
                        is_transfer = (line != current_line)
                        # 환승 횟수 제한
                        if label.transfers + (1 if is_transfer else 0) > round_num:
                            continue

                        # 방향별 역 리스트 가져오기
                        directions_map = self._get_stations_on_line(station_cd, line)

                        directions_to_explore = []
                        if line in CIRCULAR_LINES:
                            directions_to_explore.extend(directions_map.get("in", []))
                            directions_to_explore.extend(directions_map.get("out", []))
                        else:
                            directions_to_explore.extend(directions_map.get("up", []))
                            directions_to_explore.extend(directions_map.get("down", []))

                        # 양방향 탐색 버그 수정
                        for next_station_cd in directions_to_explore:
                            new_label = self._create_new_label(
                                label, station_cd, next_station_cd, line, round_num
                            )

                            existing_labels = labels[next_station_cd]
                            new_frontier, updated = self._update_pareto_frontier(new_label, existing_labels)

                            if updated:
                                labels[next_station_cd] = new_frontier
                                # 새로운 라벨이 추가될 때에만 마킹
                                Q_next_round.add(next_station_cd)

            if not Q_next_round:
                logger.info(f"No updates in round {round_num}, early termination")
                break
            Q = Q_next_round # 다음 라운드 대상 갱신
        
        final_routes = []
        for dest_cd in destination_cd_set:
            final_routes.extend(labels.get(dest_cd, []))
        return list(set(final_routes))

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

        # 점수가 낮을수록 좋음 -> 오름차순 정렬
        scored_routes.sort(key=lambda x: x[1])

        return scored_routes

    # 캐싱 적용하여 수정
    def _create_new_label(
        self,
        prev_label: Label,
        from_station_cd: str,
        to_station_cd: str,
        line: str,
        created_round_num: int,
    ) -> Label:
        """새로운 라벨 생성"""
        # 지하철 역간 이동 시간 (MVP: 2분 고정)
        travel_time = 2.0

        # 환승 여부 확인
        is_transfer = (prev_label.lines[-1] != line) if prev_label.lines else False

        transfer_difficulty_delta = 0.0
        transfer_time = 0.0

        if is_transfer:  # 환승이 발생할 때에만 계산!!!
            # 환승 거리 조회 <- 캐싱 적용
            transfer_distance = self._get_transfer_distance_cached(from_station_cd, prev_label.lines[-1], line)

            # 환승역 시설 점수 조회 <- 캐싱 적용
            facility_scores = self._get_facility_scores_cached(from_station_cd)

            # 환승 난이도 계산
            transfer_difficulty_delta = (
                self.anp_calculator.calculate_transfer_difficulty(
                    transfer_distance, facility_scores, self.disability_type
                )
            )

            # 환승 보행시간 계산 초->분
            transfer_time = self.anp_calculator.calculate_transfer_walking_time(
                transfer_distance, self.disability_type
            ) / 60.0

            # logger.debug(
            #     f"환승: {from_station}({prev_label.lines[-1]}→{line}) "
            #     f"거리={transfer_distance:.1f}m, "
            #     f"난이도={transfer_difficulty_delta:.3f}, "
            #     f"시간={transfer_time:.1f}초"
            # )

        # 도착역 편의도 계산 <- 캐싱 적용
        new_convenience = self._calculate_convenience_score_cached(to_station_cd)
        avg_convenience = (
            prev_label.convenience_score * len(prev_label.route) + new_convenience
        ) / (len(prev_label.route) + 1)

        direction = self._determine_direction(from_station_cd, to_station_cd, line)
        current_time = self.departure_time + timedelta(minutes=prev_label.arrival_time)

        # 메모리 캐시를 조회하는 _get_congestion_cached 호출
        segment_congestion = self._get_congestion_cached(to_station_cd, line, direction, current_time)
        avg_congestion = (
            prev_label.congestion_score * len(prev_label.route) + segment_congestion
        ) / (len(prev_label.route) + 1)

        new_transfer_stations = prev_label.transfer_stations.copy()
        if is_transfer:
            new_transfer_stations.add(from_station_cd)

        return Label(
            arrival_time=prev_label.arrival_time + travel_time + transfer_time,
            transfers=prev_label.transfers + (1 if is_transfer else 0),
            transfer_difficulty=prev_label.transfer_difficulty + transfer_difficulty_delta,
            convenience_score=avg_convenience,
            congestion_score=avg_congestion,
            route=prev_label.route + [to_station_cd],
            lines=prev_label.lines + [line],
            transfer_stations=new_transfer_stations,
            created_round=created_round_num,
        )

    def _get_stations_on_line(
        self, station_cd:str, line:str
    ) -> Dict[str, List[str]]:
        """사전 생성한 맵 조회로 변경"""
        return self.line_stations_map.get((station_cd, line), {})
        

    def _get_transfer_distance_cached(self, station_cd: str, from_line:str, to_line: str) -> float:
        """환승 거리 조회 <- 요청별 캐싱"""
        cache_key = (station_cd, from_line, to_line)
        if cache_key not in self._transfer_distance_cache:
            self._transfer_distance_cache[cache_key] = get_transfer_distance(station_cd, from_line, to_line)
        return self._transfer_distance_cache[cache_key]
    
    def _get_congestion_cached(self, station_cd: str, line: str, direction: str, current_time: datetime) -> float:
        """ 혼잡도 조회 <- 요청별 캐싱 """
        # 캐시 키를 30분 단위로 통일
        time_key = current_time.replace(minute=(current_time.minute // 30) * 30, second=0, microsecond=0)
        cache_key = (station_cd, line, direction, time_key)
        
        if cache_key not in self._congestion_cache:
            # ANP 계산기에 내장된 사전 적재한 메모리 캐시를 조회
            self._congestion_cache[cache_key] = self.anp_calculator.get_congestion_from_rds(
                station_cd, line, direction, current_time
            )
        return self._congestion_cache[cache_key]
    
    def _get_facility_scores_cached(self, station_cd: str) -> Dict[str, float]:
        """ 편의시설 점수 조회 <- 요청별 캐싱 """
        cache_key = (station_cd, self.disability_type)
        if cache_key not in self._facility_scores_cache:
            self._facility_scores_cache[cache_key] = self._get_facility_scores(station_cd)
        return self._facility_scores_cache[cache_key]

    def _get_facility_scores(self, station_cd: str) -> Dict[str, float]:
        """ 편의시설 점수 계산 (self.convenience_scores 조회) """
        scores = self.convenience_scores.get(station_cd, {})
        if not scores:
            return {}
        dtype_suffix = self.disability_type.lower()
        return {
            "elevator": scores.get(f"elevator_{dtype_suffix}", 0.0),
            "escalator": scores.get(f"escalator_{dtype_suffix}", 0.0),
            "transfer_walk": scores.get(f"transfer_walk_{dtype_suffix}", 0.0),
            "other_facil": scores.get(f"other_facil_{dtype_suffix}", 0.0),
            "staff_help": scores.get(f"staff_help_{dtype_suffix}", 0.0),
        }

    def _calculate_convenience_score_cached(self, station_cd: str) -> float:
        """ 편의도 점수 계산 <- 요청별 캐싱 """
        cache_key = (station_cd, self.disability_type)
        if cache_key not in self._convenience_cache:
            facility_scores = self._get_facility_scores_cached(station_cd)
            score = 2.5  # 기본값
            if facility_scores:
                score = self.anp_calculator.calculate_convenience_score(self.disability_type, facility_scores)
            self._convenience_cache[cache_key] = score
        return self._convenience_cache[cache_key]

    def _determine_direction(
    self, from_station: str, to_station: str, line: str
    ) -> str:
        """
        section_order를 이용한 방향 결정 <- 맵 조회 최적화 적용
        
        Args:
            from_station: 출발역 이름
            to_station: 도착역 이름
            line: 호선
        
        Returns:
            'up' | 'down' | 'in' | 'out'
        """
        from_order = self.station_order_map.get((from_station_cd, line))
        to_order = self.station_order_map.get((to_station_cd, line))

        if from_order is not None and to_order is not None:
            if line in CIRCULAR_LINES:
                # 'in'/'out' 구분 (순환선 로직)
                return "in" if to_order > from_order else "out"
            else:
                # 'up'/'down' 구분
                return "down" if to_order > from_order else "up"

        # logger.warning(f"방향 결정 실패: {from_station_cd} -> {to_station_cd} ({line})")
        return "up" # 기본값
    
    def _update_pareto_frontier(self, new_label: Label, existing_labels: List[Label]) -> Tuple[List[Label], bool]:
        """ 파레토 프론티어 단일 패스 갱신 """
        new_frontier = []
        is_dominated_by_existing = False
        was_updated = False # 프론티어 변경 여부

        for existing in existing_labels:
            if existing.dominates(new_label):
                # 기존 라벨이 새 라벨을 지배 -> 새 라벨 추가 안함
                is_dominated_by_existing = True
                new_frontier.append(existing)
            elif new_label.dominates(existing):
                # 새 라벨이 기존 라벨을 지배 -> 기존 라벨 제거
                was_updated = True
                continue # 기존 라벨을 new_frontier에 추가하지 않음
            else:
                # 지배 관계 아님 -> 둘 다 유지
                new_frontier.append(existing)

        if not is_dominated_by_existing:
            # 새 라벨이 지배당하지 않음 -> 프론티어에 추가
            new_frontier.append(new_label)
            was_updated = True

        return new_frontier, was_updated

    # def _is_pareto_optimal(
    #     self, new_label: Label, existing_labels: List[Label]
    # ) -> bool:
    #     """파레토 최적성 검사"""
    #     for existing in existing_labels:
    #         if existing.dominates(new_label):
    #             return False
    #     return True

    # 최적화를 위한 캐싱 메서드 추가
    # def _get_transfer_distance_cached(
    #     self, station_cd: str, from_line: str, to_line: str
    # ) -> float:
    #     """환승 거리 조회 (캐싱)"""
    #     cache_key = (station_cd, from_line, to_line)

    #     if cache_key not in self._transfer_distance_cache:
    #         distance = get_transfer_distance(station_cd, from_line, to_line)
    #         self._transfer_distance_cache[cache_key] = distance
    #         logger.debug(
    #             f"캐시 미스: 환승거리 {station_cd} {from_line}→{to_line} = {distance}m"
    #         )
    #     else:
    #         logger.debug(f"캐시 히트: 환승거리 {cache_key}")

    #     return self._transfer_distance_cache[cache_key]

    # def _get_congestion_cached(
    #     self, station_cd: str, line: str, direction: str, current_time: datetime
    # ) -> float:
    #     """혼잡도 조회 (캐싱) - 시간은 시간대로만 캐싱"""
    #     # 분 단위 무시하고 시간대만 사용 -> 캐싱 성능을 확인하면서 추후 조정하기
    #     time_key = current_time.replace(minute=0, second=0, microsecond=0)
    #     cache_key = (station_cd, line, direction, time_key)

    #     if cache_key not in self._congestion_cache:
    #         congestion = self.anp_calculator.get_congestion_from_rds(
    #             station_cd, line, direction, current_time
    #         )
    #         self._congestion_cache[cache_key] = congestion
    #         logger.debug(
    #             f"캐시 미스: 혼잡도 {station_cd} {line} {direction} = {congestion}"
    #         )
    #     else:
    #         logger.debug(f"캐시 히트: 혼잡도 {cache_key}")

    #     return self._congestion_cache[cache_key]

    # def _get_facility_scores_cached(self, station_name: str) -> Dict[str, float]:
    #     """역의 시설별 편의도 점수 조회 (캐싱)"""
    #     cache_key = (station_name, self.disability_type)

    #     if cache_key not in self._facility_scores_cache:
    #         scores = self._get_facility_scores(station_name)  # 기존 메서드 호출
    #         self._facility_scores_cache[cache_key] = scores
    #         logger.debug(f"캐시 미스: 편의시설 {station_name}")
    #     else:
    #         logger.debug(f"캐시 히트: 편의시설 {cache_key}")

    #     return self._facility_scores_cache[cache_key]

    # def _calculate_convenience_score_cached(self, station_name: str) -> float:
    #     """역 편의성 점수 계산 (캐싱)"""
    #     cache_key = (station_name, self.disability_type)

    #     if cache_key not in self._convenience_cache:
    #         facility_scores = self._get_facility_scores_cached(station_name)

    #         if not facility_scores:
    #             score = 2.5  # 기본값
    #         else:
    #             score = self.anp_calculator.calculate_convenience_score(
    #                 self.disability_type, facility_scores
    #             )

    #         self._convenience_cache[cache_key] = score
    #         logger.debug(f"캐시 미스: 편의도 {station_name} = {score}")
    #     else:
    #         logger.debug(f"캐시 히트: 편의도 {cache_key}")

    #     return self._convenience_cache[cache_key]
    
    # def _get_station_order(self, station_name: str, line: str) -> Optional[int]:
    #     """역의 section_order 조회 (캐싱)"""
    #     cache_key = (station_name, line)
        
    #     if cache_key in self._station_order_cache:
    #         return self._station_order_cache[cache_key]
        
    #     for section in self.sections:
    #         if section["line"] == line:
    #             if section["up_station_name"] == station_name:
    #                 order = section["section_order"]
    #                 self._station_order_cache[cache_key] = order
    #                 return order
    #             elif section["down_station_name"] == station_name:
    #                 # down_station의 order는 section_order보다 1 큼
    #                 order = section["section_order"] + 1
    #                 self._station_order_cache[cache_key] = order
    #                 return order
        
    #     return None
    

