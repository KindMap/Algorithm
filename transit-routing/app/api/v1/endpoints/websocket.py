"""
FAST API Websocket endpoint
"""

import logging
import uuid
from typing import Dict
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.pathfinding_service import PathfindingService
from app.services.guidance_service import GuidanceService
from app.db.redis_client import init_redis
from app.core.exceptions import KindMapException
from app.tasks.tasks import save_location_history, save_navigation_event

logger = logging.getLogger(__name__)

router = APIRouter()

# Lazy initialization 패턴: 서비스 인스턴스를 필요할 때 생성
_redis_client = None
_pathfinding_service = None
_guidance_service = None


def get_redis_client():
    """Redis 클라이언트를 반환 (싱글톤)"""
    global _redis_client
    if _redis_client is None:
        _redis_client = init_redis()
    return _redis_client


def get_pathfinding_service():
    """PathfindingService 인스턴스를 반환 (싱글톤)"""
    global _pathfinding_service
    if _pathfinding_service is None:
        _pathfinding_service = PathfindingService()
    return _pathfinding_service


def get_guidance_service():
    """GuidanceService 인스턴스를 반환 (싱글톤)"""
    global _guidance_service
    if _guidance_service is None:
        _guidance_service = GuidanceService(get_redis_client())
    return _guidance_service

class ConnectionManager:
    """websocket 연결 관리자"""

    # 추후 부하테스트를 통해 임계점을 찾고 수정하기
    # 임시 최대 동시 연결 수 => 100
    MAX_CONNECTIONS = 1000

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        # 기존 연결 확인 및 정리
        if user_id in self.active_connections:
            logger.warning(f"중복 연결 감지: {user_id}, 기존 연결을 종료합니다.")
            try:
                old_ws = self.active_connections[user_id]
                await old_ws.send_json(
                    {
                        "type": "disconnected",
                        "reason": "다른 기기에서 연결됨",
                        "code": "DUPLICATE_CONNECTION",
                    }
                )
                await old_ws.close()
            except Exception as e:
                logger.error(f"기존 연결 종료에 실패하였습니다: {e}")
            finally:
                del self.active_connections[user_id]

        # 연결 수 제한 체크
        if len(self.active_connections) >= self.MAX_CONNECTIONS:
            await websocket.close(
                code=1008, reason="서버 연결 한계에 도달했습니다."  # Policy Violation
            )
            logger.warning(
                f"연결 거부(한계 도달): user={user_id}, "
                f"current={len(self.active_connections)}"
            )
            raise Exception("최대 연결 수 초과")
        await websocket.accept()
        self.active_connections[user_id] = websocket
        logger.info(
            f"클라이언트 연결: {user_id}"
            f"총 {len(self.active_connections)}/{self.MAX_CONNECTIONS} 개 연결"
        )

    def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            logger.info(
                f"클라이언트 연결 해제: {user_id}, 남은 연결: {len(self.active_connections)}개"
            )

    async def send_message(self, user_id: str, message: dict):
        """특정 사용자에게 메시지 전송"""
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_json(message)
            except Exception as e:
                logger.error(f"메시지 전송 실패 (user={user_id}): {e}")
                self.disconnect(user_id)

    async def send_error(self, user_id: str, error_message: str, code: str = None):
        """에러 메시지 전송"""
        await self.send_message(
            user_id,
            {
                "type": "error",
                "message": error_message,
                "code": code,
                "timestamp": str(uuid.uuid4()),
            },
        )

    def get_connection_count(self) -> int:
        """활성 연결 수 반환"""
        return len(self.active_connections)


manager = ConnectionManager()


