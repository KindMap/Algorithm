import numpy as np
from typing import Dict, List, Optional
import logging
from datetime import datetime, timedelta
from database import get_db_cursor
from config import CIRCULAR_LINES, CONGESTION_CONFIG, WALKING_SPEED

logger = logging.getLogger(__name__)


class ANPWeightCalculator:
    """
    기준 변경 및 추가한 ANP 가중치 계산기

    기준:
    소요시간(환승 시 이동시간 포함, 환승역 별 환승 거리 / 유형별 보행속도)
    환승 횟수
    환승 난이도(환승 거리 + 편의도)
    편의도
    혼잡도(요일/시간/방향 특정)
    """

    def __init__(self):
        self.pairwise_metrices = {
            "PHY": self._get_phy_matrix(),
            "VIS": self._get_vis_matrix(),
            "AUD": self._get_aud_matrix(),
            "ELD": self._get_eld_matrix(),
        }

        # caching
        self._facility_preferences_cache: Optional[Dict[str, Dict[str, float]]] = None

    def _get_phy_matrix(self) -> np.ndarray:
        """
        휠체어 사용자: 편의도(이진제거자) > 환승횟수 > 환승난이도 > 혼잡도 > 소요시간
        """
        return np.array(
            [
                [1, 1 / 5, 1 / 4, 1 / 7, 1 / 2],
                [5, 1, 2, 1 / 3, 3],
                [4, 1 / 2, 1, 1 / 5, 2],
                [7, 3, 5, 1, 5],
                [2, 1 / 3, 1 / 2, 1 / 5, 1],
            ]
        )

    def _get_vis_matrix(self) -> np.ndarray:
        """
        저시력자: 편의도 > 환승난이도 > 환승횟수 > 혼잡도 > 소요시간
        """
        return np.array(
            [
                [1, 1 / 4, 1 / 3, 1 / 7, 1 / 3],
                [4, 1, 1 / 2, 1 / 5, 2],
                [3, 2, 1, 1 / 3, 3],
                [7, 5, 3, 1, 5],
                [3, 1 / 2, 1 / 3, 1 / 5, 1],
            ]
        )

    def _get_aud_matrix(self) -> np.ndarray:
        """
        청각장애인: 편의도 > 소요시간 > 환승난이도 > 환승횟수 > 혼잡도
        """
        return np.array(
            [
                [1, 1 / 4, 2, 1 / 7, 3],
                [4, 1, 3, 1 / 5, 5],
                [1 / 2, 1 / 3, 1, 1 / 7, 2],
                [7, 5, 7, 1, 8],
                [1 / 3, 1 / 5, 1 / 2, 1 / 8, 1],
            ]
        )

    def _get_eld_matrix(self) -> np.ndarray:
        """
        고령자: 혼잡도 > 환승난이도 > 환승횟수 > 편의도 > 소요시간
        => 추후 세분화 시 고령자의 이동성에 따라 추가 분류
        """
        return np.array(
            [
                [1, 1 / 2, 1 / 3, 2, 1 / 4],
                [2, 1, 1 / 2, 3, 1 / 3],
                [3, 2, 1, 4, 1 / 2],
                [1 / 2, 1 / 3, 1 / 4, 1, 1 / 5],
                [4, 3, 2, 5, 1],
            ]
        )

    def calculate_weights(self, disability_type: str) -> Dict[str, float]:
        """
        5가지 기준에 대한 ANP 가중치 계산

        정규화 적용
        """
        matrix = self.pairwise_matrices[disability_type]

        eigenvalues, eigenvectors = np.linalg.eig(matrix)
        max_idx = np.argmax(eigenvalues.real)
        principal_eigenvector = np.abs(eigenvectors[:, max_idx].real)

        weights = principal_eigenvector / np.sum(principal_eigenvector)

        cr = self._calculate_consistency_ratio(matrix, eigenvalues[max_idx].real)

        # 정규화
        if cr > 0.1:
            logger.warning(f"CR={cr:.3f} > 0.1 for {disability_type}")

        criteria = [
            "travel_time",
            "transfers",
            "transfer_difficulty",
            "convenience",
            "congestion",
        ]

        return dict(zip(criteria, weights))

    def _calculate_consistency_ratio(
        self, matrix: np.ndarray, max_eigenvalue: float
    ) -> float:
        """일관성 비율(CR) 계산"""
        n = len(matrix)
        ci = (max_eigenvalue - n) / (n - 1)
        ri = {3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45}
        return ci / ri.get(n, 1.41)

    def calculate_transfer_walking_time(
        self,
        transfer_distance: float,
        disability_type: str,
    ) -> float:
        """
        환승 시 보행 시간 계산

        Args:
            transfer_distance: 환승 거리 (미터)
            disability_type: 장애 유형

        Returns:
            보행시간 (초)
        """
        walking_speed = WALKING_SPEED.get(disability_type, 1.0)
        return transfer_distance / walking_speed

    def get_congestion_from_rds(
        self, station_cd: str, line: str, direction: str, departure_time: datetime
    ) -> float:
        """
        RDS에서 실제 혼잡도 조회

        Args:
            station_cd: 역 코드
            line: 호선 (예: '1', '2')
            direction: 방향 ('up', 'down', 'in', 'out')
            departure_time: 출발 시각

        Returns:
            혼잡도 (0.0 ~ 1.0)
        """
        day_type = self._get_day_type(departure_time)
        time_column = self._get_time_column(departure_time)

        query = f"""
        SELECT {time_column} as congestion_level
        FROM subway_congestion
        WHERE station_cd = %s 
          AND line = %s
          AND direction = %s
          AND day_type = %s
        """

        try:
            with get_db_cursor() as cursor:
                cursor.execute(query, (station_cd, line, direction, day_type))
                result = cursor.fetchone()

                if result and result["congestion_level"] is not None:
                    return float(result["congestion_level"]) / 100.0
                else:
                    logger.warning(f"혼잡도 없음: {station_cd}, {line}, {direction}")
                    return CONGESTION_CONFIG["default_value"]

        except Exception as e:
            logger.error(f"혼잡도 조회 실패: {e}")
            return CONGESTION_CONFIG["default_value"]

    def _get_day_type(self, dt: datetime) -> str:
        """요일 타입 반환"""
        weekday = dt.weekday()
        if weekday < 5:
            return "weekday"
        elif weekday == 5:
            return "sat"
        else:
            return "sun"

    def _get_time_column(self, dt: datetime) -> str:
        """시간대를 컬럼명으로 변환 (30분 단위)"""
        minutes_from_midnight = dt.hour * 60 + dt.minute
        slot_minutes = (minutes_from_midnight // 30) * 30
        return f"t_{slot_minutes}"

    def calculate_transfer_difficulty(
        self,
        transfer_distance: float,
        facility_scores: Dict[str, float],
        disability_type: str,
    ) -> float:
        """
        환승 난이도 계산

        Args:
            transfer_distance: 환승 거리 (미터)
            facility_scores: 환승역 시설 점수
            disability_type: 장애 유형

        Returns:
            환승 난이도 점수 (0.0 ~ 1.0, 높을수록 어려움)
        """
        distance_score = min(transfer_distance / 300.0, 1.0)

        convenience_score = self.calculate_convenience_score(
            disability_type, facility_scores
        )
        inconvenience_score = 1.0 - (convenience_score / 5.0)

        difficulty = 0.4 * distance_score + 0.6 * inconvenience_score

        return difficulty

    def calculate_route_congestion_score(
        self, route_segments: List[Dict], departure_time: datetime
    ) -> float:
        """
        경로 전체의 혼잡도 점수 계산

        Args:
            route_segments: List[Dict]
            departure_time: 출발 시각

        Returns:
            평균 혼잡도 점수 (0.0 ~ 1.0)

        Note:
            - 혼잡도 데이터는 30분 단위 평균값
            - 혼잡도 = 열차 정원 대비 승차 인원 비율 (%)
            - 좌석만 만석 시 34% 기준
            - 100% 초과 시 입석 승객 존재
        """
        if not route_segments:
            return 0.0

        total_congestion = 0.0
        current_time = departure_time

        for segment in route_segments:
            congestion = self.get_congestion_from_rds(
                segment["station_cd"],
                segment["line"],
                segment["direction"],
                current_time,
            )
            # 혼잡도가 유효한 경우만 합산
            if congestion is not None:
                total_congestion += congestion
                valid_segment_count += 1

            # 다음 구간 시각 업데이트
            current_time += timedelta(minutes=segment.get("duration_min", 2))

        # 유효한 구간이 없으면 기본값 반환
        if valid_segment_count == 0:
            logger.warning("유효한 혼잡도 데이터 없음, 기본값 사용")
            return CONGESTION_CONFIG["default_value"]

        # 평균 혼잡도 반환 (0.0 ~ 1.0)
        return total_congestion / len(route_segments)

    def _load_facility_preferences_from_db(self) -> Dict[str, Dict[str, float]]:
        """DB에서 시설별 선호도 가중치 로드"""
        query = """
        SELECT user_type, facility_type, weight
        FROM facility_preference
        ORDER BY user_type, facility_type
        """

        preferences = {}

        try:
            with get_db_cursor() as cursor:
                cursor.execute(query)
                rows = cursor.fetchall()

                for row in rows:
                    user_type = row["user_type"]
                    facility_type = row["facility_type"]
                    weight = float(row["weight"])

                    if user_type not in preferences:
                        preferences[user_type] = {}

                    preferences[user_type][facility_type] = weight

            logger.info(f"시설 선호도 가중치 로드 완료: {len(preferences)}개 유형")
            return preferences

        except Exception as e:
            logger.error(f"시설 선호도 로드 실패: {e}")
            return self._get_default_facility_preferences()

    def _get_default_facility_preferences(self) -> Dict[str, Dict[str, float]]:
        """DB 연결 실패 시 사용할 기본 가중치"""
        return {
            "PHY": {
                "elevator": 0.40,
                "escalator": 0.10,
                "transfer_walk": 0.25,
                "other_facil": 0.15,
                "staff_help": 0.10,
            },
            "VIS": {
                "elevator": 0.20,
                "escalator": 0.25,
                "transfer_walk": 0.20,
                "other_facil": 0.15,
                "staff_help": 0.20,
            },
            "AUD": {
                "elevator": 0.25,
                "escalator": 0.30,
                "transfer_walk": 0.25,
                "other_facil": 0.10,
                "staff_help": 0.10,
            },
            "ELD": {
                "elevator": 0.20,
                "escalator": 0.30,
                "transfer_walk": 0.20,
                "other_facil": 0.15,
                "staff_help": 0.15,
            },
        }

    def get_facility_weights(self, disability_type: str) -> Dict[str, float]:
        """시설별 선호도 가중치 반환 (캐싱)"""
        if self._facility_preferences_cache is None:
            self._facility_preferences_cache = self._load_facility_preferences_from_db()

        return self._facility_preferences_cache.get(disability_type, {})

    def calculate_convenience_score(
        self, disability_type: str, facility_scores: Dict[str, float]
    ) -> float:
        """
        편의도 점수 계산

        Args:
            disability_type: 장애 유형
            facility_scores: 시설별 점수
                {'elevator': 4.5, 'escalator': 3.8, ...}

        Returns:
            가중 편의도 점수 (0.0 ~ 5.0)
        """
        weights = self.get_facility_weights(disability_type)

        if not weights:
            logger.warning(f"시설 가중치 없음: {disability_type}")
            return 0.0

        total_score = 0.0
        for facility, weight in weights.items():
            score = facility_scores.get(facility, 0.0)
            total_score += weight * score

        return total_score
