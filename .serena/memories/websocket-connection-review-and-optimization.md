# WebSocket 연결 검토 및 최적화 전략

## 📋 요약

**프로젝트**: kindMap_Algorithm (교통약자 지하철 경로 안내 시스템)  
**웹소켓 위치**: `transit-routing/app/api/v1/endpoints/websocket.py`  
**라이브러리**: FastAPI + Uvicorn  
**검토일**: 2025-12-03  
**전체 평가**: B+ (Good with Improvements Needed)

---

## 1. 아키텍처 개요

### 1.1 WebSocket 엔드포인트

```
GET ws://localhost:8001/api/v1/ws/{user_id}?token={jwt_token}
```

**인증 방식**:
- JWT 토큰 기반 (쿼리 파라미터 또는 Authorization 헤더)
- 게스트 지원: `temp_` prefix 사용 시 토큰 없이 연결 가능
- 본인 확인: URL user_id와 JWT의 `sub` claim 비교

### 1.2 메시지 타입

| 타입 | 기능 | 핸들러 함수 |
|------|------|------------|
| `start_navigation` | 경로 계산 시작 | `handle_start_navigation()` |
| `location_update` | 위치 업데이트 및 실시간 안내 | `handle_location_update()` |
| `switch_route` | 상위 3개 경로 중 선택 | `handle_switch_route()` |
| `recalculate_route` | 경로 재계산 | `handle_recalculate_route()` |
| `end_navigation` | 내비게이션 종료 | `handle_end_navigation()` |
| `ping` | 연결 확인 | 자동 `pong` 응답 |

### 1.3 ConnectionManager 클래스

**주요 메서드**:
- `connect(websocket, user_id)`: 새 연결 수립 (중복 처리, 최대 1000개 제한)
- `disconnect(user_id)`: 연결 해제
- `send_message(user_id, message)`: JSON 메시지 전송
- `send_error(user_id, error_msg, code)`: 표준 에러 응답
- `get_connection_count()`: 활성 연결 수 조회

---

## 2. 강점 ✅

### 2.1 명확한 아키텍처
- 책임 분리가 잘 되어 있음 (ConnectionManager, 핸들러, 서비스)
- 비동기 처리 패턴 적용
- `run_in_threadpool`로 blocking 함수 처리

### 2.2 포괄적인 에러 처리
- WebSocketDisconnect와 일반 Exception 분리
- 표준화된 에러 응답 형식
- Graceful shutdown 구현

### 2.3 Redis 기반 세션 관리
- 세션 데이터를 Redis에 저장 (TTL: 30분)
- 경로 정보, 현재 위치, 선택된 경로 순위 등 보관
- 실시간 통계 수집 (`_update_analytics()`)

### 2.4 KD-Tree 기반 최근접 역 검색
- O(log N) 성능
- GPS 좌표로부터 가장 가까운 역 검색
- 경로 이탈 감지 기능

### 2.5 테스트 커버리지
- ConnectionManager 단위 테스트 (8개)
- WebSocket 핸들러 테스트 (9개)
- pytest + pytest-asyncio 사용

---

## 3. 발견된 이슈 및 개선사항

### 🔴 P0 - 즉시 조치 필요

#### Issue #1: Uvicorn Multi-Worker 설정 오류
**파일**: `main.py:321`  
**심각도**: 높음

**현재 설정**:
```python
uvicorn.run(
    "app.main:app",
    workers=4,  # ⚠️ WebSocket과 비호환
)
```

**문제**:
- WebSocket은 상태를 유지하는 연결 기반 프로토콜
- 4개 worker로 분산 시 같은 user_id가 다른 worker로 라우팅될 수 있음
- `active_connections` 딕셔너리가 worker별로 독립적으로 유지됨
- 메시지 전달 실패 가능

**해결책**:
```python
# Option 1: 단일 worker (권장)
workers=1

# Option 2: 로드밸런서에서 sticky session 설정
# Nginx: ip_hash
# HAProxy: source
```

#### Issue #2: 메시지 수신 예외 처리 누락
**파일**: `websocket.py:235`  
**심각도**: 중간

