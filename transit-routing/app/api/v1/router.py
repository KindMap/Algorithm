"""API v1 main router
모든 엔드포인트를 통합하여 하나의 API 라우터로 제공
"""

from fastapi import APIRouter
from app.api.v1.endpoints import navigation, stations, websocket

# API v1 main router
api_router = APIRouter()

# 각 엔드 포인트 라우터 통합
api_router.include_router(navigation.router, prefix="/navigation", tags=["navigation"])

api_router.include_router(stations.router, prefix="/stations", tags=["stations"])

api_router.include_router(websocket.router, tags=["websocket"])
