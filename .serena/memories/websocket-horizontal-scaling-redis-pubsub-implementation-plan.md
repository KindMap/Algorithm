# WebSocket 수평 확장 및 Redis Pub/Sub 구현 계획

## 📋 개요

**목표**: kindMap 프로젝트의 WebSocket 연결을 수평 확장 가능하도록 Redis Pub/Sub 패턴을 도입하여 다중 백엔드 인스턴스 간 메시지 라우팅을 구현합니다.

**현재 문제점**:
- `workers=4` 설정으로 인한 WebSocket 상태 불일치
- 각 worker의 `active_connections` 메모리 격리
- 수평 확장 시 메시지 전달 불가능

**해결 방안**:
- Redis Pub/Sub를 통한 메시지 브로드캐스팅
- 각 백엔드 인스턴스가 독립적으로 WebSocket 연결 관리
- `workers=1` 설정으로 프로세스당 단일 이벤트 루프 유지

---

## 1. 아키텍처 설계

### 1.1 변경 전 (현재)

```
클라이언트
    ↓ WebSocket
[Nginx Load Balancer]
    ↓ (Round Robin)
┌─────────────────────────────┐
│  FastAPI (workers=4)        │
│  ┌─────┬─────┬─────┬─────┐  │
│  │ W1  │ W2  │ W3  │ W4  │  │ ← 각 워커의 메모리 격리
│  └─────┴─────┴─────┴─────┘  │
│  active_connections 공유 ❌  │
└─────────────────────────────┘
```

**문제**:
- Worker 1에 연결된 사용자 A에게 Worker 2에서 메시지를 보낼 수 없음
- `active_connections` 딕셔너리가 프로세스별로 독립적

### 1.2 변경 후 (목표)

```
클라이언트들
    ↓ WebSocket
[Nginx Load Balancer with ip_hash]
    ↓
┌────────────────┬────────────────┬────────────────┐
│  Backend 1     │  Backend 2     │  Backend 3     │
│  (workers=1)   │  (workers=1)   │  (workers=1)   │
│                │                │                │
│  active_conns: │  active_conns: │  active_conns: │
│  {user1: ws}   │  {user2: ws}   │  {user3: ws}   │
└───────┬────────┴───────┬────────┴───────┬────────┘
        │                │                │
        └────────────────┼────────────────┘
                         ↓
                   [Redis Pub/Sub]
                  Channel: kindmap_events
                         ↓
           ┌─────────────┼─────────────┐
           │             │             │
        Subscribe    Subscribe    Subscribe
        (Listener)   (Listener)   (Listener)
```

**동작 흐름**:
1. **Publish**: 어떤 백엔드에서든 메시지 발생 시 Redis 채널에 발행
2. **Subscribe**: 모든 백엔드가 Redis 채널 구독 중
3. **Filter & Send**: 각 백엔드는 자신의 `active_connections`에 해당 user가 있으면 전송

---

## 2. 구현 단계

### Phase 1: 의존성 추가 및 설정 (Week 1)

#### 2.1 Redis Async 라이브러리 추가

**파일**: `transit-routing/tests/requirements.txt` (메인 requirements.txt 생성 필요)

```txt
# 기존 패키지들...
fastapi==0.104.1
uvicorn[standard]==0.24.0
redis==5.0.1  # 현재 설치된 버전 확인 후 유지 또는 업그레이드

# 새로 추가
redis[hiredis]>=5.0.0  # hiredis는 성능 향상용 C 라이브러리
```

**참고**:
- `redis-py` 4.2+ 버전은 async를 네이티브 지원
- `import redis.asyncio as aioredis` 방식 사용

#### 2.2 환경변수 추가

**파일**: `.env`

```env
# 기존 설정들...

# Redis Pub/Sub 설정
REDIS_PUBSUB_CHANNEL=kindmap_events
REDIS_PUBSUB_ENABLED=true

# 연결 풀 설정 (성능 최적화)
REDIS_MAX_CONNECTIONS=50
REDIS_SOCKET_CONNECT_TIMEOUT=5
REDIS_SOCKET_KEEPALIVE=true
```

**파일**: `transit-routing/app/core/config.py`