@router.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    """
    Websocket main endpoint

    /api/v1/ws/{user_id}

    핵심 기능:
    - 실시간 위치 업데이트
    - 경로 안내 메시지
    - 경로 이탈 감지
    - 도착 감지
    - 경로 재계산
    - 경로 변경 (상위 3개 중 선택)
    """

    await manager.connect(websocket, user_id)

    try:
        # 연결 성공 메시지
        await manager.send_message(
            user_id,
            {
                "type": "connected",
                "user_id": user_id,
                "message": "서버 연결 성공",
                "server_version": "4.0.0",
            },
        )

        while True:
            # 클라이언트로부터 메시지 수신
            data = await websocket.receive_json()
            message_type = data.get("type")

            logger.debug(f"메시지 수신: user={user_id}, type={message_type}")

            # 메시지 타입별 처리
            if message_type == "start_navigation":
                await handle_start_navigation(user_id, data, get_pathfinding_service())

            elif message_type == "location_update":
                await handle_location_update(user_id, data, get_guidance_service())

            elif message_type == "switch_route":
                await handle_switch_route(user_id, data)

            elif message_type == "recalculate_route":
                await handle_recalculate_route(
                    user_id, data, get_pathfinding_service(), get_guidance_service()
                )

            elif message_type == "end_navigation":
                await handle_end_navigation(user_id)

            elif message_type == "ping":
                await manager.send_message(user_id, {"type": "pong"})

            else:
                await manager.send_error(
                    user_id,
                    f"알 수 없는 메시지 타입: {message_type}",
                    "UNKNOWN_MESSAGE_TYPE",
                )

    except WebSocketDisconnect:
        logger.info(f"WebSocket 정상 종료: {user_id}")
        manager.disconnect(user_id)
    except Exception as e:
        logger.error(f"WebSocket 오류 (user={user_id}): {e}", exc_info=True)
        try:
            await manager.send_error(
                user_id, "서버 오류가 발생했습니다", "INTERNAL_SERVER_ERROR"
            )
        except:
            pass
        manager.disconnect(user_id)


async def handle_start_navigation(
    user_id: str, data: dict, pathfinding_service: PathfindingService
):
    """
    상위 3개 경로를 계산하여 반환
    """
    origin_name = data.get("origin")
    destination_name = data.get("destination")
    disability_type = data.get("disability_type", "PHY")

    if not origin_name or not destination_name:
        await manager.send_error(
            user_id, "출발지와 목적지가 필요합니다", "MISSING_PARAMETERS"
        )
        return

    logger.info(
        f"경로 계산 요청: user={user_id}, {origin_name} → {destination_name}, type={disability_type}"
    )

    try:
        route_data = pathfinding_service.calculate_route(
            origin_name, destination_name, disability_type
        )

        route_id = str(uuid.uuid4())
        route_data["route_id"] = route_id

        # Redis 세션 생성
        get_redis_client().create_session(user_id, route_data)

        # 클라이언트에 경로 정보 전송
        await manager.send_message(
            user_id,
            {
                "type": "route_calculated",
                "route_id": route_id,
                "origin": route_data["origin"],
                "origin_cd": route_data["origin_cd"],
                "destination": route_data["destination"],
                "destination_cd": route_data["destination_cd"],
                "routes": route_data["routes"],
                "total_routes_found": route_data["total_routes_found"],
                "routes_returned": route_data["routes_returned"],
                "selected_route_rank": 1,
            },
        )

        # 비동기 이벤트 저장
        save_navigation_event.delay(user_id, "route_calculated", route_data, route_id)

        logger.info(
            f"경로 계산 완료: route_id={route_id}, {route_data['routes_returned']}개 경로 반환"
        )

    except KindMapException as e:
        await manager.send_error(user_id, e.message, e.code)
        logger.error(f"경로 계산 실패 (user={user_id}): {e.message}")
    except Exception as e:
        await manager.send_error(
            user_id, "경로 계산 중 오류 발생", "ROUTE_CALCULATION_ERROR"
        )
        logger.error(f"예상치 못한 오류 (user={user_id}): {e}", exc_info=True)


