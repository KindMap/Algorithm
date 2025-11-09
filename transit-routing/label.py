from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict


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
    max_transfer_difficulty: int

    # Label class 경량화를 위한 새로운 필드
    # 부모 라벨을 가리키는 pointer
    parent_label: Optional["Label"]
    current_station_cd: str
    current_line: str
    current_direction: str
    # 방문한 역 저장
    # U턴 방지를 위해 frozenset 사용, Union 연산으로 효율적 생성 + 불변성 유지
    visited_stations: frozenset
    # 동일한 부모 라벨로부터 여러 라벨 생성됨
    # 트리 구조와 유사 => depth를 기록하여 비교가 필요할 때를 판단, 역추적 활용
    depth: int
    # transfer_context => transfer_info : 변수 이름 통일 _info
    transfer_info: Optional[Tuple[str, str, str]]  # station, from_line, to_line
    # 양방향 탐색이 필요할 경우(출발역, 환승 직후) 판단용
    is_first_move: bool
    created_round: int

    @property
    def route_length(self) -> int:
        return self.depth

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
        """파레토 우위 판단(단순 비교)"""
        if self.current_station_cd != other.current_station_cd:
            return False
        if self.current_line != other.current_line:
            return False
        if self.transfers != other.transfers:
            return False

        better_in_any = False

        if self.arrival_time < other.arrival_time:
            better_in_any = True
        elif self.arrival_time > other.arrival_time:
            return False

        # 평균으로 비교
        self_convenience_avg = self.convenience_sum / self.depth
        other_convenience_avg = other.convenience_sum / other.depth

        if self_convenience_avg > other_convenience_avg:
            better_in_any = True
        elif self_convenience_avg < other_convenience_avg:
            return False

        self_congestion_avg = self.congestion_sum / self.depth
        other_congestion_avg = other.congestion_sum / other.depth

        if self_congestion_avg > other_congestion_avg:
            better_in_any = True
        elif self_congestion_avg < other_congestion_avg:
            return False

        if self.max_transfer_difficulty < other.max_transfer_difficulty:
            better_in_any = True
        elif self.max_transfer_difficulty > other.max_transfer_difficulty:
            return False

        return better_in_any
