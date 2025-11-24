"""
KindMap Backend - FastAPI Application

교통약자를 위한 지하철 경로 안내 시스템
실시간 경로 안내 및 경로 이탈 감지
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.db.database import initialize_pool, close_pool
from app.db.cache import initialize_cache
from app.db.redis_client import init_redis
from app.api.v1.router import api_router

# 로깅 설정
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    애플리케이션 생명주기 관리

    서버 시작 시 실행:
    - PostgreSQL 연결 풀 초기화
    - 데이터 캐시 초기화 (역, 구간, 환승역 정보)
    - Redis 클라이언트 초기화

    서버 종료 시 실행:
    - PostgreSQL 연결 풀 정리
    - 리소스 해제
    """
    # ========== Startup ==========
    logger.info("=" * 60)
    logger.info("KindMap Backend 시작 중...")
    logger.info("=" * 60)

    try:
        # 1. PostgreSQL 연결 풀 초기화
        logger.info("1/3 PostgreSQL 연결 풀 초기화 중...")
        initialize_pool()
        logger.info("✓ PostgreSQL 연결 풀 초기화 완료")

        # 2. 데이터 캐시 초기화 (역, 구간, 환승역)
        logger.info("2/3 데이터 캐시 로딩 중...")
        initialize_cache()
        logger.info("✓ 데이터 캐시 초기화 완료")

        # 3. Redis 클라이언트 초기화
        logger.info("3/3 Redis 클라이언트 초기화 중...")
        redis_client = init_redis()
        logger.info("✓ Redis 클라이언트 초기화 완료")

        logger.info("=" * 60)
        logger.info(f"✅ 서버 준비 완료: http://0.0.0.0:{settings.PORT}")
        logger.info(f"📚 API 문서: http://0.0.0.0:{settings.PORT}/docs")
        logger.info(f"🔌 WebSocket: ws://0.0.0.0:{settings.PORT}/api/v1/ws/{{user_id}}")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"❌ 초기화 실패: {e}", exc_info=True)
        raise

    yield

    # ========== Shutdown ==========
    logger.info("=" * 60)
    logger.info("KindMap Backend 종료 중...")
    logger.info("=" * 60)

    try:
        # PostgreSQL 연결 풀 정리
        logger.info("PostgreSQL 연결 풀 정리 중...")
        close_pool()
        logger.info("✓ PostgreSQL 연결 풀 정리 완료")

        logger.info("=" * 60)
        logger.info("✅ 서버 종료 완료")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"❌ 종료 중 오류: {e}", exc_info=True)