async def handle_location_update(
    user_id: str, data: dict, guidance_service: GuidanceService
):
    """
    위치 업데이트 및 실시간 경로 안내

    - 현재 위치 파악
    - 다음 역까지 거리 계산
    - 환승 안내
    - 경로 이탈 감지
    - 도착 감지
    """
    lat = data.get("latitude")
    lon = data.get("longitude")
    accuracy = data.get("accuracy", 50)

    if lat is None or lon is None:
        await manager.send_error(
            user_id, "위도/경도 정보가 필요합니다", "MISSING_LOCATION"
        )
        return

    # 세션 확인
    session = get_redis_client().get_session(user_id)
    if not session:
        await manager.send_error(
            user_id,
            "활성 세션이 없습니다. 먼저 경로를 설정하세요.",
            "NO_ACTIVE_SESSION",
        )
        return

    logger.debug(
        f"위치 업데이트: user={user_id}, lat={lat:.6f}, lon={lon:.6f}, accuracy={accuracy}m"
    )

    try:
        # 실시간 경로 안내 계산
        guidance = guidance_service.get_navigation_guidance(user_id, lat, lon)

        # 경로 이탈 감지
        if guidance.get("recalculate"):
            await manager.send_message(
                user_id,
                {
                    "type": "route_deviation",
                    "message": guidance["message"],
                    "current_location": guidance.get("current_location"),
                    "nearest_station": guidance.get("nearest_station"),
                    "suggested_action": "재계산을 권장합니다",
                },
            )
            save_navigation_event.delay(
                user_id, "deviation", guidance, session["route_id"]
            )
            logger.warning(
                f"경로 이탈 감지: user={user_id}, nearest={guidance.get('nearest_station')}"
            )
            return

        # 목적지 도착
        if guidance.get("arrived"):
            await manager.send_message(
                user_id,
                {
                    "type": "arrival",
                    "message": guidance["message"],
                    "destination": guidance["destination"],
                    "destination_cd": session.get("destination_cd"),
                },
            )
            save_navigation_event.delay(
                user_id, "arrival", guidance, session["route_id"]
            )
            logger.info(
                f"목적지 도착: user={user_id}, destination={guidance['destination']}"
            )
            return

        # 일반 경로 안내
        await manager.send_message(
            user_id,
            {
                "type": "navigation_update",
                "current_station": guidance["current_station"],
                "current_station_name": guidance["current_station_name"],
                "next_station": guidance.get("next_station"),
                "next_station_name": guidance.get("next_station_name"),
                "distance_to_next": guidance.get("distance_to_next"),
                "remaining_stations": guidance["remaining_stations"],
                "is_transfer": guidance.get("is_transfer", False),
                "transfer_from_line": guidance.get("transfer_from_line"),
                "transfer_to_line": guidance.get("transfer_to_line"),
                "message": guidance["message"],
                "progress_percent": guidance.get("progress_percent", 0),
            },
        )

        # 비동기 위치 이력 저장
        save_location_history.delay(user_id, lat, lon, accuracy, session["route_id"])

    except KindMapException as e:
        await manager.send_error(user_id, e.message, e.code)
        logger.error(f"경로 안내 실패 (user={user_id}): {e.message}")
    except Exception as e:
        await manager.send_error(user_id, "경로 안내 중 오류 발생", "NAVIGATION_ERROR")
        logger.error(f"경로 안내 오류 (user={user_id}): {e}", exc_info=True)


async def handle_switch_route(user_id: str, data: dict):
    """
    경로 변경 (상위 3개 중 선택)
    """
    target_rank = data.get("target_rank")

    if not target_rank or target_rank not in [1, 2, 3]:
        await manager.send_error(
            user_id, "유효하지 않은 경로 순위입니다 (1-3)", "INVALID_ROUTE_RANK"
        )
        return

    logger.info(f"경로 변경 요청: user={user_id}, target_rank={target_rank}")

    try:
        success = get_redis_client().switch_route(user_id, target_rank)

        if success:
            session = get_redis_client().get_session(user_id)

            await manager.send_message(
                user_id,
                {
                    "type": "route_switched",
                    "selected_route_rank": target_rank,
                    "route_sequence": session["route_sequence"],
                    "route_lines": session["route_lines"],
                    "total_time": session["total_time"],
                    "transfers": session["transfers"],
                    "transfer_stations": session["transfer_stations"],
                    "message": f"{target_rank}순위 경로로 변경되었습니다",
                },
            )

            logger.info(f"경로 변경 완료: user={user_id}, rank={target_rank}")
        else:
            await manager.send_error(
                user_id, "경로 변경에 실패했습니다", "ROUTE_SWITCH_FAILED"
            )

    except Exception as e:
        logger.error(f"경로 변경 오류 (user={user_id}): {e}", exc_info=True)
        await manager.send_error(
            user_id, "경로 변경 중 오류 발생", "ROUTE_SWITCH_ERROR"
        )


