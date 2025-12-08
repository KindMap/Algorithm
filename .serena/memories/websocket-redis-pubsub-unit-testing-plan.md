# WebSocket 수평확장 및 Redis Pub/Sub 검증 및 유닛 테스트 작성 계획

## 📋 작업 개요

**목표**:
1. 웹소켓 수평확장과 Redis Pub/Sub 구현이 올바르게 되었는지 검증
2. Nginx 로드밸런싱 설정 검증
3. 기존 테스트 패턴을 따라 해당 기능의 유닛 테스트 작성 (총 72개 테스트 케이스)

**현재 상태 분석**:
- ✅ Redis Pub/Sub Manager 구현 완료 (`redis_pubsub_manager.py`)
- ✅ ConnectionManager에 Pub/Sub 통합 완료
- ✅ Application lifespan에 초기화/종료 로직 통합
- ✅ Docker Compose 설정 (workers=1, replicas=3)
- ✅ Nginx 로드밸런싱 설정 (ip_hash)
- ❌ 유닛 테스트 누락

**작업 전략**:
- 포괄적 테스트 전략 (모든 엣지 케이스 커버)
- 코드 개선사항 5개 제안 후 사용자 승인 받아 적용

---

## Phase 1: 구현 검증 결과

### ✅ 검증 완료 항목

#### A. Redis Pub/Sub Manager (`redis_pubsub_manager.py`)
- Async Redis 클라이언트 사용 (`redis.asyncio`)
- Connection pooling 설정 (max_connections=50)
- Channel 구독 (`kindmap_events`)
- `publish()`: JSON 직렬화 및 발행
- `start_listening()`: 백그라운드 asyncio Task로 리스너 실행
- `_listen_loop()`: 무한 루프로 메시지 수신, "message" 타입만 처리
- `_handle_message()`: JSON 역직렬화 및 핸들러 호출
- Graceful shutdown: `stop_listening()`, `close()`
- Singleton 패턴 (`get_pubsub_manager()`)

#### B. ConnectionManager 통합 (`websocket.py`)
- `send_message()`: 로컬 우선, 없으면 Pub/Sub 발행
- `handle_pubsub_message()`: Pub/Sub 메시지 수신 → WebSocket 전송
- Smart routing: local first, then Redis Pub/Sub

#### C. Application Lifecycle (`main.py`)
- Startup: Pub/Sub 초기화 및 리스너 시작
- Shutdown: Pub/Sub 종료
- Message handler 등록: `websocket_manager.handle_pubsub_message`
- lifespan context manager 사용

#### D. Docker 설정
- **개발 환경** (`docker-compose.yml`): workers=1
- **프로덕션** (`docker-compose.prod.yml`): replicas=3, workers=1
- Redis Pub/Sub 버퍼 최적화: `--client-output-buffer-limit pubsub 32mb 8mb 60`

#### E. Nginx 로드밸런싱 (`nginx/conf.d/kindmap_api.conf`)
- Upstream: `fastapi_backend`
- `ip_hash`: Sticky session for WebSocket stability
- WebSocket upgrade 헤더 설정
- Buffering OFF
- 타임아웃: 3600s (1시간)

---

## Phase 2: 코드 개선사항 제안 (5개)

### 제안 1: 에러 처리 로깅 레벨 개선
**파일**: `redis_pubsub_manager.py:publish()`

**문제**:
```python
if not self.enabled or not self.pubsub_client:
    logger.warning("Redis Pub/Sub이 초기화되지 않았습니다")
    return  # 조용히 실패 → 메시지 유실 가능
```

**개선**:
```python
if not self.enabled:
    logger.debug("Redis Pub/Sub 비활성화")
    return
if not self.pubsub_client:
    logger.error("Redis Pub/Sub 미초기화 - 메시지 유실")
    return
```

### 제안 2: Singleton 리셋 함수 추가 (테스트용)
**파일**: `redis_pubsub_manager.py`

**추가**:
```python
def reset_pubsub_manager():
    """테스트용: Singleton 인스턴스 리셋"""
    global _pubsub_manager
    _pubsub_manager = None
```

