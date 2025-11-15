import redis
import os
import json
from typing import Optional, Dict
from datetime import datetime


class RedisSessionManager:
    def __init__(self):
        self.redis_client = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            db=0,
            decode_responses=True,
        )

    def create_session(self, user_id: str, route_data: dict) -> bool:
        """
        경로 안내를 관리할 유저별 세션 생성

        Args:
            user_id (str): 사용자 식별 ID
            route_data (dict): 경로 데이터, 지하철 역 dictionary

        Returns:
            bool: 세션 생성 성공/실패
        """
        session_key = f"session:{user_id}"
        session_data = {
            "route_id": route_data.get("route_id"),
            "current_station": route_data.get("start"),
            "destination": route_data.get("destination"),
            "route_sequence": json.dumps(route_data.get("route_sequence", [])),
            "transfer_stations": json.dumps(route_data.get("transfer_stations", [])),
            "last_update": datetime.now().isoformat(),
        }
        return self.redis_client.setex(
            session_key, 14400, json.dumps(session_data)  # TTL : 4 hour
        )

    def get_session(self, user_id: str) -> Optional[Dict]:
        """user_id를 받아 세션 가져오기"""
        session_key = f"session:{user_id}"
        data = self.redis_client.get(session_key)
        if data:
            session = json.loads(data)
            # session에 해당 필드가 없을 경우 대비
            session["route_sequence"] = json.loads(session.get("route_sequence", "[]"))
            session["transfer_stations"] = json.loads(
                session.get("transfer_stations", "[]")
            )
            return session
        return None

    def update_location(self, user_id: str, current_station: str):
        session = self.get_session(user_id)
        if session:
            session["current_station"] = current_station
            session["last_update"] = datetime.now().isoformat()
            session["route_sequence"] = json.dumps(session["route_sequence"])
            session["transfer_stations"] = json.dumps(session["transfer_stations"])
            self.redis_client.setex(f"session:{user_id}", 14400, json.dumps(session))


def init_redis():
    return RedisSessionManager()