async def handle_recalculate_route(
    user_id: str,
    data: dict,
    pathfinding_service: PathfindingService,
    guidance_service: GuidanceService,
):
    """
    현재 위치에서 목적지까지 새로운 경로 탐색
    """
    session = get_redis_client().get_session(user_id)

    if not session:
        await manager.send_error(user_id, "활성 세션이 없습니다", "NO_ACTIVE_SESSION")
        return

    lat = data.get("latitude")
    lon = data.get("longitude")
    disability_type = data.get("disability_type", "PHY")

    if lat is None or lon is None:
        await manager.send_error(
            user_id, "현재 위치 정보가 필요합니다", "MISSING_LOCATION"
        )
        return

    logger.info(f"경로 재계산 요청: user={user_id}")

    try:
        # 현재 위치에서 가장 가까운 역 찾기
        current_station_name = guidance_service.find_nearest_station_name(lat, lon)
        destination_name = session["destination"]

        logger.info(f"재계산 시작: {current_station_name} → {destination_name}")

        # 새 경로 계산
        route_data = pathfinding_service.calculate_route(
            current_station_name, destination_name, disability_type
        )

        route_id = str(uuid.uuid4())
        route_data["route_id"] = route_id

        # 세션 업데이트
        get_redis_client().create_session(user_id, route_data)

        await manager.send_message(
            user_id,
            {
                "type": "route_recalculated",
                "route_id": route_id,
                "origin": route_data["origin"],
                "origin_cd": route_data["origin_cd"],
                "destination": route_data["destination"],
                "destination_cd": route_data["destination_cd"],
                "routes": route_data["routes"],
                "total_routes_found": route_data["total_routes_found"],
                "routes_returned": route_data["routes_returned"],
                "selected_route_rank": 1,
                "message": "경로가 재계산되었습니다",
            },
        )

        save_navigation_event.delay(user_id, "recalculate", route_data, route_id)
        logger.info(f"경로 재계산 완료: route_id={route_id}")

    except KindMapException as e:
        await manager.send_error(user_id, e.message, e.code)
        logger.error(f"경로 재계산 실패 (user={user_id}): {e.message}")
    except Exception as e:
        await manager.send_error(
            user_id, "경로 재계산 중 오류 발생", "RECALCULATION_ERROR"
        )
        logger.error(f"재계산 오류 (user={user_id}): {e}", exc_info=True)


async def handle_end_navigation(user_id: str):
    """
    세션 삭제 및 종료 이벤트 기록
    """
    session = get_redis_client().get_session(user_id)

    if session:
        route_id = session.get("route_id")

        # Redis 세션 삭제 => 내브 구현에 직접 접근하는 방식은 위험
        # get_redis_client().redis_client.delete(f"session:{user_id}")
        get_redis_client().delete_session(user_id)  # => 캡슐화 유지

        # 종료 이벤트 저장
        save_navigation_event.delay(user_id, "navigation_ended", {}, route_id)

        await manager.send_message(
            user_id,
            {
                "type": "navigation_ended",
                "message": "내비게이션을 종료했습니다",
                "route_id": route_id,
            },
        )

        logger.info(f"내비게이션 종료: user={user_id}, route_id={route_id}")
    else:
        await manager.send_error(user_id, "활성 세션이 없습니다", "NO_ACTIVE_SESSION")
