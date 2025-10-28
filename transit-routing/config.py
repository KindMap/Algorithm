import os
from typing import Dict, Any

DB_CONFIG = {
    "endpoint": os.getenv("DB_ENDPOINT", "rds_endpoint"),
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
    "ELDERLY": "고령자",
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