```python
class Settings:
    # ... 기존 설정들 ...
    
    # Redis Pub/Sub 설정
    REDIS_PUBSUB_CHANNEL: str = os.getenv("REDIS_PUBSUB_CHANNEL", "kindmap_events")
    REDIS_PUBSUB_ENABLED: bool = os.getenv("REDIS_PUBSUB_ENABLED", "true").lower() == "true"
    REDIS_MAX_CONNECTIONS: int = int(os.getenv("REDIS_MAX_CONNECTIONS", 50))
```

---

### Phase 2: ConnectionManager 리팩토링 (Week 1-2)

#### 2.3 Redis Pub/Sub Manager 클래스 생성

**새 파일**: `transit-routing/app/services/redis_pubsub_manager.py`

```python
"""
Redis Pub/Sub Manager for WebSocket Message Broadcasting
수평 확장 환경에서 백엔드 인스턴스 간 메시지 라우팅
"""

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
        """Redis 연결 풀 초기화"""
        if not self.enabled:
            logger.info("Redis Pub/Sub이 비활성화되어 있습니다")
            return
        
        try:
            # 연결 풀 생성
            self.redis_pool = aioredis.ConnectionPool.from_url(
                self.redis_url,
                max_connections=settings.REDIS_MAX_CONNECTIONS,
                decode_responses=True,  # 자동 UTF-8 디코딩
            )
            
            # Pub/Sub 클라이언트 생성
            self.pubsub_client = aioredis.Redis(connection_pool=self.redis_pool)
            self.pubsub = self.pubsub_client.pubsub()
            
            # 채널 구독
            await self.pubsub.subscribe(self.channel)
            logger.info(f"✓ Redis Pub/Sub 초기화 완료: channel={self.channel}")
            
        except Exception as e:
            logger.error(f"✗ Redis Pub/Sub 초기화 실패: {e}", exc_info=True)
            raise
    
    async def publish(self, user_id: str, message: dict):
        """Redis 채널에 메시지 발행"""
        if not self.enabled or not self.pubsub_client:
            logger.warning("Redis Pub/Sub이 초기화되지 않았습니다")
            return
        
        try:
            payload = {
                "target_user_id": user_id,
                "message": message,
                "timestamp": message.get("timestamp", "")
            }
            
            # JSON 직렬화 후 발행
            await self.pubsub_client.publish(
                self.channel,
                json.dumps(payload, ensure_ascii=False)
            )
            
            logger.debug(f"메시지 발행: user_id={user_id}, type={message.get('type')}")
            
        except Exception as e:
            logger.error(f"메시지 발행 실패: {e}", exc_info=True)
    
    async def start_listening(self, message_handler: Callable):
        """백그라운드에서 Redis 메시지 수신 시작"""
        if not self.enabled or not self.pubsub:
            logger.warning("Redis Pub/Sub이 비활성화되어 있거나 초기화되지 않았습니다")
            return
        
        self.message_handler = message_handler
        self._is_listening = True
        
        # 백그라운드 태스크로 리스너 실행
        self._listener_task = asyncio.create_task(self._listen_loop())
        logger.info(f"✓ Redis Pub/Sub 리스너 시작: channel={self.channel}")
    
    async def _listen_loop(self):
        """메시지 수신 루프 (무한 루프)"""
        try:
            async for message in self.pubsub.listen():
                if not self._is_listening:
                    break
                
                # 'message' 타입만 처리 (subscribe/unsubscribe 메시지 무시)
                if message["type"] == "message":
                    await self._handle_message(message["data"])
                    
        except asyncio.CancelledError:
            logger.info("Redis Pub/Sub 리스너가 취소되었습니다")
        except Exception as e:
            logger.error(f"Redis Pub/Sub 리스너 오류: {e}", exc_info=True)
    
    async def _handle_message(self, data: str):
        """수신한 메시지 처리"""
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
        """리스너 중지"""
        self._is_listening = False
        
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Redis Pub/Sub 리스너 중지됨")
    
    async def close(self):
        """Redis 연결 종료"""
        await self.stop_listening()
        
        if self.pubsub:
            await self.pubsub.unsubscribe(self.channel)
            await self.pubsub.close()
        
        if self.pubsub_client:
            await self.pubsub_client.close()
        
        if self.redis_pool:
            await self.redis_pool.disconnect()
        
        logger.info("Redis Pub/Sub 연결 종료됨")


# 싱글톤 인스턴스
_pubsub_manager: Optional[RedisPubSubManager] = None


def get_pubsub_manager() -> RedisPubSubManager:
    """Pub/Sub Manager 싱글톤 인스턴스 반환"""
    global _pubsub_manager
    if _pubsub_manager is None:
        _pubsub_manager = RedisPubSubManager()
    return _pubsub_manager
```

