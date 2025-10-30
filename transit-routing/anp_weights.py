import numpy as np
from typing import Dict, List, Optional
import logging
from database import get_db_cursor

logger = logging.getLogger(__name__)


class ANPWeightCalculator:
    def __init__(self):
        self.pairwise_matrices = {
            "PHY": self._get_phy_matrix(),  # 지체 장애(휠체어 사용자)
            "VIS": self._get_vis_matrix(),  # 시각 장애(저시력자)
            "AUD": self._get_aud_matrix(),  # 청각 장애(농인)
            "ELD": self._get_eld_matrix(),  # 고령자(추후 운동능력에 따라 세분화)
        }

        # lazy initialization memory cache
        self._facility_preferences_cache: Optional[Dict[str, Dict[str, float]]] = None

    def _get_phy_matrix(self) -> np.ndarray:
        # 휠체어: 환승 > 편의도 > 보행거리 > 소요시간
        return np.array(
            [
                [1, 1 / 4, 1 / 2, 1 / 3],  # 소요시간
                [4, 1, 3, 2],  # 환승 횟수
                [2, 1 / 3, 1, 1 / 2],  # 보행거리
                [3, 1 / 2, 2, 1],  # 편의도
            ]
        )

    def _get_vis_matrix(self) -> np.ndarray:
        # 시각장애: 편의도(안전) > 환승 > 보행거리 > 소요시간
        return np.array(
            [
                [1, 1 / 4, 1 / 3, 1 / 7],  # 소요시간
                [4, 1, 2, 1 / 3],  # 환승 횟수
                [3, 1 / 2, 1, 1 / 5],  # 보행거리
                [7, 3, 5, 1],  # 편의도
            ]
        )

    def _get_aud_matrix(self) -> np.ndarray:
        # 청각장애: 편의도(시각정보) > 소요시간 > 환승 > 보행거리
        return np.array(
            [
                [1, 1 / 4, 2, 1 / 7],  # 소요시간
                [4, 1, 5, 1 / 5],  # 환승 횟수
                [1 / 2, 1 / 5, 1, 1 / 8],  # 보행거리
                [7, 5, 8, 1],  # 편의도
            ]
        )

    def _get_eld_matrix(self) -> np.ndarray:
        # 고령자: 보행거리 > 환승 > 소요시간 > 편의도
        return np.array(
            [
                [1, 1 / 2, 1 / 3, 2],  # 소요시간
                [2, 1, 1 / 2, 3],  # 환승 횟수
                [3, 2, 1, 4],  # 보행거리
                [1 / 2, 1 / 3, 1 / 4, 1],  # 편의도
            ]
        )

    def _load_facility_preferences_from_db(self) -> Dict[str, Dict[str, float]]:
        """DB에서 시설별 선호도 가중치 로드 (한 번만 실행)"""
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
            # 실패 시 기본값 반환
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
            "ELDERLY": {
                "elevator": 0.20,
                "escalator": 0.30,
                "transfer_walk": 0.20,
                "other_facil": 0.15,
                "staff_help": 0.15,
            },
        }

    def calculate_weights(self, disability_type: str) -> Dict[str, float]:
        """4가지 기준(소요시간, 환승, 보행거리, 편의도)에 대한 ANP 가중치 계산"""
        matrix = self.pairwise_matrices[disability_type]

        eigenvalues, eigenvectors = np.linalg.eig(matrix)
        max_idx = np.argmax(eigenvalues.real)
        principal_eigenvector = np.abs(eigenvectors[:, max_idx].real)

        weights = principal_eigenvector / np.sum(principal_eigenvector)

        cr = self._calculate_consistency_ratio(matrix, eigenvalues[max_idx].real)

        if cr > 0.1:
            logger.warning(f"CR={cr:.3f} > 0.1 for {disability_type}")

        criteria = ["travel_time", "transfers", "walking_distance", "convenience"]

        return dict(zip(criteria, weights))

    def _calculate_consistency_ratio(
        self, matrix: np.ndarray, max_eigenvalue: float
    ) -> float:
        n = len(matrix)
        ci = (max_eigenvalue - n) / (n - 1)
        ri = {3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45}
        return ci / ri.get(n, 1.41)

    def get_facility_weights(self, disability_type: str) -> Dict[str, float]:
        """
        시설별 선호도 가중치 반환 (캐싱 적용)

        첫 호출 시 DB에서 로드하여 메모리 캐시, 이후 캐시에서 반환
        """
        # Lazy initialization
        if self._facility_preferences_cache is None:
            self._facility_preferences_cache = self._load_facility_preferences_from_db()

        return self._facility_preferences_cache.get(disability_type, {})

    def calculate_convenience_score(
        self, disability_type: str, facility_scores: Dict[str, float]
    ) -> float:
        """
        편의도 점수 계산

        Args:
            disability_type: 장애 유형 ('PHY', 'VIS', 'AUD', 'ELDERLY')
            facility_scores: 시설별 점수 딕셔너리
                           {'elevator': 3.38, 'escalator': 3.06, ...}

        Returns:
            가중 편의도 점수 (0.0 ~ 5.0 범위)
        """
        weights = self.get_facility_weights(disability_type)

        if not weights:
            logger.warning(f"No facility weights found for {disability_type}")
            return 0.0

        total_score = 0.0
        for facility, weight in weights.items():
            score = facility_scores.get(facility, 0.0)
            total_score += weight * score

        return total_score
