"""
REST API 경로 계산 엔드포인트 (WebSocket 대안)
"""

from fastapi import APIRouter, HTTPException, Depends
import logging
from functools import lru_cache
from app.models.requests import NavigationStartRequest
from app.models.responses import RouteCalculatedResponse
from app.services.pathfinding_service import PathfindingService
from app.core.exceptions import KindMapException
from app.api.deps import get_current_user
from app.models.domain import User
from typing import Optional
import uuid


router = APIRouter()
logger = logging.getLogger(__name__)


# lru_cache 사용하여 싱글톤 패턴과 유사한 효과, 의존성 주입
@lru_cache()
def get_pathfinding_service() -> PathfindingService:
    return PathfindingService()


# def get_pathfinding_service():
#     """PathfindingService 인스턴스를 반환(싱글톤)"""
#     global _pathfinding_service
#     if _pathfinding_service is None:
#         _pathfinding_service = PathfindingService()
#     return _pathfinding_service


# login -> user의 disability_type 자동 적용
@router.post("/calculate", response_model=RouteCalculatedResponse)
async def calculate_route(
    request: NavigationStartRequest,
    current_user: Optional[User] = Depends(get_current_user),
    service: PathfindingService = Depends(get_pathfinding_service),
):
    """
    경로 계산 (REST API)

    WebSocket을 사용하지 않는 경우를 위한 대안
    로그인하지 않았을 경우 -> request의 값 사용
    로그인한 상태일 경우 => 사용자의 입력을 우선시, 입력이 없을 경우 disability_type 자동 적용

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
        # User prefence Fallbcak
        final_disability_type = request.disability_type

        if not final_disability_type and current_user:
            final_disability_type = current_user.disability_type

        if not final_disability_type:
            raise HTTPException(
                status_code=400, detail="교통약자 유형 정보가 없습니다."
            )

        logger.info(
            f"REST 경로 계산: {request.origin} → {request.destination}, type={request.disability_type}"
        )

        result = service.calculate_route(
            origin_name=request.origin,
            destination_name=request.destination,
            disability_type=final_disability_type,
        )

        # route_id 생성 및 추가
        # client -> REST API응답을 사용하여 경로를 탐색할 경우에도 route_id를 받을 수 있도록 함
        # Wesocket start_navigation과 일관성 유지
        route_id = str(uuid.uuid4())
        result["route_id"] = route_id

        logger.info(f"REST 경로 계산 완료: {route_id}")

        return result

    except KindMapException as e:
        logger.error(f"경로 계산 실패: {e.message}")
        raise HTTPException(
            status_code=400, detail={"message": e.message, "code": e.code}
        )
    except Exception as e:
        logger.error(f"예상치 못한 오류: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"경로 계산 중 오류 발생: {str(e)}")
