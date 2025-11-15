"""
역 검색 REST API 엔드포인트
"""

from fastapi import APIRouter, Query, HTTPException
from typing import List
import logging

from app.db.cache import search_stations_by_name, get_station_cd_by_name, get_lines_dict
from app.models.responses import StationSearchResponse, StationValidateResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/search", response_model=StationSearchResponse)
async def search_stations(
    q: str = Query(..., description="검색 키워드", min_length=1, max_length=50),
    limit: int = Query(10, ge=1, le=50, description="최대 결과 수")
):
    """
    역 검색 (자동완성용)
    
    - **q**: 검색 키워드 (1-50자)
    - **limit**: 최대 결과 수 (1-50, 기본값 10)
    
    Example:
        GET /api/v1/stations/search?q=강남&limit=5
    """
    try:
        logger.info(f"역 검색: keyword={q}, limit={limit}")
        results = search_stations_by_name(q, limit)
        
        return {
            "keyword": q,
            "count": len(results),
            "results": results
        }
    except Exception as e:
        logger.error(f"역 검색 오류: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"검색 중 오류 발생: {str(e)}")


@router.post("/validate", response_model=StationValidateResponse)
async def validate_station(station_name: str = Query(..., min_length=1)):
    """
    역 이름 유효성 검증
    
    - **station_name**: 검증할 역 이름
    
    Example:
        POST /api/v1/stations/validate?station_name=강남
    """
    try:
        logger.info(f"역 검증: station_name={station_name}")
        station_cd = get_station_cd_by_name(station_name)
        
        if station_cd:
            return {
                "valid": True,
                "station_cd": station_cd,
                "station_name": station_name
            }
        else:
            return {
                "valid": False,
                "message": f"'{station_name}' 역을 찾을 수 없습니다"
            }
    except Exception as e:
        logger.error(f"역 검증 오류: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"검증 중 오류 발생: {str(e)}")


@router.get("/lines")
async def get_all_lines():
    """
    전체 호선 목록 조회
    
    Returns:
        {
            "1호선": ["0150", "0151", ...],
            "2호선": ["0201", "0202", ...],
            ...
        }
    """
    try:
        lines = get_lines_dict()
        return {
            "lines": lines,
            "total_lines": len(lines)
        }
    except Exception as e:
        logger.error(f"호선 목록 조회 오류: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"조회 중 오류 발생: {str(e)}")