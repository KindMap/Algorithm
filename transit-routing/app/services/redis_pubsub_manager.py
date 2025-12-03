# 수평 확장 환경에서 백엔드 인스턴스 간 메시지 라우팅
import asyncio
import json
import logging
from typing import Callable, Optional
import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)


class RedisPubSubManager:
    """Redis Pub/Sub 기반 메시지 브로드캐스트 관리자"""

    def __init__(self):
        self.redis_url = f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/0"
        self.channel = settings.REDIS_PUBSUB_CHANNEL
        self.enabled = settings.REDIS_PUBSUB_ENABLED

        # 연결 풀 설정 (성능 최적화)
        self.redis_pool: Optional[aioredis.ConnectionPool] = None
        self.pubsub_client: Optional[aioredis.Redis] = None
        self.pubsub: Optional[aioredis.client.PubSub] = None

        # 메시지 핸들러 (ConnectionManager에서 주입받음)
        self.message_handler: Optional[Callable] = None

        # 리스너 태스크
        self._listener_task: Optional[asyncio.Task] = None
        self._is_listening = False

    async def initialize(self):
        """(비동기)Redis 연결 풀 초기화"""
        if not self.enabled:
            logger.info("Redis Pub/Sub 비활성화")
            return

        try:
            # create connection pool
            self.redis_pool = aioredis.ConnectionPool.from_url(
                self.redis_url,
                max_connections=settings.REDIS_MAX_CONNECTIONS,
                decode_responses=True,  # 자동 UTF-8 decoding
            )

            # Pub/Sub client 생성
            self.pubsub_client = aioredis.Redis(connection_pool=self.redis_pool)
            self.pubsub = self.pubsub_client.pubsub()

            # subscribe channel
            await self.pubsub.subscribe(self.channel)
            logger.info(f"Redis Pub/Sub 초기화 완료: channel={self.channel}")

        except Exception as e:
            logger.error(f"Redis Pub/Sub 초기화 실패: {e}")
            raise

    async def publish(self, user_id: str, message: dict):
        """(비동기)Redis 채널에 메시지 발행"""
        if not self.enabled or not self.pubsub_client:
            logger.warning("Redis Pub/Sub이 초기화되지 않았습니다")
            return

        try:
            payload = {
                "target_user_id": user_id,
                "message": message,
                "timestamp": message.get("timestamp", ""),
            }

            # JSON 직렬화 후 발행
            await self.pubsub_client.publish(
                self.channel, json.dumps(payload, ensure_ascii=False)
            )

            logger.debug(f"메시지 발행: user_id={user_id}, type={message.get('type')}")

        except Exception as e:
            logger.error(f"메시지 발행 실패: {e}", exc_info=True)

    async def start_listening(self, message_handler: Callable):
        """(비동기)백그라운드에서 Redis 메시지 수신 시작"""
        if not self.enabled or not self.pubsub:
            logger.warning("Redis Pub/Sub이 비활성화되어 있거나 초기화되지 않았습니다")
            return

        self.message_handler = message_handler
        self._is_listening = True

        # 백그라운드 태스크로 리스너 실행
        self._listener_task = asyncio.create_task(self._listen_loop())
        logger.info(f"Redis Pub/Sub 리스너 시작: channel={self.channel}")

    async def _listen_loop(self):
        """(비동기)메시지 수신 루프 (무한 루프)"""
        try:
            async for message in self.pubsub.listen():
                if not self._is_listening:
                    break
                # message 타입만 처리 => subscribe/unsubscribe 메시지 무시
                if message["type"] == "message":
                    await self._handle_message(message["data"])

        except asyncio.CancelledError:
            logger.info("Redis Pub/Sub 리스너가 취소되었습니다")
        except Exception as e:
            logger.error(f"Redis Pub/Sub 리스너 오류: {e}", exc_info=True)

    async def _handle_message(self, data: str):
        """(비동기)수신한 메시지 처리"""
        try:
            # JSON 역직렬화
            payload = json.loads(data)
            target_user_id = payload["target_user_id"]
            message = payload["message"]

            # ConnectionManager의 핸들러 호출
            if self.message_handler:
                await self.message_handler(target_user_id, message)

        except json.JSONDecodeError as e:
            logger.error(f"Redis 메시지 파싱 실패: {e}")
        except Exception as e:
            logger.error(f"메시지 처리 중 오류: {e}", exc_info=True)

    async def stop_listening(self):
        """(비동기)리스너 중지"""
        self._is_listening = False

        if self._listener_task:
            # 백그라운드에 남아있는 task가 있다면 cancel
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass

        logger.info("Redis Pub/Sub 리스너 중지됨")

    async def close(self):
        """(비동기)Redis 연결 종료"""
        await self.stop_listening()

        if self.pubsub:
            await self.pubsub.unsubscribe(self.channel)
            await self.pubsub.close()

        if self.pubsub_client:
            await self.pubsub_client.close()

        if self.redis_pool:
            await self.redis_pool.disconnect()

        logger.info("Redis Pub/Sub 연결 종료됨")


# singleton instance
_pubsub_manager: Optional[RedisPubSubManager] = None


def get_pubsub_manager() -> RedisPubSubManager:
    """Redis Pub/Sub instance 반환"""
    global _pubsub_manager
    if _pubsub_manager is None:
        _pubsub_manager = RedisPubSubManager()
    return _pubsub_manager