**현재 코드**:
```python
data = await websocket.receive_json()  # JSONDecodeError 미처리
```

**문제**:
- 클라이언트가 잘못된 JSON 전송 시 연결이 비정상 종료됨
- ValidationError가 발생하면 예외가 상위로 전파됨

**해결책**:
```python
try:
    data = await websocket.receive_json()
except json.JSONDecodeError:
    await manager.send_error(user_id, "유효하지 않은 JSON 형식", "INVALID_JSON")
    continue
except ValueError as e:
    logger.warning(f"메시지 파싱 실패: {e}")
    continue
```

---

### 🟡 P1 - 단기 개선

#### Issue #3: Lazy Initialization의 Race Condition
**파일**: `websocket.py:28-55`  
**심각도**: 중간

**현재 코드**:
```python
_redis_client = None

def get_redis_client():
    global _redis_client
    if _redis_client is None:
        _redis_client = init_redis()  # Race condition 가능
    return _redis_client
```

**문제**:
- 다중 스레드 환경에서 여러 스레드가 동시에 초기화 시도 가능
- 중복 Redis 연결 생성 가능

**해결책**:
```python
import threading

_redis_client = None
_lock = threading.Lock()

def get_redis_client():
    global _redis_client
    if _redis_client is None:
        with _lock:
            if _redis_client is None:  # Double-checked locking
                _redis_client = init_redis()
    return _redis_client
```

#### Issue #4: handle_end_navigation 로직 오류
**파일**: `websocket.py:626-643`  
**심각도**: 중간

**현재 코드**:
```python
async def handle_end_navigation(user_id: str):
    session = get_redis_client().get_session(user_id)
    route_id_from_client = session.get("route_id")  # session에서 가져옴
    
    # 클라이언트로부터 route_id를 받지 않음
```

**문제**:
- 함수가 `data` 파라미터를 받지 않음
- 클라이언트가 보낸 route_id를 검증할 수 없음
- session 중복 조회 (2회)

**해결책**:
```python
async def handle_end_navigation(user_id: str, data: dict):
    route_id_from_client = data.get("route_id")
    session = get_redis_client().get_session(user_id)
    
    if not session:
        await manager.send_error(user_id, "활성 세션 없음", "NO_ACTIVE_SESSION")
        return
    
    if route_id_from_client and session.get("route_id") != route_id_from_client:
        await manager.send_error(user_id, "경로 ID 불일치", "ROUTE_ID_MISMATCH")
        return
    
    # 정상 종료 처리
    get_redis_client().delete_session(user_id)
    await manager.send_message(user_id, {
        "type": "navigation_ended",
        "message": "내비게이션이 종료되었습니다."
    })
```

#### Issue #5: 토큰 보안 - 쿼리 파라미터 노출
**파일**: `websocket.py:147`  
**심각도**: 중간

**현재 코드**:
```python
token: str = Query(None),  # URL에 토큰 노출
```

**문제**:
- JWT가 URL에 노출되어 로그, 히스토리, referer에 기록됨
- HTTPS라도 프록시 로그에 남을 수 있음

**권장사항**:
```python
# 우선순위 변경
# 1. WebSocket Sec-WebSocket-Protocol 헤더 사용
# 2. Authorization 헤더 사용
# 3. 쿼리 파라미터 (fallback)

# 클라이언트 예시:
# new WebSocket(url, ['bearer', token]);
```

---

### 🟢 P2 - 장기 개선

#### Issue #6: 메모리 누수 가능성
**파일**: `websocket.py:66`

**현재 구조**:
```python
self.active_connections: Dict[str, WebSocket] = {}
```

**잠재 문제**:
- 비정상 종료 시 딕셔너리 항목이 남아있을 수 있음
- 장시간 운영 시 메모리 증가 가능

**권장 모니터링**:
```python
# Prometheus 메트릭 추가
from prometheus_client import Gauge

active_connections_gauge = Gauge(
    'websocket_active_connections',
    'Number of active WebSocket connections'
)

# 주기적 정리 작업 (예: APScheduler)
async def cleanup_stale_connections():
    for user_id in list(manager.active_connections.keys()):
        # TTL 기반 정리 또는 health check
        pass
```

