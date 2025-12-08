"""
C++ 엔진 성능 테스트용 간단한 서버

DB 의존성 없이 경로 탐색 엔드포인트만 테스트
"""

import os
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

# C++ 엔진 강제 활성화
os.environ["USE_CPP_ENGINE"] = "true"
os.environ["DEBUG"] = "true"

from app.services.pathfinding_factory import get_pathfinding_service, get_engine_info

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# FastAPI 앱 생성 (간단한 버전)
app = FastAPI(
    title="KindMap C++ Engine Test",
    version="1.0.0",
    description="C++ 경로 탐색 엔진 성능 테스트용 서버",
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 요청 모델
class RouteRequest(BaseModel):
    origin: str
    destination: str
    departure_time: Optional[str] = "2024-12-10 09:00:00"
    disability_type: str = "PHY"


@app.on_event("startup")
async def startup_event():
    """서버 시작 시 C++ 엔진 초기화"""
    logger.info("=" * 60)
    logger.info("C++ 엔진 테스트 서버 시작 중...")
    logger.info("=" * 60)
    
    try:
        # 엔진 정보 확인
        engine_info = get_engine_info()
        logger.info(f"엔진 정보: {engine_info}")
        
        if engine_info.get("cpp_enabled"):
            logger.info("✅ C++ 엔진 활성화 성공!")
        else:
            logger.warning("⚠️ Python 엔진으로 fallback됨")
            
    except Exception as e:
        logger.error(f"엔진 초기화 실패: {e}", exc_info=True)


@app.get("/")
async def root():
    """루트 엔드포인트"""
    return {
        "service": "KindMap C++ Engine Test",
        "status": "running",
        "engine": get_engine_info(),
    }


@app.get("/health")
async def health_check():
    """헬스체크"""
    import time
    
    engine_info = get_engine_info()
    
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "engine": engine_info,
    }


@app.post("/api/v1/navigation/calculate")
async def calculate_route(request: RouteRequest):
    """
    경로 계산 (C++ 엔진 테스트)
    
    주의: 이 테스트 서버는 DB 없이 동작하므로
    실제 경로 계산은 불가능하며, C++ 엔진 호출만 테스트합니다.
    """
    import time
    
    start_time = time.time()
    
    try:
        # 경로 탐색 서비스 가져오기
        pathfinding_service = get_pathfinding_service()
        
        logger.info(
            f"경로 계산 요청: {request.origin} → {request.destination} "
            f"(장애유형: {request.disability_type})"
        )
        
        # 실제로는 DB가 필요하므로 여기서는 엔진 정보만 반환
        # 실제 환경에서는 pathfinding_service.find_routes() 호출
        
        elapsed_time = (time.time() - start_time) * 1000
        
        return {
            "message": "C++ 엔진 테스트 모드",
            "engine": get_engine_info(),
            "request": {
                "origin": request.origin,
                "destination": request.destination,
                "disability_type": request.disability_type,
            },
            "elapsed_time_ms": round(elapsed_time, 2),
            "note": "실제 경로 계산은 DB 연결이 필요합니다. "
                    "이 서버는 C++ 엔진 로딩 및 응답 속도만 테스트합니다.",
        }
        
    except Exception as e:
        logger.error(f"경로 계산 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/info")
async def api_info():
    """API 정보"""
    return {
        "api_version": "v1",
        "service": "KindMap C++ Engine Test",
        "engine": get_engine_info(),
        "endpoints": {
            "health": "GET /health",
            "calculate": "POST /api/v1/navigation/calculate",
        },
    }


if __name__ == "__main__":
    import uvicorn
    
    logger.info("테스트 서버 시작...")
    
    uvicorn.run(
        "test_server:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        log_level="info",
    )
