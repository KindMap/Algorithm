import os
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()  # 환경변수 읽어오기


class Settings:
    PROJECT_NAME: str = "KindMap Backend"
    VERSION: str = "4.0.0"  # get file refactoring

    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"
    PORT: int = int(os.getenv("PORT", 8001))

    DB_HOST: str = os.getenv("DB_HOST", "rds_endpoint")
    DB_PORT: int = int(os.getenv("DB_PORT", 5432))
    DB_NAME: str = os.getenv("DB_NAME", "database_name")
    DB_USER: str = os.getenv("DB_USER", "postgres")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "password")

    REDIS_HOST: str = os.getenv("REDIS_HOST", "redis")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", 6379))
    # 세션 TTL 설정
    SESSION_TTL_SECONDS: int = int(
        os.getenv("SESSION_TTL_SECONDS", 1800)
    )  # 30 m => 모니터링하면서 수정 필

    # 경로 캐시 TTL
    ROUTE_CACHE_TTL_SECONDS: int = int(
        os.getenv("ROUTE_CACHE_TTL_SECONDS", 3600)
    )  # 1시간

    # 캐시 메트릭 활성화 플래그
    ENABLE_CACHE_METRICS: bool = (
        os.getenv("ENABLE_CACHE_METRICS", "true").lower() == "true"
    )

    CELERY_BROKER_URL: str = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1")
    CELERY_RESULT_BACKEND: str = os.getenv(
        "CELERY_RESULT_BACKEND", "redis://redis:6379/2"
    )

    # JWT 설정
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "my -jwt-secret-key")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # CORS 설정
    # ALLOWED_HOSTS(X) => ALLOWED_ORIGINS
    ALLOWED_ORIGINS: list[str] = os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://inha-capstone-03-frontend.s3-website-us-west-2.amazonaws.com,https://kindmap-for-you.cloud",
    ).split(",")

    @property
    def DB_CONFIG(self) -> Dict[str, Any]:
        return {
            "host": self.DB_HOST,
            "port": self.DB_PORT,
            "database": self.DB_NAME,
            "user": self.DB_USER,
            "password": self.DB_PASSWORD,
            "sslmode": "require",  # rds는 ssl 필수
            "connect_timeout": 30,
        }


settings = Settings()  # 모듈화


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

# 장애 유형별 epsilon => v4 : eopsilon 강화
EPSILON_CONFIG = {
    "PHY": 0.04,  # 휠체어: 보수적 (환승 중요)
    "VIS": 0.05,  # 시각장애: 균형
    "AUD": 0.05,  # 청각장애: 균형
    "ELD": 0.02,  # 고령자: 매우 보수적 (변화에 민감)
}

ALLOWED_HOSTS: list[str] = ["localhost", "127.0.0.1", "0.0.0.0"]

# 세션 TTL 설정
SESSION_TTL_SECONDS: int = int(os.getenv("SESSION_TTL_SECONDS", 1800))
# 30 m => 모니터링하면서 수정 필