### 제안 3: 무한 루프 방지 (via_pubsub 플래그)
**파일**: `websocket.py:ConnectionManager`

**문제**: 로컬 전송 실패 → Pub/Sub 재발행 → 무한 루프 가능

**개선**:
```python
async def send_message(self, user_id: str, message: dict, via_pubsub: bool = False):
    if user_id in self.active_connections:
        try:
            await self.active_connections[user_id].send_json(message)
            return
        except Exception as e:
            self.disconnect(user_id)
            return  # Pub/Sub 재시도 안 함
    
    # Pub/Sub로 받은 메시지는 재발행 안 함
    if not via_pubsub and self.pubsub_manager.enabled:
        await self.pubsub_manager.publish(user_id, message)

async def handle_pubsub_message(self, user_id: str, message: dict):
    await self.send_message(user_id, message, via_pubsub=True)
```

### 제안 4: 타임스탬프 수정
**파일**: `websocket.py:send_error()`

**문제**: `str(uuid.uuid4())`를 timestamp로 사용 (잘못된 사용)

**개선**:
```python
from datetime import datetime, timezone

"timestamp": datetime.now(timezone.utc).isoformat()  # ISO 8601
```

### 제안 5: Pub/Sub 메시지 스키마 검증
**파일**: `redis_pubsub_manager.py:_handle_message()`

**문제**: KeyError 가능

**개선**:
```python
async def _handle_message(self, data: str):
    try:
        payload = json.loads(data)
        
        # 필수 필드 검증
        if "target_user_id" not in payload or "message" not in payload:
            logger.error(f"Invalid schema: {payload}")
            return
        
        target_user_id = payload["target_user_id"]
        message = payload["message"]
        
        if self.message_handler:
            await self.message_handler(target_user_id, message)
    
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode failed: {e}, data={data[:100]}")
    except Exception as e:
        logger.error(f"Message handling failed: {e}", exc_info=True)
```

---

## Phase 3: 유닛 테스트 작성 (72개 케이스)

### 3.1 테스트 파일 구조

```
transit-routing/tests/test/
├── test_redis_pubsub_manager.py      # 44개 테스트 케이스
├── test_websocket_pubsub.py          # 28개 테스트 케이스
└── conftest.py                        # Fixture 추가
```

### 3.2 test_redis_pubsub_manager.py (44개)

#### A. 초기화 테스트 (6개)
1. `test_initialize_success`
2. `test_initialize_creates_connection_pool`
3. `test_initialize_subscribes_to_channel`
4. `test_initialize_disabled`
5. `test_initialize_connection_error`
6. `test_initialize_idempotent`

#### B. 메시지 발행 테스트 (9개)
7. `test_publish_message_success`
8. `test_publish_calls_redis_publish`
9. `test_publish_message_json_serialization`
10. `test_publish_message_payload_structure`
11. `test_publish_message_with_korean_characters`
12. `test_publish_message_not_initialized`
13. `test_publish_message_disabled`
14. `test_publish_message_redis_error`
15. `test_publish_message_with_special_characters`

#### C. 메시지 수신 테스트 (11개)
16-26. 리스너 시작, 메시지 처리, JSON 파싱, 필터링 등

#### D. 리스너 제어 테스트 (4개)
27-30. 중지, Task 취소, 에러 처리

#### E. 종료 및 정리 (6개)
31-36. 채널 구독 해제, 연결 종료, Shutdown 순서

#### F. Singleton 패턴 (3개)
37-39. Singleton 동작, 리셋 함수

#### G. 엣지 케이스 (5개)
40-44. 예외 처리, None/빈 값, 연속 메시지

**Mock 전략**:
- `redis.asyncio.ConnectionPool.from_url` → AsyncMock
- `redis.asyncio.Redis` → AsyncMock
- `pubsub.listen()` → async generator mock

### 3.3 test_websocket_pubsub.py (28개)

#### A. 메시지 라우팅 (9개)
1-9. 로컬 전송, Pub/Sub fallback, via_pubsub 플래그