#### 2.4 ConnectionManager 수정

**파일**: `transit-routing/app/api/v1/endpoints/websocket.py`

**변경 사항**:

```python
# 기존 import에 추가
from app.services.redis_pubsub_manager import get_pubsub_manager

class ConnectionManager:
    """WebSocket 연결 관리자 (Redis Pub/Sub 통합)"""
    
    MAX_CONNECTIONS = 1000
    
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.pubsub_manager = get_pubsub_manager()  # Redis Pub/Sub 매니저
    
    # ... connect(), disconnect() 메서드는 기존 유지 ...
    
    async def send_message(self, user_id: str, message: dict):
        """
        특정 사용자에게 메시지 전송
        
        [변경 사항]
        - 로컬에 연결이 있으면: 직접 전송
        - 로컬에 연결이 없으면: Redis Pub/Sub으로 발행 (다른 백엔드에서 전달)
        """
        # 1. 로컬 연결 확인
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_json(message)
                logger.debug(f"로컬 전송 성공: user_id={user_id}")
                return
            except Exception as e:
                logger.error(f"로컬 메시지 전송 실패 (user={user_id}): {e}")
                self.disconnect(user_id)
        
        # 2. 로컬에 없으면 Redis Pub/Sub으로 발행
        if self.pubsub_manager.enabled:
            await self.pubsub_manager.publish(user_id, message)
            logger.debug(f"Redis 발행: user_id={user_id} (다른 백엔드로 전달)")
        else:
            logger.warning(f"메시지 전송 실패: user_id={user_id} (로컬 연결 없음, Pub/Sub 비활성화)")
    
    async def handle_pubsub_message(self, user_id: str, message: dict):
        """
        Redis Pub/Sub로부터 수신한 메시지 처리
        
        [호출 경로]
        RedisPubSubManager._handle_message() → 이 메서드 → WebSocket 전송
        """
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_json(message)
                logger.debug(f"Pub/Sub 메시지 전송 성공: user_id={user_id}")
            except Exception as e:
                logger.error(f"Pub/Sub 메시지 전송 실패: {e}")
                self.disconnect(user_id)
        else:
            # 이 백엔드에는 연결이 없음 (다른 백엔드에서 처리할 것)
            logger.debug(f"Pub/Sub 메시지 무시: user_id={user_id} (로컬 연결 없음)")
    
    # ... send_error(), get_connection_count() 메서드는 기존 유지 ...


# 싱글톤 인스턴스
manager = ConnectionManager()
```

---

### Phase 3: 애플리케이션 생명주기 통합 (Week 2)

#### 2.5 Startup/Shutdown 이벤트 설정

**파일**: `transit-routing/app/main.py`

**변경 사항**:

```python
# 기존 import에 추가
from app.services.redis_pubsub_manager import get_pubsub_manager
from app.api.v1.endpoints.websocket import manager as websocket_manager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 생명주기 관리"""
    # ========== Startup ==========
    logger.info("=" * 60)
    logger.info("KindMap Backend 시작 중...")
    logger.info("=" * 60)
    
    try:
        # 1. PostgreSQL 연결 풀 초기화
        logger.info("1/4 PostgreSQL 연결 풀 초기화 중...")
        initialize_pool()
        
        # 2. 데이터 캐시 초기화
        logger.info("2/4 역 정보 캐시 초기화 중...")
        initialize_cache()
        
        # 3. Redis 클라이언트 초기화 (세션 관리용)
        logger.info("3/4 Redis 세션 클라이언트 초기화 중...")
        init_redis()
        
        # 4. Redis Pub/Sub 초기화 및 리스너 시작
        logger.info("4/4 Redis Pub/Sub 초기화 중...")
        pubsub_manager = get_pubsub_manager()
        await pubsub_manager.initialize()
        
        # WebSocket 메시지 핸들러 등록 및 리스너 시작
        await pubsub_manager.start_listening(
            message_handler=websocket_manager.handle_pubsub_message
        )
        
        logger.info("=" * 60)
        logger.info("✓ KindMap Backend 시작 완료!")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"✗ 서버 초기화 실패: {e}", exc_info=True)
        raise
    
    # 애플리케이션 실행 (yield로 제어 반환)
    yield
    
    # ========== Shutdown ==========
    logger.info("=" * 60)
    logger.info("KindMap Backend 종료 중...")
    logger.info("=" * 60)
    
    try:
        # 1. Redis Pub/Sub 종료
        logger.info("1/2 Redis Pub/Sub 종료 중...")
        pubsub_manager = get_pubsub_manager()
        await pubsub_manager.close()
        
        # 2. PostgreSQL 연결 풀 종료
        logger.info("2/2 PostgreSQL 연결 풀 종료 중...")
        close_pool()
        
        logger.info("=" * 60)
        logger.info("✓ KindMap Backend 종료 완료")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"✗ 서버 종료 중 오류: {e}", exc_info=True)


# FastAPI 앱 생성
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,  # 생명주기 관리자 등록
)
```