#### Issue #7: 브로드캐스팅 기능 없음
**현재**: 1-to-1 unicast만 지원

**향후 필요 시**:
```python
async def broadcast(self, message: dict, exclude: set = None):
    """모든 연결된 클라이언트에 메시지 전송"""
    exclude = exclude or set()
    
    for user_id in list(self.active_connections.keys()):
        if user_id not in exclude:
            await self.send_message(user_id, message)
```

#### Issue #8: 게스트 연결 정책이 암묵적
**파일**: `websocket.py:169`

**현재**:
```python
if user_id.startswith("temp_"):
    logger.info(f"게스트 연결 허용: {user_id}")
```

**개선**:
```python
# config.py에 명시
GUEST_USER_PREFIX = "temp_"
GUEST_CONNECTIONS_ENABLED = True

# 문서화 및 클라이언트 계약 명확화
```

---

## 4. 최적화 전략

### 4.1 단기 최적화 (1-2주)

**우선순위 1: Workers 설정 수정**
```python
# main.py
if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        workers=1,  # WebSocket 호환
        ws_ping_interval=20.0,
        ws_ping_timeout=20.0,
        timeout_keep_alive=30,
    )
```

**우선순위 2: 예외 처리 강화**
```python
# websocket.py 메시지 루프
while True:
    try:
        data = await websocket.receive_json()
    except json.JSONDecodeError:
        await manager.send_error(user_id, "잘못된 JSON 형식", "INVALID_JSON")
        continue
    except Exception as e:
        logger.error(f"메시지 수신 오류: {e}")
        break
    
    # 메시지 처리
    try:
        message_type = data.get("type")
        # ... 핸들러 호출
    except Exception as e:
        logger.error(f"메시지 처리 오류: {e}", exc_info=True)
        await manager.send_error(user_id, "메시지 처리 실패", "PROCESSING_ERROR")
```

**우선순위 3: Redis 클라이언트 초기화 개선**
```python
import threading

_redis_client = None
_redis_lock = threading.Lock()

def get_redis_client():
    global _redis_client
    if _redis_client is None:
        with _redis_lock:
            if _redis_client is None:
                _redis_client = init_redis()
    return _redis_client
```

### 4.2 중기 최적화 (1-2개월)

**성능 모니터링**:
```python
# 메트릭 수집
import time
from prometheus_client import Counter, Histogram

websocket_messages_total = Counter(
    'websocket_messages_total',
    'Total WebSocket messages',
    ['type', 'status']
)

websocket_message_duration = Histogram(
    'websocket_message_duration_seconds',
    'WebSocket message processing duration',
    ['type']
)

# 핸들러에서 사용
async def handle_location_update(user_id: str, data: dict):
    start_time = time.time()
    
    try:
        # 처리 로직
        websocket_messages_total.labels(type='location_update', status='success').inc()
    except Exception as e:
        websocket_messages_total.labels(type='location_update', status='error').inc()
        raise
    finally:
        duration = time.time() - start_time
        websocket_message_duration.labels(type='location_update').observe(duration)
```

**연결 상태 모니터링**:
```python
# 헬스체크 엔드포인트
@router.get("/health")
async def websocket_health():
    return {
        "active_connections": manager.get_connection_count(),
        "max_connections": manager.MAX_CONNECTIONS,
        "redis_connected": get_redis_client().redis_client.ping()
    }
```

### 4.3 장기 최적화 (3-6개월)

**수평 확장 고려**:
```python
# Redis Pub/Sub를 이용한 멀티 서버 지원
class RedisWebSocketManager:
    def __init__(self):
        self.pubsub = redis_client.pubsub()
        self.pubsub.subscribe('websocket_messages')
    
    async def broadcast_via_redis(self, user_id: str, message: dict):
        """Redis를 통해 다른 서버의 연결에도 메시지 전달"""
        await redis_client.publish('websocket_messages', json.dumps({
            'user_id': user_id,
            'message': message
        }))
    
    async def listen_redis_messages(self):
        """다른 서버에서 발행한 메시지 수신"""
        for message in self.pubsub.listen():
            if message['type'] == 'message':
                data = json.loads(message['data'])
                await manager.send_message(data['user_id'], data['message'])
```

