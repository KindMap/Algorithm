from flask_socketio import emit, disconnect, join_room, leave_room
from flask import request
from navigation_service import NavigationService
from tasks import save_location_history
import json
import logging
import uuid

logger = logging.getLogger(__name__)


def register_socketio_handlers(socketio, redis_client):
    nav_service = NavigationService(redis_client)

    @socketio.on("connect")
    def handle_connect():
        user_id = request.sid
        join_room(user_id)
        logger.info(f"User connected: {user_id}")
        emit("connected", {"user_id": user_id})

    @socketio.on("disconnect")
    def handle_disconnect():
        user_id = request.sid
        leave_room(user_id)
        logger.info(f"User disconnected: {user_id}")

    @socketio.on("start_navigation")
    def handle_start_navigation(data):
        user_id = request.sid
        start = data["start"]
        destination = data["destination"]
        disability_type = data["disability_type"]

        if disability_type == None:  # 기본값 : PHY
            disability_type = "PHY"

        route_data = nav_service.calculate_route(start, destination, disability_type)

        if route_data:
            route_data["route_id"] = str(uuid.uuid4())
            redis_client.create_session(user_id, route_data)
            emit(
                "route_calculated",
                {
                    "route_id": route_data["route_id"],
                    "start": route_data["start"],
                    "destination": route_data["destination"],
                    "route_sequence": route_data["route_sequence"],
                    "total_time": route_data["total_time"],
                    "transfers": route_data["transfers"],
                    "transfer_stations": route_data["transfer_stations"],
                },
                room=user_id,
            )
        else:
            emit("error", {"message": "경로를 찾을 수 없습니다"}, room=user_id)

    @socketio.on("update_location")
    def handle_location_update(data):
        user_id = request.sid
        lat = data["latitude"]
        lon = data["longitude"]
        accuracy = data.get("accuracy", 50)

        guidance = nav_service.get_navigation_guidance(user_id, lat, lon)

        if guidance:
            # 에러 처리
            if "error" in guidance:
                emit("error", {"message": guidance["error"]}, room=user_id)
                return

            # 경로 이탈
            if guidance.get("recalculate"):
                emit(
                    "route_deviation",
                    {
                        "message": guidance["message"],
                        "current_location": guidance.get("current_location"),
                    },
                    room=user_id,
                )
                return

            # 목적지 도착
            if guidance.get("arrived"):
                emit(
                    "arrival",
                    {
                        "message": guidance["message"],
                        "current_station": guidance["current_station"],
                    },
                    room=user_id,
                )

                # 세션 종료 처리 추가하기 or client측에서 추가하기
                return

            # 일반 경로 안내
            emit(
                "navigation_update",
                {
                    "current_station": guidance["current_station"],
                    "next_station": guidance["next_station"],
                    "distance_to_next": guidance["distance_to_next"],
                    "remaining_stations": guidance["remaining_stations"],
                    "is_transfer": guidance["is_transfer"],
                    "message": guidance["message"],
                },
                room=user_id,
            )

            # 비동기로 위치 이력 저장
            save_location_history.delay(
                user_id, lat, lon, accuracy, guidance.get("route_id")
            )

    @socketio.on("recalculate_route")
    def handle_recalculate_route(data):
        """경로 재탐색 요청 처리"""
        user_id = request.sid
        session = redis_client.get_session(user_id)

        if not session:
            emit("error", {"message": "활성 세션이 없습니다"}, room=user_id)
            return

        lat = data["latitude"]
        lon = data["longitude"]
        destination = session["destination"]
        disability_type = data["disability_type"]

        # 현재 위치에서 가장 가까운 역을 새 출발지로 설정
        current_station = nav_service._find_nearest_station(lat, lon)

        route_data = nav_service.calculate_route(
            current_station, destination, disability_type
        )

        if route_data:
            route_data["route_id"] = str(uuid.uuid4())
            redis_client.create_session(user_id, route_data)
            emit(
                "route_recalculated",
                {
                    "route_id": route_data["route_id"],
                    "start": route_data["start"],
                    "destination": route_data["destination"],
                    "route_sequence": route_data["route_sequence"],
                    "total_time": route_data["total_time"],
                    "transfers": route_data["transfers"],
                    "transfer_stations": route_data["transfer_stations"],
                },
                room=user_id,
            )
        else:
            emit("error", {"message": "경로를 재계산할 수 없습니다"}, room=user_id)

    @socketio.on("end_navigation")
    def handle_end_navigation():
        """내비게이션 종료"""
        user_id = request.sid
        session = redis_client.get_session(user_id)

        if session:
            # Redis에서 세션 삭제
            redis_client.redis_client.delete(f"session:{user_id}")
            emit(
                "navigation_ended",
                {"message": "내비게이션을 종료했습니다"},
                room=user_id,
            )
            logger.info(f"Navigation ended for user: {user_id}")
        else:
            emit("error", {"message": "활성 세션이 없습니다"}, room=user_id)