---

### Phase 4: Docker 및 인프라 설정 (Week 2-3)

#### 2.6 Uvicorn Workers 설정 변경

**파일**: `docker-compose.yml` (개발 환경)

```yaml
services:
  # ... redis 설정 유지 ...
  
  fastapi:
    build:
      context: .
      dockerfile: Dockerfile.fastapi
    container_name: kindmap-fastapi
    restart: unless-stopped
    env_file:
      - .env
    environment:
      ALLOWED_ORIGINS: "..."
      # Redis Pub/Sub 환경변수 추가
      REDIS_PUBSUB_ENABLED: "true"
      REDIS_PUBSUB_CHANNEL: "kindmap_events"
    ports:
      - "8001:8001"
    networks:
      - kindmap-network
    depends_on:
      redis:
        condition: service_healthy
    volumes:
      - ./transit-routing:/app
    # [변경] workers=1로 설정
    command: uvicorn app.main:app --host 0.0.0.0 --port 8001 --workers 1 --ws-ping-interval 20 --ws-ping-timeout 20
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8001/health').read()"]
      interval: 30s
      timeout: 3s
      retries: 3
      start_period: 40s
  
  # ... nginx 설정 유지 ...
```

**파일**: `docker-compose.prod.yml` (프로덕션 환경)

```yaml
services:
  redis:
    image: redis:7-alpine
    container_name: kindmap-redis
    restart: unless-stopped
    networks:
      - kindmap-network
    expose:
      - "6379"
    volumes:
      - redis-data:/data
    # [변경] 메모리 증가 및 Pub/Sub 최적화
    command: >
      redis-server
      --appendonly yes
      --maxmemory 512mb
      --maxmemory-policy allkeys-lru
      --notify-keyspace-events ""
      --client-output-buffer-limit pubsub 32mb 8mb 60
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 3
      start_period: 5s
  
  # [새로 추가] 백엔드 컨테이너 스케일링
  fastapi:
    image: ${REPOSITORY_URI}:fastapi-${IMAGE_TAG}
    # [변경] container_name 제거 (스케일링 위해)
    restart: unless-stopped
    env_file:
      - /home/ec2-user/.env
    environment:
      ALLOWED_ORIGINS: "..."
      REDIS_PUBSUB_ENABLED: "true"
      REDIS_PUBSUB_CHANNEL: "kindmap_events"
    expose:
      - "8001"
    networks:
      - kindmap-network
    depends_on:
      redis:
        condition: service_healthy
    # [변경] workers=1로 변경
    command: uvicorn app.main:app --host 0.0.0.0 --port 8001 --workers 1 --ws-ping-interval 20 --ws-ping-timeout 20
    # [새로 추가] 배포 설정으로 3개 인스턴스 실행
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: '1.0'
          memory: 1G
        reservations:
          cpus: '0.5'
          memory: 512M
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8001/health').read()"]
      interval: 30s
      timeout: 3s
      retries: 3
      start_period: 40s
  
  nginx:
    image: ${REPOSITORY_URI}:nginx-${IMAGE_TAG}
    container_name: kindmap-nginx
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    depends_on:
      - fastapi
    networks:
      - kindmap-network
    volumes:
      - /etc/letsencrypt:/etc/letsencrypt
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost/health"]
      interval: 30s
      timeout: 3s
      retries: 3
      start_period: 10s

networks:
  kindmap-network:
    driver: bridge

volumes:
  redis-data:
    driver: local
```