**WebSocket 압축 활성화**:
```python
# main.py
uvicorn.run(
    "app.main:app",
    ws_compression='deflate',  # 메시지 압축
)
```

---

## 5. 성능 벤치마크 기준

### 5.1 목표 메트릭

| 메트릭 | 목표 | 현재 추정 |
|--------|------|-----------|
| 동시 연결 수 | 1000 | 1000 (설정값) |
| 평균 메시지 지연 | < 100ms | 측정 필요 |
| 메시지 처리율 | > 1000 msg/s | 측정 필요 |
| 메모리 사용량 | < 500MB | 측정 필요 |
| CPU 사용률 | < 50% | 측정 필요 |

### 5.2 부하 테스트 시나리오

```python
# locust 부하 테스트 예시
from locust import HttpUser, task, between
import websocket
import json

class WebSocketUser(HttpUser):
    wait_time = between(1, 3)
    
    def on_start(self):
        # WebSocket 연결
        self.ws = websocket.create_connection(
            f"ws://localhost:8001/api/v1/ws/temp_{self.user_id}"
        )
    
    @task
    def send_ping(self):
        self.ws.send(json.dumps({"type": "ping"}))
        response = self.ws.recv()
    
    @task
    def location_update(self):
        self.ws.send(json.dumps({
            "type": "location_update",
            "lat": 37.5665,
            "lon": 126.9780
        }))
        response = self.ws.recv()
    
    def on_stop(self):
        self.ws.close()
```

---

## 6. 구현 타임라인

### Week 1-2: 긴급 수정
- [ ] Uvicorn workers=1 설정 변경
- [ ] receive_json() 예외 처리 추가
- [ ] 로컬 환경 테스트

### Week 3-4: 안정성 개선
- [ ] Redis 클라이언트 thread-safe 초기화
- [ ] handle_end_navigation 수정
- [ ] 토큰 전달 방식 개선 (Authorization 헤더 우선)
- [ ] 단위 테스트 추가

### Month 2: 모니터링 구축
- [ ] Prometheus 메트릭 추가
- [ ] Grafana 대시보드 구성
- [ ] 알람 설정 (연결 수, 에러율)
- [ ] 부하 테스트 수행

### Month 3-6: 확장성 고려
- [ ] Redis Pub/Sub 기반 멀티 서버 지원
- [ ] WebSocket 압축 활성화
- [ ] 연결 풀 최적화
- [ ] 캐시 전략 개선

---

## 7. 파일 경로 참고

```
C:\Users\yunha\Desktop\kindMap_Algorithm\transit-routing\
├── app\
│   ├── api\v1\endpoints\
│   │   └── websocket.py              ← 핵심 WebSocket 엔드포인트
│   ├── db\
│   │   └── redis_client.py           ← Redis 세션 관리
│   ├── services\
│   │   ├── guidance_service.py       ← 실시간 안내 로직
│   │   └── pathfinding_service.py    ← 경로 계산
│   └── main.py                        ← Uvicorn 설정
└── tests\test\
    └── test_websocket.py              ← WebSocket 테스트
```

---

## 8. 참고 자료

- **FastAPI WebSocket 문서**: https://fastapi.tiangolo.com/advanced/websockets/
- **Uvicorn 설정**: https://www.uvicorn.org/settings/
- **Redis Pub/Sub**: https://redis.io/docs/manual/pubsub/
- **WebSocket RFC 6455**: https://tools.ietf.org/html/rfc6455

---

## 9. 결론

kindMap 프로젝트의 WebSocket 구현은 전반적으로 **잘 설계**되어 있으나, **multi-worker 설정 오류**와 **예외 처리 누락** 등 몇 가지 중요한 이슈가 있습니다.

**즉시 조치**가 필요한 P0 이슈를 해결하면 안정적인 운영이 가능하며, 중장기적으로 모니터링 및 확장성 개선을 통해 더욱 견고한 시스템을 구축할 수 있습니다.

**현재 상태 평가**: B+ (Good with Improvements Needed)  
**개선 후 예상 평가**: A (Excellent)