# FastAPI 애플리케이션 생성
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="""
    ## 교통약자를 위한 지하철 경로 안내 시스템
    
    ### 주요 기능
    - 🚇 실시간 경로 안내 (WebSocket)
    - 👥 교통약자 유형별 최적 경로 (ANP 가중치)
    - 📍 경로 이탈 감지 및 재계산
    - 🔄 상위 3개 경로 제공
    - 🚉 환승역 안내
    
    ### 지원 장애 유형
    - **PHY**: 지체장애 (휠체어 사용자)
    - **VIS**: 시각장애
    - **AUD**: 청각장애
    - **ELD**: 고령자
    
    ### WebSocket 연결
```
    ws://localhost:8000/api/v1/ws/{user_id}
```
    
    구현 완료
    - ✅ 실시간 위치 기반 경로 안내
    - ✅ 경로 이탈 감지
    - ✅ 도착 감지
    - ✅ 환승 안내
    - ✅ 경로 재계산
    """,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=(
        ["*"]
        # if settings.DEBUG => 우선 "*"
        # else [
        #     "http://localhost:3000",
        #     "http://localhost:8080",
        #     # "https://kindmap.kr",  # web frontend or cloudfront
        # ]
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 라우터 등록
app.include_router(api_router, prefix="/v1") # 중복 접두사 문제 발생 수정


# ========== Health Check Endpoints ==========


@app.get("/")
async def root():
    """
    루트 엔드포인트

    서비스 기본 정보 반환
    """
    return {
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "running",
        "phase": "Phase 3",
        "features": [
            "실시간 경로 안내",
            "경로 이탈 감지",
            "상위 3개 경로 제공",
            "환승 안내",
            "교통약자 유형별 최적화",
        ],
        "docs": "/docs",
        "websocket": f"ws://localhost:{settings.PORT}/api/v1/ws/{{user_id}}",
    }


@app.get("/health")
async def health_check():
    """
    헬스 체크 엔드포인트

    서버 상태 확인용 (로드 밸런서, 모니터링)
    """
    try:
        # Redis 연결 확인
        from app.db.redis_client import init_redis

        redis_client = init_redis()
        redis_status = "healthy" if redis_client.redis_client.ping() else "unhealthy"

    except Exception as e:
        logger.error(f"Redis 헬스 체크 실패: {e}")
        redis_status = "unhealthy"

    try:
        # PostgreSQL 연결 확인
        from app.db.database import get_db_connection

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        db_status = "healthy"

    except Exception as e:
        logger.error(f"DB 헬스 체크 실패: {e}")
        db_status = "unhealthy"

    overall_status = (
        "healthy"
        if (redis_status == "healthy" and db_status == "healthy")
        else "unhealthy"
    )

    status_code = 200 if overall_status == "healthy" else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": overall_status,
            "version": settings.VERSION,
            "timestamp": str(logging.time.time()),
            "components": {"database": db_status, "redis": redis_status},
        },
    )


@app.get("/api/v1/info")
async def api_info():
    """
    API 정보 엔드포인트

    API 버전 및 사용 가능한 엔드포인트 정보
    """
    return {
        "api_version": "v1",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "endpoints": {
            "websocket": {
                "url": f"ws://localhost:{settings.PORT}/api/v1/ws/{{user_id}}",
                "description": "실시간 경로 안내 WebSocket",
            },
            "rest": {
                "calculate_route": "POST /api/v1/navigation/calculate",
                "search_stations": "GET /api/v1/stations/search",
                "validate_station": "POST /api/v1/stations/validate",
                "get_lines": "GET /api/v1/stations/lines",
            },
        },
        "documentation": {"swagger": "/docs", "redoc": "/redoc"},
        "supported_disability_types": {
            "PHY": "지체장애 (휠체어 사용자)",
            "VIS": "시각장애",
            "AUD": "청각장애",
            "ELD": "고령자",
        },
    }


# ========== Exception Handlers ==========


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """
    전역 예외 핸들러

    예상치 못한 오류 처리
    """
    logger.error(f"예상치 못한 오류: {exc}", exc_info=True)

    return JSONResponse(
        status_code=500,
        content={
            "message": "서버 내부 오류가 발생했습니다",
            "detail": str(exc) if settings.DEBUG else "Internal Server Error",
        },
    )


# ========== Startup Event (Legacy - lifespan 사용 권장) ==========


@app.on_event("startup")
async def startup_event():
    """
    서버 시작 이벤트 (lifespan이 더 권장됨)

    추가적인 시작 작업이 필요한 경우 여기에 작성
    """
    logger.info("Startup event triggered (using lifespan context manager)")


@app.on_event("shutdown")
async def shutdown_event():
    """
    서버 종료 이벤트 (lifespan이 더 권장됨)

    추가적인 종료 작업이 필요한 경우 여기에 작성
    """
    logger.info("Shutdown event triggered (using lifespan context manager)")


# ========== Development Server ==========

if __name__ == "__main__":
    import uvicorn

    logger.info("개발 서버 시작...")

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="debug" if settings.DEBUG else "info",
        access_log=True,
        use_colors=True,
        # WebSocket 설정
        ws_ping_interval=20.0,  # 20초마다 ping
        ws_ping_timeout=20.0,  # 20초 timeout
        # 성능 설정
        workers=1,  # WebSocket은 단일 worker 권장
        limit_concurrency=1000,
        limit_max_requests=10000,
        timeout_keep_alive=30,
    )