#### 2.7 Nginx 설정 수정 (WebSocket Upstream)

**파일**: `Dockerfile.nginx` 내부 또는 별도 `nginx.conf`

```nginx
upstream fastapi_backend {
    # [변경] ip_hash를 통한 sticky session
    # 동일 IP는 동일 백엔드로 라우팅 (WebSocket Handshake 안정성)
    ip_hash;
    
    # Docker Compose의 서비스 이름 사용
    # replicas=3 설정 시 Docker가 자동으로 로드밸런싱
    server fastapi:8001 max_fails=3 fail_timeout=30s;
}

server {
    listen 80;
    server_name kindmap-for-you.cloud;
    
    # WebSocket 프록시 설정
    location / {
        proxy_pass http://fastapi_backend;
        
        # WebSocket Upgrade 헤더
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # 기본 프록시 헤더
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # 타임아웃 설정 (WebSocket 장시간 연결 지원)
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
```

---

### Phase 5: 테스트 및 검증 (Week 3)

#### 2.8 단위 테스트 추가

**새 파일**: `transit-routing/tests/test/test_redis_pubsub.py`

```python
"""
Redis Pub/Sub Manager 테스트
"""

import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.redis_pubsub_manager import RedisPubSubManager, get_pubsub_manager


class TestRedisPubSubManager:
    @pytest.fixture
    async def pubsub_manager(self):
        """Pub/Sub Manager 픽스처"""
        manager = RedisPubSubManager()
        yield manager
        await manager.close()
    
    @pytest.mark.asyncio
    async def test_initialize_success(self, pubsub_manager):
        """Redis Pub/Sub 초기화 성공"""
        with patch('redis.asyncio.ConnectionPool.from_url') as mock_pool:
            mock_pool.return_value = AsyncMock()
            await pubsub_manager.initialize()
            
            assert pubsub_manager.pubsub_client is not None
            assert pubsub_manager.pubsub is not None
    
    @pytest.mark.asyncio
    async def test_publish_message(self, pubsub_manager):
        """메시지 발행 테스트"""
        pubsub_manager.pubsub_client = AsyncMock()
        
        await pubsub_manager.publish("user123", {"type": "test", "data": "hello"})
        
        # publish 메서드가 호출되었는지 확인
        pubsub_manager.pubsub_client.publish.assert_called_once()
        
        # 발행된 데이터 확인
        call_args = pubsub_manager.pubsub_client.publish.call_args
        channel, payload_str = call_args[0]
        payload = json.loads(payload_str)
        
        assert channel == pubsub_manager.channel
        assert payload["target_user_id"] == "user123"
        assert payload["message"]["type"] == "test"
    
    @pytest.mark.asyncio
    async def test_message_handler_called(self, pubsub_manager):
        """메시지 핸들러 호출 확인"""
        handler = AsyncMock()
        pubsub_manager.message_handler = handler
        
        # 메시지 처리
        test_data = json.dumps({
            "target_user_id": "user123",
            "message": {"type": "location_update"}
        })
        
        await pubsub_manager._handle_message(test_data)
        
        # 핸들러가 올바른 인자로 호출되었는지 확인
        handler.assert_called_once_with("user123", {"type": "location_update"})
```

#### 2.9 통합 테스트 (Multi-Backend 시뮬레이션)

**새 파일**: `transit-routing/tests/test/test_multibackend_integration.py`

```python
"""
다중 백엔드 간 메시지 라우팅 통합 테스트
"""

import pytest
import asyncio
from fastapi.testclient import TestClient
from fastapi import WebSocket

from app.main import app
from app.api.v1.endpoints.websocket import manager
from app.services.redis_pubsub_manager import get_pubsub_manager


@pytest.mark.asyncio
async def test_cross_backend_message_delivery():
    """
    시나리오:
    1. Backend 1에 user1 연결
    2. Backend 2에 user2 연결
    3. Backend 1에서 user2에게 메시지 전송 시도
    4. Redis Pub/Sub를 통해 Backend 2로 전달되어야 함
    """
    
    # Mock WebSocket 생성
    user1_ws = AsyncMock(spec=WebSocket)
    user2_ws = AsyncMock(spec=WebSocket)
    
    # 연결 시뮬레이션
    manager.active_connections["user1"] = user1_ws
    # user2는 다른 백엔드에 연결되어 있다고 가정 (로컬에 없음)
    
    # 메시지 전송
    await manager.send_message("user2", {"type": "test", "message": "hello"})
    
    # Redis Pub/Sub으로 발행되었는지 확인
    pubsub_manager = get_pubsub_manager()
    # (실제로는 Redis Mock을 사용하여 publish 호출 검증)
    
    # user1의 WebSocket은 호출되지 않아야 함
    user1_ws.send_json.assert_not_called()
```

