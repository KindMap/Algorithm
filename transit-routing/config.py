import os
from typing import Dict, Any

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "rds_endpoint"),
    "port": int(os.getenv("DB_PORT", 5432)),
    "database": os.getenv("DB_NAME", "database_name"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "password"),
    "sslmode": "require",  # rds는 ssl 필수
    "connect_timeout": 30,
}

DISABILITY_TYPES = {
    "PHY": "지체장애",  # 휠체어 사용자
    "VIS": "시각장애",
    "AUD": "청각장애",
    "ELD": "고령자",
}

CRITERIA = [
    "travel_time",
    "transfers",
    "walking_distance",
    "elevator",
    "escalator",
    "transfer_walk",
    "other_facil",
    "staff_help",
]

# 혼잡도 조회를 위한 상/하선 구별에서 순환노선의 경우 내/외선을 사용함
# 순환선 정의
CIRCULAR_LINES = {
    "2호선": "circular",
    "분당선": "circular",
    "경의중앙선": "circular",
}

# 혼잡도 관련 설정
CONGESTION_CONFIG = {
    # 혼잡도(0-100%), 34% => 자리 꽉 참
    # 평균 혼잡도 -> 56.96% 정규화 적용 => 0.57
    "default_value": 0.57,
    "time_slot_minutes": 30,
}

# 교통약자 유형별 보행 속도(m/s)
WALKING_SPEED = {
    "PHY": 0.79,  # 휠체어 사용자 (수동 0.73, 전동 0.86 평균)
    "VIS": 0.76,  # 시각장애인
    "AUD": 0.98,  # 청각장애인
    "ELD": 0.65,  # 고령자
}

# 환승 거리 기본값(m) <- 전체 환승 거리의 평균
DEFAULT_TRANSFER_DISTANCE = 133.09
