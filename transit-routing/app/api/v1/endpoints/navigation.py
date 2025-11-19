"""
REST API 경로 계산 엔드포인트 (WebSocket 대안)
"""

from fastapi import APIRouter, HTTPException
import logging
from app.models.requests import NavigationStartRequest
from app.models.responses import RouteCalculatedResponse
from app.services.pathfinding_service import PathfindingService
from app.core.exceptions import KindMapException

router = APIRouter()
logger = logging.getLogger(__name__)

# lazy initialization pattern 사용
_pathfinding_service = None


def get_pathfinding_service():
    """PathfindingService 인스턴스를 반환(싱글톤)"""
    global _pathfinding_service
    if _pathfinding_service is None:
        _pathfinding_service = PathfindingService()
    return _pathfinding_service


@router.post("/calculate", response_model=RouteCalculatedResponse)
async def calculate_route(request: NavigationStartRequest):
    """
    경로 계산 (REST API)

    WebSocket을 사용하지 않는 경우를 위한 대안

    - **origin**: 출발지 역 이름
    - **destination**: 목적지 역 이름
    - **disability_type**: 장애 유형 (PHY/VIS/AUD/ELD)

    Returns:
        상위 3개 경로 정보

    Example:
        POST /api/v1/navigation/calculate
        {
            "origin": "강남",
            "destination": "서울역",
            "disability_type": "PHY"
        }
    """
    try:
        logger.info(
            f"REST 경로 계산: {request.origin} → {request.destination}, type={request.disability_type}"
        )
        pathfinding_service = get_pathfinding_service()

        route_data = pathfinding_service.calculate_route(
            request.origin, request.destination, request.disability_type
        )

        return {
            "origin": route_data["origin"],
            "destination": route_data["destination"],
            "routes": route_data["routes"],
            "total_routes_found": route_data["total_routes_found"],
            "routes_returned": route_data["routes_returned"],
        }

    except KindMapException as e:
        logger.error(f"경로 계산 실패: {e.message}")
        raise HTTPException(
            status_code=400, detail={"message": e.message, "code": e.code}
        )
    except Exception as e:
        logger.error(f"예상치 못한 오류: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"경로 계산 중 오류 발생: {str(e)}")