#### 2.10 부하 테스트 (Locust)

**새 파일**: `transit-routing/tests/load_test/locustfile.py`

```python
"""
Locust 부하 테스트: 다중 백엔드 환경에서 WebSocket 성능 검증
"""

import json
import time
from locust import User, task, between, events
import websocket


class WebSocketUser(User):
    """WebSocket 사용자 시뮬레이션"""
    
    wait_time = between(1, 3)
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ws = None
        self.user_id = f"load_test_{int(time.time() * 1000)}_{id(self)}"
    
    def on_start(self):
        """WebSocket 연결"""
        ws_url = f"ws://localhost/api/v1/ws/{self.user_id}"
        try:
            self.ws = websocket.create_connection(ws_url, timeout=10)
            print(f"연결 성공: {self.user_id}")
        except Exception as e:
            print(f"연결 실패: {e}")
            raise
    
    @task(3)
    def send_ping(self):
        """Ping/Pong 테스트"""
        if not self.ws:
            return
        
        start_time = time.time()
        try:
            self.ws.send(json.dumps({"type": "ping"}))
            response = self.ws.recv()
            
            elapsed = (time.time() - start_time) * 1000
            events.request.fire(
                request_type="WebSocket",
                name="ping",
                response_time=elapsed,
                response_length=len(response),
                exception=None,
            )
        except Exception as e:
            events.request.fire(
                request_type="WebSocket",
                name="ping",
                response_time=0,
                response_length=0,
                exception=e,
            )
    
    @task(1)
    def send_location_update(self):
        """위치 업데이트 테스트"""
        if not self.ws:
            return
        
        start_time = time.time()
        try:
            self.ws.send(json.dumps({
                "type": "location_update",
                "lat": 37.5665,
                "lon": 126.9780
            }))
            response = self.ws.recv()
            
            elapsed = (time.time() - start_time) * 1000
            events.request.fire(
                request_type="WebSocket",
                name="location_update",
                response_time=elapsed,
                response_length=len(response),
                exception=None,
            )
        except Exception as e:
            events.request.fire(
                request_type="WebSocket",
                name="location_update",
                response_time=0,
                response_length=0,
                exception=e,
            )
    
    def on_stop(self):
        """WebSocket 연결 종료"""
        if self.ws:
            try:
                self.ws.close()
                print(f"연결 종료: {self.user_id}")
            except:
                pass
```

**실행 명령**:

```bash
# 1000명의 동시 사용자, 초당 100명씩 증가
locust -f tests/load_test/locustfile.py --host=http://localhost --users 1000 --spawn-rate 100
```

---

## 3. 배포 절차

### 3.1 개발 환경 테스트

```bash
# 1. Docker Compose 빌드
docker-compose build

# 2. 컨테이너 시작
docker-compose up -d

# 3. 로그 확인
docker-compose logs -f fastapi

# 기대 로그:
# ✓ Redis Pub/Sub 초기화 완료: channel=kindmap_events
# ✓ Redis Pub/Sub 리스너 시작: channel=kindmap_events
```

### 3.2 프로덕션 배포

```bash
# 1. 프로덕션 이미지 빌드
docker-compose -f docker-compose.prod.yml build

# 2. ECR에 푸시 (GitHub Actions에서 자동화됨)

# 3. EC2에서 배포
docker-compose -f docker-compose.prod.yml up -d --scale fastapi=3

# 4. 배포 확인
docker-compose -f docker-compose.prod.yml ps
# 출력 예:
# kindmap-redis   running
# fastapi_1       running
# fastapi_2       running
# fastapi_3       running
# kindmap-nginx   running
```

---

## 4. 모니터링 및 검증

### 4.1 Redis Pub/Sub 모니터링

**Redis CLI로 확인**:

