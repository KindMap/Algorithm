from typing import List, Dict, Set, Tuple, Optional
from collections import defaultdict
from datetime import datetime, timedelta
import logging

from label import Label
from anp_weights import ANPWeightCalculator
from database import get_transfer_distance  # get_station_info 직접 사용하지 않도록 수정
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
        self.name_line_to_cd: Dict[Tuple[str, str], str] = {
            (s["name"], s["line"]): s["station_cd"] for s in self.stations.values()
        }
        # (name) -> [station_cd list] map
        self.station_name_to_cds: Dict[str, List[str]] = defaultdict(list)
        for s in self.stations.values():
            self.station_name_to_cds[s["name"]].append(s["station_cd"])

        # 역 연결 그래프 구축 <- 사전 연산 맵 사용
        self.graph = self._build_graph()

        # 섹션 순서 인덱스 구축 => 방향 결정 <- 사전 연산 맵 사용
        self.station_order_map = self._build_station_order_map()

        # station_cd, line -> 인접 역에 대해 방향 역 리스트 맵
        self.line_stations_map = self._build_line_stations_map()
        logger.info(
            f"McRaptor: 방향성 노선 맵 {len(self.line_stations_map)} 개 구축 완료"
        )

        # 최적화를 위해 신규 캐시 추가
        self._transfer_distance_cache = {}
        # self._congestion_cache = {} <- 요청별 캐싱과 중복되므로 삭제
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
                section_id = section["section_id"]
                logger.warning(
                    f"graph build: {section_id}의 역 code 없음: {up_name}, {down_name}"
                )
                continue

            graph[up_cd].append(
                {"to": down_cd, "line": line, "order": section["section_order"]}
            )
            graph[down_cd].append(
                {"to": up_cd, "line": line, "order": section["section_order"]}
            )

        return graph

    def _build_station_order_map(self) -> Dict:
        """station order map 구축 (from_station, to_station, line) -> section_order"""
        order_map = {}
        for section in self.sections:
            line = section["line"]

            # 순회 대신 사전 연산 맵에서 바로 조회
            up_cd = self.name_line_to_cd.get((section["up_station_name"], line))
            down_cd = self.name_line_to_cd.get((section["down_station_name"], line))

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
                down_stations = ordered_stations[i + 1 :]  # i+1부터 끝까지

                is_circular = line in CIRCULAR_LINES
                line_map[(station_cd, line)] = {
                    "up": up_stations,
                    "down": down_stations,
                    "in": (
                        down_stations if is_circular else []
                    ),  # 순환선 'in'을 'down'으로 매핑
                    "out": (
                        up_stations if is_circular else []
                    ),  # 순환선 'out'을 'up'으로 매핑
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

        # 메모리 누수 방지를 위해 요청별 캐시 초기화 <- 운영 상황에서 중요한 문제
        # 무작정 쌓이면 안됨
        self._transfer_distance_cache.clear()
        self._convenience_cache.clear()
        self._facility_scores_cache.clear()

        # 파레토 프론티어
        labels = defaultdict(list)

        # 순회 대신 맵 조회
        origin_cds = self.station_name_to_cds.get(origin, [])
        destination_cds = self.station_name_to_cds.get(destination, [])

        # # 출발/도착역 확인 로그 추가
        # logger.info(f"출발역: {origin} -> 코드: {origin_cds}")
        # logger.info(f"도착역: {destination} -> 코드: {destination_cds}")
        # logger.info(
        #     f"출발역 그래프 연결: {[len(self.graph.get(cd, [])) for cd in origin_cds]}"
        # )

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
            initial_congestion = self.anp_calculator.get_congestion_from_rds(
                origin_cd, origin_line, "up", departure_time
            )
            origin_convenience = self._calculate_convenience_score_cached(origin_cd)

            initial_label = Label(
                arrival_time=0.0,
                transfers=0,
                # transfer_difficulty=0.0,
                # convenience_score=origin_convenience,
                # congestion_score=initial_congestion,
                # !!! 수정 누적합(평균), 리스트(최악) 사용 !!!
                transfer_difficulty_list=[],
                congestion_sum=initial_congestion,
                convenience_sum=origin_convenience,
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
            logger.info(f"현재 전체 라벨 수: {sum(len(v) for v in labels.values())}개")
            Q_next_round = set()

            # Marking된 역만 탐색
            for station_cd in Q:
                station_labels = labels[station_cd]
                # 이전 라운드까지 생성된 라벨만 탐색
                to_explore_labels = [
                    l for l in station_labels if l.created_round < round_num
                ]
                if not to_explore_labels:
                    continue

                logger.debug(f"역 {station_cd}: 탐색 라벨 {len(to_explore_labels)}개")

                for label in to_explore_labels:
                    current_line = label.lines[-1] if label.lines else None

                    # 환승 로직 수정
                    # 현재 station_cd의 이름 찾기
                    current_station_name = self.get_station_name_from_cd(station_cd)

                    # 해당 이름을 갖고 있는 모든 station_cd 찾음 => 같은 역이라도 노선이 다르면 station_cd가 다름
                    all_cds_at_station = self.station_name_to_cds.get(
                        current_station_name, []
                    )

                    # 위에서 찾은 모든 station_cd를 활용해 노선 정보 생성
                    available_lines_info = {
                        self.get_station_info_from_cd(cd).get("line"): cd
                        for cd in all_cds_at_station
                        if self.get_station_info_from_cd(cd)  # 방어 코드
                    }

                    if not available_lines_info:
                        logger.debug(f"역 {station_cd}: 이용 가능한 호선 없음")
                        continue

                    # 수정된 맵 순환 => 양방향을 동시에 탐색 => 심각한 논리적 오류
                    # 양방향 탐색 오류 수정
                    for line, line_start_cd in available_lines_info.items():
                        is_transfer = line != current_line
                        # 환승 횟수 제한
                        if label.transfers + (1 if is_transfer else 0) > round_num:
                            continue

                        # 현재 병렬로 탐색되는 환승/직진 로직을 분리
                        if is_transfer:
                            # 환승 로직!!! => 직전 역은 현재 역
                            new_label = self._create_new_label(
                                label,
                                line_start_cd,
                                station_cd,
                                line_start_cd,
                                line,
                                round_num,
                                0.0,  # 같은 역에서 환승 -> 지하철로 인한 이동 시간은 0 -> 추후 환승 거리를 통해 보행 시간이 계산됨
                            )

                            existing_labels = labels[line_start_cd]
                            new_frontier, updated = self._update_pareto_frontier(
                                new_label, existing_labels
                            )

                            if updated:
                                labels[line_start_cd] = new_frontier
                                # 환승한 노선의 탐색은 다음 라운드에서 진행돼야 하므로
                                # 환승 노드만!!! 마킹
                                Q_next_round.add(line_start_cd)
                        else:
                            # 환승이 아닐 경우 현재 라벨의 방향을 판별
                            # 직진 로직!!!
                            directions_map = self._get_stations_on_line(
                                line_start_cd, line
                            )

                            # U턴 방지 방향 설정
                            direction_keys = []

                            # 환승 직후일 경우 => 양방향 탐색 가능해야 함
                            is_just_transferred = False
                            if len(label.route) >= 2:
                                # lines 리스트는 route와 길이가 같을 것이므로
                                if (
                                    len(label.lines) >= 2
                                    and label.lines[-1] != label.lines[-2]
                                ):
                                    is_just_transferred = True

                            if len(label.route) < 2 or is_just_transferred:
                                # 출발역 또는 환승 직후인 경우
                                # 양방향 탐색 허용
                                direction_keys = (
                                    ["up", "down"]
                                    if line not in CIRCULAR_LINES
                                    else ["in", "out"]
                                )
                            else:
                                # 직전 역과 현재 역으로 방향을 결정
                                from_cd = label.route[-2]
                                to_cd = label.route[-1]
                                current_direction = self._determine_direction(
                                    from_cd, to_cd, line
                                )
                                direction_keys = [current_direction]

                        # 상반되는 방향을 별도로 순회
                        for direction in direction_keys:
                            # 해당 방향의 역 리스트만 가져옴 => 합치지 않도록 주의!
                            directions_to_explore = directions_map.get(direction, [])

                            # # 순차적으로 탐색 진행 => 순차 탐색 폐기
                            # 병렬 누적 시간 방식 사용
                            cumulative_travel_time = 0.0

                            # 직전 역 station_cd 추적 <- 방향 결정
                            previous_station_cd = station_cd  # line_start_cd == station_cd <- 직진 로직이므로

                            # 해당 단일 방향으로만
                            for next_station_cd in directions_to_explore:
                                # 중요!!!
                                # U턴 및 무한 루프 방지 로직 추가
                                # 생성할 라벨의 다음 역이 이전 경로에 이미 포함되어 있다면 건너뜀
                                if next_station_cd in label.route:
                                    continue

                                segment_travel_time = (
                                    2.0  # MVP 버전 임시 역간 이동 시간 2.0
                                )
                                cumulative_travel_time += segment_travel_time

                                # !!!!!!!병렬 전파 적용!!!!!!!
                                # 모든 라벨은 탑승 라벨을 기준으로 병렬 생성
                                new_label = self._create_new_label(
                                    label,  # 탑승 라벨 <- 기준점
                                    station_cd,  # 탐승한 역 <- 환승 계산
                                    previous_station_cd,  # 직전 역 <- 방향 계산
                                    next_station_cd,  # 도착할 역
                                    line,
                                    round_num,
                                    cumulative_travel_time,  # 누적 시간
                                )

                                existing_labels = labels[next_station_cd]
                                new_frontier, updated = self._update_pareto_frontier(
                                    new_label, existing_labels
                                )

                                if updated:
                                    labels[next_station_cd] = new_frontier
                                    # 새로운 라벨이 추가될 때에만 마킹
                                    Q_next_round.add(next_station_cd)

            if not Q_next_round:
                logger.info(f"No updates in round {round_num}, early termination")
                break
            Q = Q_next_round  # 다음 라운드 대상 갱신

        # 목적지가 포함된 라벨만 집계
        candidates = []
        for dest_cd in destination_cd_set:
            candidates.extend(
                [label for label in labels.get(dest_cd, []) if dest_cd in label.route]
            )
        # 목적지에서 종료하는 라벨만 취합
        final_routes = []
        final_routes = [
            label for label in candidates if label.route[-1] in destination_cd_set
        ]
        logger.info(f"최종 경로 수: {len(final_routes)}개")
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
    # !!! 병렬 시간 누적 적용을 위한 수정 적용 !!!
    def _create_new_label(
        self,
        prev_label: Label,  # 탑승 시점의 라벨
        from_station_cd: str,  # 탑승한 역 -> 환승 계산용
        prev_stop_cd: str,  # 직전 역 -> 방향 계산용
        to_station_cd: str,  # 도착할 역
        line: str,
        created_round_num: int,
        cumulative_travel_time: float,  # 누적 시간 인자 추가
    ) -> Label:
        """새로운 라벨 생성 <- 누적합 적용!!!"""

        # 환승 여부 확인
        is_transfer = (prev_label.lines[-1] != line) if prev_label.lines else False

        transfer_difficulty_delta = 0.0
        transfer_time = 0.0

        if is_transfer:  # 환승이 발생할 때에만 계산!!!
            # from_station_cd 기준으로 환승 계산!!!
            # transfer_context 저장을 위해 from_line, to_line 변수화
            from_line = prev_label.lines[-1]
            to_line = line

            # 환승 거리 조회 <- 캐싱 적용
            transfer_distance = self._get_transfer_distance_cached(
                from_station_cd, from_line, to_line  # 탑승역 기준
            )

            # 환승역 시설 점수 조회 <- 캐싱 적용
            facility_scores = self._get_facility_scores_cached(from_station_cd)

            # 환승 난이도 계산 -> 추후 새로운 라벨의 환승 난이도 리스트에 추가
            transfer_difficulty_delta = (
                self.anp_calculator.calculate_transfer_difficulty(
                    transfer_distance, facility_scores, self.disability_type
                )
            )

            # 환승 보행시간 계산 초->분
            transfer_time = (
                self.anp_calculator.calculate_transfer_walking_time(
                    transfer_distance, self.disability_type
                )
                / 60.0
            )

            # logger.debug(
            #     f"환승: {from_station}({prev_label.lines[-1]}→{line}) "
            #     f"거리={transfer_distance:.1f}m, "
            #     f"난이도={transfer_difficulty_delta:.3f}, "
            #     f"시간={transfer_time:.1f}초"
            # )

        # 누적합 계산 로직으로 변경
        # 도착역의 개별 편의도 점수
        new_convenience = self._calculate_convenience_score_cached(to_station_cd)
        # 위의 것을 합산한 새로운 편의도 누적합
        new_convenience_sum = prev_label.convenience_sum + new_convenience

        # 도착역 개별 혼잡도
        direction = self._determine_direction(prev_stop_cd, to_station_cd, line)
        current_time = self.departure_time + timedelta(minutes=prev_label.arrival_time)
        segment_congestion = self.anp_calculator.get_congestion_from_rds(
            to_station_cd, line, direction, current_time
        )

        # 새로운 혼잡도 누적합
        new_congestion_sum = prev_label.congestion_sum + segment_congestion

        # 환승 난이도 역시 새로운 환승역의 난이도를 리스트 복사 후 추가
        new_transfer_difficulty_list = prev_label.transfer_difficulty_list.copy()
        if is_transfer:
            new_transfer_difficulty_list.append(transfer_difficulty_delta)

        # transfer_context 리스트를 복사하고 새로운 환승 정보 추가
        new_transfer_context = prev_label.transfer_context.copy()
        if is_transfer:
            new_transfer_context.append((from_station_cd, from_line, to_line))

        return Label(
            arrival_time=prev_label.arrival_time
            + cumulative_travel_time
            + transfer_time,
            transfers=prev_label.transfers + (1 if is_transfer else 0),
            transfer_difficulty_list=new_transfer_difficulty_list,
            convenience_sum=new_convenience_sum,
            congestion_sum=new_congestion_sum,
            # 경로 수정 => 병렬 방식에서는 탑승역 경로 + 도착역만 저장
            route=prev_label.route + [to_station_cd],
            lines=prev_label.lines + [line],
            transfer_context=new_transfer_context,
            created_round=created_round_num,
        )

    def _get_stations_on_line(self, station_cd: str, line: str) -> Dict[str, List[str]]:
        """사전 생성한 맵 조회로 변경"""
        return self.line_stations_map.get((station_cd, line), {})

    def _get_transfer_distance_cached(
        self, station_cd: str, from_line: str, to_line: str
    ) -> float:
        """환승 거리 조회 <- 요청별 캐싱"""
        cache_key = (station_cd, from_line, to_line)
        if cache_key not in self._transfer_distance_cache:
            self._transfer_distance_cache[cache_key] = get_transfer_distance(
                station_cd, from_line, to_line
            )
        return self._transfer_distance_cache[cache_key]

    def _get_facility_scores_cached(self, station_cd: str) -> Dict[str, float]:
        """편의시설 점수 조회 <- 요청별 캐싱"""
        cache_key = (station_cd, self.disability_type)
        if cache_key not in self._facility_scores_cache:
            self._facility_scores_cache[cache_key] = self._get_facility_scores(
                station_cd
            )
        return self._facility_scores_cache[cache_key]

    def _get_facility_scores(self, station_cd: str) -> Dict[str, float]:
        """편의시설 점수 계산 (self.convenience_scores 조회)"""
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
        """편의도 점수 계산 <- 요청별 캐싱"""
        cache_key = (station_cd, self.disability_type)
        if cache_key not in self._convenience_cache:
            facility_scores = self._get_facility_scores_cached(station_cd)
            score = 2.5  # 기본값
            if facility_scores:
                score = self.anp_calculator.calculate_convenience_score(
                    self.disability_type, facility_scores
                )
            self._convenience_cache[cache_key] = score
        return self._convenience_cache[cache_key]

    def _determine_direction(
        self, from_station_cd: str, to_station_cd: str, line: str
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
        return "up"  # 기본값

    def _update_pareto_frontier(
        self, new_label: Label, existing_labels: List[Label]
    ) -> Tuple[List[Label], bool]:
        """파레토 프론티어 단일 패스 갱신"""
        new_frontier = []
        is_dominated_by_existing = False
        was_updated = False  # 프론티어 변경 여부

        for existing in existing_labels:
            if existing.dominates(new_label):
                # 기존 라벨이 새 라벨을 지배 -> 새 라벨 추가 안함
                is_dominated_by_existing = True
                new_frontier.append(existing)
            elif new_label.dominates(existing):
                # 새 라벨이 기존 라벨을 지배 -> 기존 라벨 제거
                was_updated = True
                continue  # 기존 라벨을 new_frontier에 추가하지 않음
            else:
                # 지배 관계 아님 -> 둘 다 유지
                new_frontier.append(existing)

        if not is_dominated_by_existing:
            # 새 라벨이 지배당하지 않음 -> 프론티어에 추가
            new_frontier.append(new_label)
            was_updated = True

        return new_frontier, was_updated

    # main.py용 헬퍼 함수
    def get_station_info_from_cd(self, station_cd: str) -> Dict:
        """station_cd로 self.stations에서 역 정보 조회"""
        return self.stations.get(station_cd, {})

    def get_station_name_from_cd(self, station_cd: str) -> str:
        """station_cd로 역 이름 조회"""
        return self.stations.get(station_cd, {}).get("name", "Unknown Station")
