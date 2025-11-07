from typing import List, Dict, Set
from dataclasses import dataclass, field


# label class와 mc_raptor 분리
@dataclass
class Label:
    """경로 라벨 (파레토 최적해)"""

    arrival_time: float  # 총 소요시간 (분)
    transfers: int  # 환승 횟수
    transfer_difficulty: float  # 환승 난이도 총합 (0~1 * 환승횟수)
    convenience_score: float  # 평균 편의도 점수 (0~5)
    congestion_score: float  # 평균 혼잡도 점수 (0~1+)
    route: List[str] = field(default_factory=list)  # 경로를 지나가는 역의 정보
    lines: List[str] = field(default_factory=list)  # 역들의 호선 정보 -> 환승 횟수 계산
    transfer_stations: Set[str] = field(
        default_factory=set
    )  # 환승역 별 안내를 위한 환승역 리스트
    created_round: int = 0  # 라벨이 생성된 라운드

    def dominates(self, other: "Label") -> bool:
        """
        파레토 우위 판단 (5개 기준)

        Returns:
            True if self가 other를 지배함
        """
        better_in_one = False
        criteria = [
            (self.arrival_time, other.arrival_time, False),  # 최소화
            (self.transfers, other.transfers, False),  # 최소화
            (self.transfer_difficulty, other.transfer_difficulty, False),  # 최소화
            (self.convenience_score, other.convenience_score, True),  # 최대화
            (self.congestion_score, other.congestion_score, False),  # 최소화
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
            anp_weights: {'travel_time': 0.x, 'transfers': 0.x, ...}

        Returns:
            float: 가중 종합 페널티 (낮을수록 좋음)
        """
        # 정규화 (0-1 범위)
        norm_time = min(self.arrival_time / 120.0, 1.0)  # 120분 기준
        norm_transfers = min(self.transfers / 4.0, 1.0)  # 4회 기준

        # 환승 난이도: 환승이 없으면 0, 있으면 평균 난이도
        norm_difficulty = (
            self.transfer_difficulty / max(1, self.transfers)
            if self.transfers > 0
            else 0.0
        )

        # 편의도: 5점 만점을 0-1로 변환 (높을수록 좋으므로 역변환)
        norm_convenience = 1.0 - (self.convenience_score / 5.0)

        # 혼잡도: 이미 0-1 범위
        norm_congestion = min(self.congestion_score, 1.0)

        # 가중 합산
        score = (
            anp_weights.get("travel_time", 0.2) * norm_time
            + anp_weights.get("transfers", 0.2) * norm_transfers
            + anp_weights.get("transfer_difficulty", 0.2) * norm_difficulty
            + anp_weights.get("convenience", 0.2) * norm_convenience
            + anp_weights.get("congestion", 0.2) * norm_congestion
        )

        return score

    def __eq__(self, other: "Label") -> bool:
        """라벨 동등성 검사 (경로 비교)"""
        if not isinstance(other, Label):
            return False
        return self.route == other.route

    def __hash__(self) -> int:
        """해시 함수 (Set에서 사용)"""
        return hash(tuple(self.route))
