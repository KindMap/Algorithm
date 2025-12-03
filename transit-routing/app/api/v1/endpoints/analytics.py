"""
통계 대시보드 API 엔드포인트
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from typing import List
import logging
import redis

from app.db.redis_client import init_redis, RedisSessionManager
from app.models.analytics import DashboardResponse, StatItem, HourlyItem

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/dashboard", response_model=DashboardResponse)
async def get_analytics_dashboard(
    limit: int = Query(10, ge=1, le=50, description="조회할 순위 개수"),
    redis_manager: RedisSessionManager = Depends(init_redis),
):
    """
    통계 대시보드 데이터 조회

    - **limit**: 조회할 순위 개수 (1-50, 기본값 10)

    Returns:
        - top_origins: 인기 출발역 TOP N
        - top_destinations: 인기 도착역 TOP N
        - top_od_pairs: 인기 경로 TOP N
        - top_transfer_stations: 환승 많은 역 TOP N
        - hourly_traffic: 시간대별 검색 트래픽

    Example:
        GET /api/v1/analytics/dashboard?limit=10
    """
    try:
        logger.info(f"통계 대시보드 조회 시작: limit={limit}")

        # Redis 데이터 조회
        origins_data = redis_manager.get_top_origins(limit)
        destinations_data = redis_manager.get_top_destinations(limit)
        od_pairs_data = redis_manager.get_top_od_pairs(limit)
        transfers_data = redis_manager.get_top_transfer_stations(limit)
        hourly_data = redis_manager.get_hourly_traffic()

        # 데이터 변환 헬퍼 Tuple -> Pydantic Model
        def to_stat_items(data_list: List[tuple]) -> List[StatItem]:
            return [StatItem(label=item[0], count=int(item[1])) for item in data_list]

        # 시간대 데이터 변환 Dict -> List[HourlyItem]
        # 명시적으로 int 변환
        sorted_hours = sorted(hourly_data.items(), key=lambda x: int(x[0]))
        hourly_items = [HourlyItem(hour=int(h), count=c) for h, c in sorted_hours]

        logger.info(
            f"통계 조회 성공: origins={len(origins_data)}, "
            f"destinations={len(destinations_data)}, "
            f"od_pairs={len(od_pairs_data)}, "
            f"transfers={len(transfers_data)}"
        )

        # 응답 생성
        return DashboardResponse(
            top_origins=to_stat_items(origins_data),
            top_destinations=to_stat_items(destinations_data),
            top_od_pairs=to_stat_items(od_pairs_data),
            top_transfer_stations=to_stat_items(transfers_data),
            hourly_traffic=hourly_items,
        )

    except redis.RedisError as e:
        logger.error(f"Redis 연결 실패: {e}")
        raise HTTPException(
            status_code=503,
            detail="통계 서비스 일시 중단"
        )
    except Exception as e:
        logger.error(f"통계 조회 중 예상치 못한 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"통계 조회 중 오류 발생: {str(e)}"
        )