#### B. Pub/Sub 수신 처리 (5개)
10-14. 메시지 수신 후 WebSocket 전송, 에러 처리

#### C. 연결 관리 (3개)
15-17. connect, disconnect, 연결 상태 변경

#### D. 에러 메시지 (3개)
18-20. send_error 동작, 타임스탬프 포맷

#### E. 통합 시나리오 (4개)
21-24. 크로스 백엔드 메시지, Pub/Sub 비활성화

#### F. 엣지 케이스 (4개)
25-28. None 값, 빈 메시지, 동시 메시지, WebSocket 종료

**Mock 전략**:
- `WebSocket` → AsyncMock
- `RedisPubSubManager.publish()` → AsyncMock
- `get_pubsub_manager()` → Mock instance

### 3.4 conftest.py Fixture 추가

```python
@pytest.fixture
def mock_redis_pubsub_client():
    """Mock Redis Pub/Sub client with async operations"""
    ...

@pytest.fixture
def sample_pubsub_message():
    """Sample Pub/Sub message with Korean characters"""
    ...
```

---

## Phase 4: 테스트 실행 및 커버리지

### 실행 명령어

```bash
# 새 테스트만 실행
pytest tests/test/test_redis_pubsub_manager.py -v
pytest tests/test/test_websocket_pubsub.py -v

# 모든 테스트 실행
pytest tests/test/ -v

# 커버리지 포함
pytest tests/test/ \
  --cov=app.services.redis_pubsub_manager \
  --cov=app.api.v1.endpoints.websocket \
  --cov-report=html
```

### 커버리지 목표
- `redis_pubsub_manager.py`: 90% 이상
- `websocket.py` (Pub/Sub 부분): 85% 이상

---

## 중요 파일 위치

### 검증 대상
- `transit-routing/app/services/redis_pubsub_manager.py`
- `transit-routing/app/api/v1/endpoints/websocket.py`
- `transit-routing/app/main.py`
- `docker-compose.yml`
- `docker-compose.prod.yml`
- `nginx/conf.d/kindmap_api.conf`

### 생성 예정
- `transit-routing/tests/test/test_redis_pubsub_manager.py` (신규)
- `transit-routing/tests/test/test_websocket_pubsub.py` (신규)
- `transit-routing/tests/test/conftest.py` (Fixture 추가)

---

## 예상 이슈 및 해결

### 이슈 1: Async Iterator Mock
**문제**: `pubsub.listen()`은 async generator
**해결**: 
```python
async def mock_listen():
    yield {"type": "subscribe"}
    yield {"type": "message", "data": "..."}

mock_pubsub.listen = mock_listen
```

### 이슈 2: Singleton 상태 유지
**문제**: 테스트 간 singleton 인스턴스 공유
**해결**: `reset_pubsub_manager()` 호출 또는 `_pubsub_manager = None`

### 이슈 3: Background Task 테스트
**문제**: `_listen_loop()`는 무한 루프
**해결**: `asyncio.CancelledError`로 종료 또는 `_is_listening = False`

---

## 예상 작업 시간

- **코드 개선** (Phase 2): 약 30분
- **테스트 작성** (Phase 3): 약 4시간
  - `test_redis_pubsub_manager.py` (44개): 2시간
  - `test_websocket_pubsub.py` (28개): 1.5시간
  - `conftest.py` fixture: 20분
- **테스트 실행 및 디버깅** (Phase 4): 약 1.5시간

**전체**: 약 6시간

---

## 다음 작업 시 순서

1. 사용자에게 개선사항 5개 승인 요청
2. 승인된 개선사항 코드 적용
3. `test_redis_pubsub_manager.py` 작성 (44개)
4. `test_websocket_pubsub.py` 작성 (28개)
5. `conftest.py` fixture 추가
6. 테스트 실행 및 디버깅
7. 커버리지 확인 및 보완

---

**작성일**: 2025-12-03  
**상태**: 계획 완료, 작업 대기 중  
**총 테스트 케이스**: 72개 (44 + 28)
