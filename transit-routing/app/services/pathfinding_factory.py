# 경로 탐색 서비스 팩토리

import logging
from functools import lru_cache
from typing import Union

from app.core.config import settings
from app.services.pathfinding_service import PathfindingService

logger = logging.getLogger(__name__)


@lru_cache()
def get_pathfinding_service() -> Union[PathfindingService, "PathfindingServiceCPP"]:
    """
    환경 변수에 따라 적절한 경로 탐색 서비스 반환 (싱글톤)

    - USE_CPP_ENGINE=true: PathfindingServiceCPP (C++ 엔진)
    - USE_CPP_ENGINE=false: PathfindingService (Python 엔진)

    Returns:
        PathfindingService 또는 PathfindingServiceCPP 인스턴스
    """

    if settings.USE_CPP_ENGINE:
        logger.info("C++ 경로 탐색 엔진 사용")
        try:
            from app.services.pathfinding_service_cpp import PathfindingServiceCPP

            service = PathfindingServiceCPP()
            logger.info("✓ PathfindingServiceCPP 초기화 완료")
            return service

        except ImportError as e:
            logger.error(
                f"C++ 엔진을 로드할 수 없습니다: {e}\n"
                "Python 엔진으로 폴백합니다. C++ 모듈을 빌드해야 합니다:\n"
                "cd transit-routing/cpp_src && mkdir build && cd build && "
                "cmake .. -DCMAKE_BUILD_TYPE=Release && make"
            )
            # Fallback to Python engine
            service = PathfindingService()
            logger.warning("⚠️ Python 엔진으로 폴백 (성능 저하 가능)")
            return service

        except Exception as e:
            logger.error(
                f"C++ 엔진 초기화 실패: {e}\n" "Python 엔진으로 폴백합니다.",
                exc_info=True,
            )
            service = PathfindingService()
            logger.warning("⚠️ Python 엔진으로 폴백 (성능 저하 가능)")
            return service

    else:
        logger.info("Python 경로 탐색 엔진 사용")
        service = PathfindingService()
        logger.info("✓ PathfindingService 초기화 완료")
        return service


def get_engine_info() -> dict:
    """
    현재 사용 중인 엔진 정보 반환

    Returns:
        dict: 엔진 정보
    """
    service = get_pathfinding_service()

    engine_type = "cpp" if settings.USE_CPP_ENGINE else "python"
    engine_name = service.__class__.__name__

    return {
        "engine_type": engine_type,
        "engine_class": engine_name,
        "cpp_enabled": settings.USE_CPP_ENGINE,
        "description": (
            "C++ pathfinding_cpp 모듈 (고성능)"
            if engine_type == "cpp"
            else "Python McRaptor 엔진 (표준)"
        ),
    }
