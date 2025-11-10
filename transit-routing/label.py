from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Dict

EMPTY_FROZENSET = frozenset()


# slots=True => 파이썬 객체가 기본적으로 생성하는 딕셔너리를 방지,
# 클래스에 정의된 필드만을 위해 고정된 메모리 공간 사용
# 메모리 절감 및 빠른 접근, 동적 속성 추가 방지로 버그 방지
@dataclass(slots=True)
class Label:
    arrival_time: float
    transfers: int
    # 편의도, 혼잡도 => 누적합 활용 및 추후 평균 비교
    convenience_sum: float
    congestion_sum: float
    # 환승 난이도 => 최댓값(최악) 활용
    max_transfer_difficulty: float

    # Label class 경량화를 위한 새로운 필드
    # 부모 라벨을 가리키는 pointer
    parent_label: Optional["Label"]
    current_station_cd: str
    current_line: str
    current_direction: str
    # 방문한 역 저장
    # U턴 방지를 위해 frozenset 사용, Union 연산으로 효율적 생성 + 불변성 유지
    visited_stations: frozenset = field(default_factory=lambda: EMPTY_FROZENSET)
    # 동일한 부모 라벨로부터 여러 라벨 생성됨
    # 트리 구조와 유사 => depth를 기록하여 비교가 필요할 때를 판단, 역추적 활용
    depth: int = 1
    # transfer_context => transfer_info : 변수 이름 통일 _info
    transfer_info: Optional[Tuple[str, str, str]] = None  # station, from_line, to_line
    # 양방향 탐색이 필요할 경우(출발역, 환승 직후) 판단용
    is_first_move: bool = False
    created_round: int = 0

    @property
    def route_length(self) -> int:
        return self.depth

    @property
    def avg_convenience(self) -> float:
        """평균 편의도"""
        return self.convenience_sum / self.depth

    @property
    def avg_congestion(self) -> float:
        """평균 혼잡도"""
        return self.congestion_sum / self.depth

    # 중요!!! 역추적 로직!!!
    # leaf -> root 탐색하는 로직과 동일
    def reconstruct_route(self) -> List[str]:
        """전체 경로 역추적"""
        route = []
        cur = self
        while cur is not None:
            route.append(cur.current_station_cd)
            cur = cur.parent_label
        return route[::-1]

    def reconstruct_lines(self) -> List[str]:
        """전체 노선 정보 재구성"""
        lines = []
        cur = self
        while cur is not None:
            lines.append(cur.current_line)
            cur = cur.parent_label
        return lines[::-1]

    def reconstruct_transfer_info(self) -> List[Tuple[str, str, str]]:
        """환승 정보 재구성"""
        transfers = []
        cur = self
        while cur is not None:
            if cur.transfer_info is not None:
                transfers.append(cur.transfer_info)
            cur = cur.parent_label
        return transfers[::-1]

    def __eq__(self, other):
        if not isinstance(other, Label):
            return False
        return (
            self.current_station_cd == other.current_station_cd
            and self.current_line == other.current_line
            and self.transfers == other.transfers
        )

    # 해싱!!!
    def __hash__(self):
        return hash((self.current_station_cd, self.current_line, self.transfers))

    # epsilon 제거 => 단순 비교로 변경
    def dominates(self, other: "Label") -> bool:
        """파레토 우위 판단(단순 비교) 평균을 비교"""

        # 비교 대상이 아닌 라벨 => False
        if self.current_station_cd != other.current_station_cd:
            return False
        if self.current_line != other.current_line:
            return False
        if self.transfers != other.transfers:
            return False

        better_in_any = False

        # 최소화해야 하는 기준 -> 환승 횟수 소요 시간, 평균 혼잡도, 환승 난이도
        if self.transfers < other.transfers:
            better_in_any = True
        elif self.transfers > other.transfers:
            return False

        if self.max_transfer_difficulty < other.max_transfer_difficulty:
            better_in_any = True
        elif self.max_transfer_difficulty > other.max_transfer_difficulty:
            return False

        if self.arrival_time < other.arrival_time:
            better_in_any = True
        elif self.arrival_time > other.arrival_time:
            return False

        if self.avg_congestion < other.avg_congestion:
            better_in_any = True
        elif self.avg_congestion > other.avg_congestion:
            return False

        # 최대화해야 하는 기준 -> 편의도
        if self.avg_convenience > other.avg_convenience:
            better_in_any = True
        elif self.avg_convenience < other.avg_convenience:
            return False

        return better_in_any

    # 교통약자 유형별 가중치를 받아 최종 스코어(페널티)를 계산
    def calculate_weighted_score(self, weights: Dict[str, float]) -> float:
        """anp_weights가 계산한 가중치를 입력받아 스코어를 계산"""

        norm_time = min(self.arrival_time / 120.0, 1.0)  # 120분 기준
        norm_transfers = min(self.transfers / 4.0, 1.0)  # 4회 기준

        # 이미 정규화 적용된 값
        norm_difficulty = self.max_transfer_difficulty

        # 편의도는 높을 수록 좋으므로 역변환
        norm_convenience = 1.0 - (self.avg_convenience / 5.0)

        # 혼잡도 <- 1+ 가능
        norm_congestion = min(self.avg_congestion, 1.0)

        score = (
            weights.get("travel_time", 0.2) * norm_time
            + weights.get("transfers", 0.2)
            * norm_transfers  
            + weights.get("transfer_difficulty", 0.2) * norm_difficulty
            + weights.get("convenience", 0.2) * norm_convenience
            + weights.get("congestion", 0.2) * norm_congestion
        )

        return score