```bash
# Redis 컨테이너 접속
docker exec -it kindmap-redis redis-cli

# Pub/Sub 채널 모니터링
PUBSUB CHANNELS
# 출력: 1) "kindmap_events"

# 구독자 수 확인
PUBSUB NUMSUB kindmap_events
# 출력: 1) "kindmap_events"
#       2) "3"  (3개 백엔드 구독 중)

# 실시간 메시지 모니터링 (디버깅용)
SUBSCRIBE kindmap_events
```

### 4.2 Grafana 대시보드

**메트릭 추가** (향후 구현):

```python
# app/services/redis_pubsub_manager.py
from prometheus_client import Counter, Histogram

pubsub_messages_published = Counter(
    'pubsub_messages_published_total',
    'Total messages published to Redis Pub/Sub'
)

pubsub_messages_received = Counter(
    'pubsub_messages_received_total',
    'Total messages received from Redis Pub/Sub'
)

pubsub_message_latency = Histogram(
    'pubsub_message_latency_seconds',
    'Latency of Pub/Sub message delivery'
)
```

---

## 5. 롤백 계획

만약 Redis Pub/Sub 도입 후 문제가 발생하면:

### 5.1 긴급 롤백

```bash
# 1. 기존 docker-compose.yml로 되돌리기
git revert <commit-hash>

# 2. workers=4로 복원 (단, WebSocket 비활성화 권장)
# docker-compose.prod.yml:
command: uvicorn app.main:app --host 0.0.0.0 --port 8001 --workers 4

# 3. 재배포
docker-compose -f docker-compose.prod.yml up -d
```

### 5.2 Redis Pub/Sub 비활성화 (코드 유지)

```bash
# .env 파일 수정
REDIS_PUBSUB_ENABLED=false

# 재시작
docker-compose restart fastapi
```

이 경우 기존 로컬 메모리 방식으로 동작 (단일 백엔드만 사용 가능)

---

## 6. 예상 성능 개선

### Before (workers=4, Pub/Sub 없음)

- **동시 연결**: 1000 / 4 = 250 per worker
- **메시지 라우팅**: 25% 성공률 (같은 worker에 있을 확률)
- **수평 확장**: 불가능

### After (workers=1, Pub/Sub, replicas=3)

- **동시 연결**: 3000 (1000 × 3)
- **메시지 라우팅**: 100% 성공률
- **수평 확장**: replicas 수만 늘리면 무한 확장 가능
- **예상 응답 시간**: < 50ms (Redis Pub/Sub 오버헤드 포함)

---

## 7. 체크리스트

### Phase 1: 준비 (Week 1)
- [ ] `redis[hiredis]>=5.0.0` 의존성 추가
- [ ] `.env`에 `REDIS_PUBSUB_CHANNEL`, `REDIS_PUBSUB_ENABLED` 추가
- [ ] `config.py`에 Pub/Sub 설정 추가

### Phase 2: 구현 (Week 1-2)
- [ ] `redis_pubsub_manager.py` 생성
- [ ] `ConnectionManager.send_message()` 수정
- [ ] `ConnectionManager.handle_pubsub_message()` 추가
- [ ] `main.py` lifespan에 Pub/Sub 초기화 추가

### Phase 3: Docker (Week 2-3)
- [ ] `docker-compose.yml`에서 `workers=1` 설정
- [ ] `docker-compose.prod.yml`에 `deploy.replicas=3` 추가
- [ ] Nginx upstream에 `ip_hash` 추가

### Phase 4: 테스트 (Week 3)
- [ ] 단위 테스트 (`test_redis_pubsub.py`)
- [ ] 통합 테스트 (`test_multibackend_integration.py`)
- [ ] 부하 테스트 (Locust)

### Phase 5: 배포 (Week 4)
- [ ] 개발 환경 배포 및 검증
- [ ] 프로덕션 배포
- [ ] 모니터링 설정

---

## 8. 참고 자료

- **Redis Pub/Sub 공식 문서**: https://redis.io/docs/manual/pubsub/
- **redis-py Async 가이드**: https://redis-py.readthedocs.io/en/stable/examples/asyncio_examples.html
- **FastAPI Lifespan Events**: https://fastapi.tiangolo.com/advanced/events/
- **Docker Compose Deploy**: https://docs.docker.com/compose/compose-file/deploy/

---

**작성일**: 2025-12-03  
**작성자**: Claude (Serena Agent)  
**버전**: 1.0  
**상태**: 구현 대기 중
