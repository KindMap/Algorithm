"""
KindMap Backend - FastAPI Application

교통약자를 위한 지하철 경로 안내 시스템
실시간 경로 안내 및 경로 이탈 감지
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.db.database import initialize_pool, close_pool
from app.db.cache import initialize_cache
from app.db.redis_client import init_redis
from app.api.v1.router import api_router

# Redis Pub/Sub
from app.services.redis_pubsub_manager import get_pubsub_manager
from app.api.v1.endpoints.websocket import manager as websocket_manager

# 성능 모니터링
from app.middleware.performance_monitoring import (
    PerformanceMonitoringMiddleware,
    RequestLoggingMiddleware,
    get_metrics_collector,
)

# 경로 탐색 서비스
from app.services.pathfinding_factory import get_engine_info

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
    - Redis 클라이언트 초기화 (세션 관리용)
    - Redis Pub/Sub 초기화 및 리스너 시작
    - Websocket 메시지 핸들러 등록 및 리스너 시

    서버 종료 시 실행:
    - Redis Pub/Sub 종료
    - PostgreSQL 연결 풀 종
    """
    # ========== Startup ==========
    logger.info("=" * 60)
    logger.info("KindMap Backend 시작 중...")
    logger.info("=" * 60)

    try:
        # 1. PostgreSQL 연결 풀 초기화
        logger.info("1/4 PostgreSQL 연결 풀 초기화 중...")
        initialize_pool()

        # 2. 데이터 캐시 초기화
        logger.info("2/4 역 정보 캐시 초기화 중...")
        initialize_cache()

        # 3. Redis 클라이언트 초기화 (세션 관리용)
        logger.info("3/4 Redis 세션 클라이언트 초기화 중...")
        init_redis()

        # 4. Redis Pub/Sub 초기화 및 리스너 시작
        logger.info("4/4 Redis Pub/Sub 초기화 중...")
        pubsub_manager = get_pubsub_manager()
        await pubsub_manager.initialize()

        # WebSocket 메시지 핸들러 등록 및 리스너 시작
        await pubsub_manager.start_listening(
            message_handler=websocket_manager.handle_pubsub_message
        )

        logger.info("=" * 60)
        logger.info("KindMap Backend 시작 완료!")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"❌ 초기화 실패: {e}", exc_info=True)
        raise

    # application 실행 <- yield로 제어 반
    yield

    # ========== Shutdown ==========
    logger.info("=" * 60)
    logger.info("KindMap Backend 종료 중...")
    logger.info("=" * 60)

    try:
        # 1. Redis Pub/Sub 종료
        logger.info("1/2 Redis Pub/Sub 종료 중...")
        pubsub_manager = get_pubsub_manager()
        await pubsub_manager.close()

        # 2. PostgreSQL 연결 풀 종료
        logger.info("2/2 PostgreSQL 연결 풀 종료 중...")
        close_pool()

        logger.info("=" * 60)
        logger.info("✓ KindMap Backend 종료 완료")
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
    lifespan=lifespan,  # 생명주기 관리자 등록
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS 설정
# allow_credentials=True일 때는 allow_origins에 ["*"]를 사용할 수 없음
# 명시적인 origin 목록을 환경변수에서 가져옴
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 성능 모니터링 미들웨어 추가
if settings.ENABLE_PERFORMANCE_MONITORING:
    app.add_middleware(PerformanceMonitoringMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    logger.info("✓ 성능 모니터링 미들웨어 활성화")

# API 라우터 등록
app.include_router(api_router, prefix="/v1")  # 중복 접두사 문제 발생 수정


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
    - 데이터베이스 연결 상태
    - Redis 연결 상태
    - C++ 엔진 사용 여부
    - 성능 통계
    """
    import time as time_module

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

    # 경로 탐색 엔진 정보
    try:
        engine_info = get_engine_info()
        engine_status = "healthy"
    except Exception as e:
        logger.error(f"엔진 헬스 체크 실패: {e}")
        engine_info = {"error": str(e)}
        engine_status = "unhealthy"

    # 성능 통계 (선택사항)
    performance_stats = None
    if settings.ENABLE_PERFORMANCE_MONITORING:
        try:
            metrics = get_metrics_collector()
            performance_stats = metrics.get_summary()
        except Exception as e:
            logger.error(f"성능 통계 조회 실패: {e}")

    overall_status = (
        "healthy"
        if (
            redis_status == "healthy"
            and db_status == "healthy"
            and engine_status == "healthy"
        )
        else "unhealthy"
    )

    status_code = 200 if overall_status == "healthy" else 503

    response_content = {
        "status": overall_status,
        "version": settings.VERSION,
        "timestamp": time_module.time(),
        "components": {
            "database": db_status,
            "redis": redis_status,
            "pathfinding_engine": engine_status,
        },
        "engine": engine_info,
    }

    # 성능 통계 추가 (있으면)
    if performance_stats:
        response_content["performance"] = performance_stats

    return JSONResponse(status_code=status_code, content=response_content)


@app.get("/api/v1/info")
async def api_info():
    """
    API 정보 엔드포인트

    API 버전 및 사용 가능한 엔드포인트 정보
    """
    # 엔진 정보 추가
    engine = get_engine_info()

    return {
        "api_version": "v1",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "engine": engine,
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


@app.get("/v1/metrics")
async def get_metrics():
    """
    성능 메트릭 엔드포인트

    애플리케이션 성능 통계 조회
    (nginx가 /metrics -> /v1/metrics로 프록시)
    """
    if not settings.ENABLE_PERFORMANCE_MONITORING:
        return {"message": "성능 모니터링이 비활성화되어 있습니다"}

    try:
        metrics = get_metrics_collector()

        return {
            "summary": metrics.get_summary(),
            "top_paths": metrics.get_path_stats(top_n=10),
            "configuration": {
                "slow_request_threshold_ms": settings.SLOW_REQUEST_THRESHOLD_MS,
                "monitoring_enabled": settings.ENABLE_PERFORMANCE_MONITORING,
            },
        }

    except Exception as e:
        logger.error(f"메트릭 조회 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"메트릭 조회 실패: {str(e)}")


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
        workers=4,  # WebSocket은 단일 worker 권장
        limit_concurrency=1000,
        limit_max_requests=10000,
        timeout_keep_alive=30,
    )
