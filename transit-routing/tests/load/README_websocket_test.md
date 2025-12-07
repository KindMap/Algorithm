# WebSocket 부하 테스트 가이드

## 개요

이 문서는 KindMap 프로젝트의 수평 확장 환경(Redis Pub/Sub)에서 WebSocket 연결의 안정성과 성능을 검증하기 위한 부하 테스트 실행 가이드입니다.

### 테스트 목표

- **1000명 동시 WebSocket 연결** 처리 검증
- **실시간 위치 업데이트** 성능 측정
- **경로 계산** 부하 처리 검증
- **Redis Pub/Sub**를 통한 크로스-백엔드 메시지 라우팅 검증

### 테스트 환경

- **대상 서버**: `wss://kindmap-for-you.cloud`
- **Backend**: 3개 replica (각 1 worker)
- **최대 용량**: 3000 connections (1000/backend × 3)
- **Redis Pub/Sub**: `kindmap_events` 채널
- **총 테스트 시간**: 25분

---

## 파일 구조

```
transit-routing/tests/load/
├── locustfile_websocket_load_test.py  # WebSocket 부하 테스트 (신규)
├── locustfile_http_load_test.py       # HTTP REST API 부하 테스트 (기존)
├── websocket_test_config.json         # 테스트 설정 및 데이터 (신규)
└── README_websocket_test.md           # 본 문서 (신규)
```

---

## 사전 준비

### 1. 환경 확인

#### Backend 상태 확인
```bash
# Docker Compose로 3개 replica 실행 확인
docker ps | grep fastapi

# 예상 출력: kindmap-fastapi-1, kindmap-fastapi-2, kindmap-fastapi-3
```

#### Redis Pub/Sub 활성화 확인
```bash
# .env 파일 또는 환경 변수 확인
grep REDIS_PUBSUB_ENABLED .env

# 예상 출력: REDIS_PUBSUB_ENABLED=true
```

#### Nginx 설정 확인
```bash
# nginx.conf에서 ip_hash 및 WebSocket 설정 확인
cat nginx/conf.d/kindmap_api.conf | grep -A 5 "upstream fastapi_backend"

# 예상 출력:
# upstream fastapi_backend {
#     ip_hash;
#     server fastapi:8001;
# }
```

### 2. 테스트 계정 확인

다음 5개 계정이 데이터베이스에 존재해야 합니다:

- `test123@test.com` / `password`
- `test789@test.com` / `password2`
- `test147@test.com` / `password3`
- `test258@test.com` / `password4`
- `test369@test.com` / `password5`

계정이 없다면 회원가입 API를 통해 생성하거나 DB에 직접 INSERT 해야 합니다.

### 3. 의존성 설치

```bash
# Locust 및 WebSocket 클라이언트 라이브러리 설치
pip install locust websocket-client requests
```

**필수 라이브러리**:
- `locust>=2.15.0` - 부하 테스트 프레임워크
- `websocket-client>=1.6.0` - WebSocket 클라이언트
- `requests>=2.31.0` - HTTP 요청 (JWT 토큰 획득용)

### 4. 모니터링 준비

#### CloudWatch 대시보드 (AWS)
- EC2 인스턴스 CPU, Memory, Network 메트릭
- Locust 테스트 시작 전 스냅샷 확보

#### Redis 모니터링
```bash
# Redis 연결 수 확인
docker exec kindmap-redis redis-cli INFO clients | grep connected_clients

# Redis Pub/Sub 상태 확인
docker exec kindmap-redis redis-cli PUBSUB CHANNELS
```

#### Application 로그
```bash
# Backend 로그 실시간 모니터링 (별도 터미널)
docker logs -f kindmap-fastapi-1
docker logs -f kindmap-fastapi-2
docker logs -f kindmap-fastapi-3
```

---

## 테스트 실행

### 방법 1: Locust 웹 UI (권장)

**장점**: 실시간 그래프, 동적 사용자 수 조정, 직관적인 인터페이스

```bash
cd C:\Users\yunha\Desktop\kindMap_Algorithm\transit-routing\tests\load

# Locust 웹 UI 실행
locust -f locustfile_websocket_load_test.py \
    --host=wss://kindmap-for-you.cloud \
    --web-host=0.0.0.0 \
    --web-port=8089
```

**접속**: http://localhost:8089

**설정**:
- Number of users: `1000` (최대 동시 사용자 수)
- Spawn rate: `5` (초당 증가율)
- Host: `wss://kindmap-for-you.cloud` (자동 설정됨)

**실행**: Start 버튼 클릭

**모니터링**:
- Statistics 탭: 요청 성공률, 응답 시간 (p50, p95, p99)
- Charts 탭: 실시간 RPS, 응답 시간 그래프
- Failures 탭: 에러 발생 시 상세 정보

**중지**: Stop 버튼 클릭 후 Download Report 가능

---

### 방법 2: Headless 모드 (자동화)

**장점**: CI/CD 통합, 스크립트 자동화, 리포트 자동 생성

```bash
cd C:\Users\yunha\Desktop\kindMap_Algorithm\transit-routing\tests\load

# 1000명, 25분 자동 테스트
locust -f locustfile_websocket_load_test.py \
    --host=wss://kindmap-for-you.cloud \
    --headless \
    --users=1000 \
    --spawn-rate=5 \
    --run-time=25m \
    --html=websocket_load_report.html \
    --csv=websocket_metrics
```

**출력 파일**:
- `websocket_load_report.html` - HTML 리포트 (그래프 포함)
- `websocket_metrics_stats.csv` - 통계 데이터
- `websocket_metrics_stats_history.csv` - 시간별 히스토리
- `websocket_metrics_failures.csv` - 에러 로그

---

### 방법 3: 작은 규모 테스트 (개발/검증용)

프로덕션 테스트 전 로컬/스테이징 환경에서 소규모 테스트 권장:

```bash
# 100명, 5분 테스트
locust -f locustfile_websocket_load_test.py \
    --host=wss://kindmap-for-you.cloud \
    --headless \
    --users=100 \
    --spawn-rate=2 \
    --run-time=5m \
    --html=websocket_small_test.html
```

---

## 부하 패턴

### Step Load 전략

테스트는 다음과 같이 점진적으로 부하가 증가합니다:

| 단계 | 시간 | 사용자 수 | Spawn Rate | 설명 |
|------|------|-----------|------------|------|
| 1. Warm-up | 0-2분 | 0 → 100 | 1/s | 초기 연결 안정화 |
| 2. Normal Load | 2-5분 | 100 → 300 | 2/s | 일반 부하 수준 |
| 3. Medium Load | 5-8분 | 300 → 500 | 3/s | 중간 부하 (167/backend) |
| 4. High Load | 8-12분 | 500 → 750 | 5/s | 높은 부하 (250/backend) |
| 5. Peak Load | 12-15분 | 750 → 1000 | 5/s | 최대 부하 (333/backend) |
| 6. Sustained Stress | 15-25분 | 1000 유지 | - | **지속 스트레스 테스트** |

**중요**: Stage 6 (Sustained Stress)는 시스템이 피크 부하를 10분간 안정적으로 유지하는지 검증합니다.

---

## 테스트 시나리오

### 사용자 행동 시뮬레이션

각 가상 사용자는 다음 과정을 반복합니다:

1. **초기화** (on_start):
   - HTTP POST `/api/v1/auth/login` → JWT 토큰 획득
   - WebSocket 연결: `wss://kindmap-for-you.cloud/api/v1/ws/{user_id}?token={jwt_token}`

2. **경로 계산** (Task, Weight=1):
   - 메시지: `{"type": "start_navigation", "origin": "강남", "destination": "홍대입구", "disability_type": "PHY"}`
   - 응답 대기: 최대 10초
   - 성공 시: route_id 저장, GPS 초기화

3. **위치 업데이트** (Task, Weight=10):
   - 메시지: `{"type": "location_update", "latitude": 37.4979, "longitude": 127.0276, "route_id": "..."}`
   - 응답 대기: 최대 3초
   - GPS 시뮬레이션: 10-50m 랜덤 이동 (3-5초 간격)

4. **종료** (on_stop):
   - WebSocket 연결 해제

### 메시지 비율

- **start_navigation**: 1 (무거운 작업 - 경로 계산)
- **location_update**: 10 (빈번한 작업 - 실시간 안내)

**비율 1:10** → 실제 사용자 행동과 유사 (경로 1회 계산 후 GPS 업데이트 여러 번)

---

## 성공 기준

### 필수 통과 기준

| 메트릭 | 목표 | 측정 방법 |
|--------|------|-----------|
| WebSocket 연결 성공률 | >99% | Locust Statistics: `ws_connect` Failure % |
| 연결 수립 시간 (p95) | <500ms | Locust Charts: `ws_connect` 95th percentile |
| start_navigation (p95) | <2000ms | Locust Statistics: `ws_start_navigation` 95% |
| location_update (p95) | <300ms | Locust Statistics: `ws_location_update` 95% |
| 전체 에러율 | <1% | Locust Statistics: Total Failures % |
| Redis Pub/Sub 전달 실패 | 0건 | Application Logs: "메시지 발행 실패" 검색 |

### 권장 모니터링 기준

| 리소스 | 정상 범위 | 경고 | 위험 |
|--------|-----------|------|------|
| Backend CPU | <70% | 70-85% | >85% |
| Backend Memory | <80% | 80-90% | >90% |
| Redis Connected Clients | <150 | 150-180 | >180 |
| Redis Memory | <400MB | 400-480MB | >480MB |
| Nginx Active Connections | <3000 | 3000-3500 | >3500 |

---

## 결과 분석

### 1. Locust HTML Report 확인

생성된 `websocket_load_report.html`을 브라우저에서 열어 다음 확인:

#### Statistics 테이블
- **Type**: WebSocket (모든 메트릭)
- **Name**:
  - `ws_connect` - WebSocket 연결
  - `ws_start_navigation` - 경로 계산
  - `ws_location_update` - 위치 업데이트
- **# Requests**: 총 요청 수
- **# Fails**: 실패 수 (0에 가까워야 함)
- **Median / 95%ile / 99%ile**: 응답 시간 (ms)
- **Average**: 평균 응답 시간
- **Min / Max**: 최소/최대 응답 시간

#### Charts
- **Total Requests per Second**: RPS 변화 (안정적이어야 함)
- **Response Times (ms)**: 시간에 따른 응답 시간 추이
- **Number of Users**: 사용자 수 증가 패턴 확인

### 2. CSV 데이터 분석

```bash
# 통계 요약
cat websocket_metrics_stats.csv

# 시간별 히스토리 (Excel/Python pandas로 분석)
cat websocket_metrics_stats_history.csv

# 실패 로그
cat websocket_metrics_failures.csv
```

### 3. Application 로그 분석

#### WebSocket 연결 로그
```bash
# 연결 성공 건수
docker logs kindmap-fastapi-1 | grep "WebSocket 연결 성공" | wc -l

# 연결 실패 건수
docker logs kindmap-fastapi-1 | grep "WebSocket 연결 실패" | wc -l
```

#### Redis Pub/Sub 메시지 발행
```bash
# 메시지 발행 건수
docker logs kindmap-fastapi-1 | grep "메시지 발행" | wc -l

# 발행 실패 (있으면 안 됨!)
docker logs kindmap-fastapi-1 | grep "메시지 발행 실패"
```

#### 경로 계산 완료
```bash
docker logs kindmap-fastapi-1 | grep "경로 계산 완료" | wc -l
```

### 4. Backend 부하 분산 확인

각 backend의 WebSocket 연결 수를 비교하여 균등 분산 확인:

```bash
# Backend 1 연결 수
docker exec kindmap-fastapi-1 netstat -an | grep :8001 | grep ESTABLISHED | wc -l

# Backend 2 연결 수
docker exec kindmap-fastapi-2 netstat -an | grep :8001 | grep ESTABLISHED | wc -l

# Backend 3 연결 수
docker exec kindmap-fastapi-3 netstat -an | grep :8001 | grep ESTABLISHED | wc -l
```

**예상**: 각 backend 약 333 connections (1000/3)

### 5. Redis 상태 확인

```bash
# 연결 클라이언트 수
docker exec kindmap-redis redis-cli INFO clients

# Pub/Sub 채널 확인
docker exec kindmap-redis redis-cli PUBSUB CHANNELS

# 메모리 사용량
docker exec kindmap-redis redis-cli INFO memory | grep used_memory_human
```

---

## 문제 해결

### 문제 1: WebSocket 연결 실패율 높음 (>1%)

**증상**:
```
Locust Statistics: ws_connect - Failures: 50 (5%)
```

**원인**:
- Nginx 연결 제한 도달
- Backend 리소스 부족 (CPU/Memory)
- Redis 연결 풀 소진

**해결**:
1. Nginx worker_connections 증가 확인
2. Backend 로그에서 에러 확인: `docker logs kindmap-fastapi-1`
3. CloudWatch에서 CPU/Memory 확인
4. Redis connection count 확인

---

### 문제 2: start_navigation 응답 시간 길음 (p95 > 2000ms)

**증상**:
```
Locust Statistics: ws_start_navigation - 95%ile: 3500ms
```

**원인**:
- PostgreSQL 쿼리 성능 저하
- 경로 캐시 미스율 높음
- Backend CPU 부족

**해결**:
1. PostgreSQL slow query log 확인
2. Redis 캐시 히트율 확인: `docker logs kindmap-fastapi-1 | grep "캐시 히트"`
3. Backend CPU 증가 고려 (Docker resources limits)

---

### 문제 3: location_update 응답 시간 길음 (p95 > 300ms)

**증상**:
```
Locust Statistics: ws_location_update - 95%ile: 500ms
```

**원인**:
- Redis Pub/Sub 지연
- Redis 메모리 부족 (eviction 발생)
- Backend 간 네트워크 지연

**해결**:
1. Redis latency 측정: `docker exec kindmap-redis redis-cli --latency`
2. Redis memory 확인 및 maxmemory 증가
3. Pub/Sub buffer 설정 확인: `client-output-buffer-limit pubsub 32mb 8mb 60`

---

### 문제 4: JWT 토큰 만료

**증상**:
```
Application Log: "JWT 토큰이 만료되었습니다"
```

**원인**:
- ACCESS_TOKEN_EXPIRE_MINUTES=30 (30분 후 만료)
- 테스트 시간 25분 → 일부 초기 사용자 토큰 만료 가능

**해결**:
1. 테스트 시간 단축 (<30분)
2. 토큰 갱신 로직 추가 (현재 미구현)
3. 테스트 전용 긴 만료 시간 설정 (보안 주의!)

---

### 문제 5: Nginx ip_hash로 인한 불균형

**증상**:
```
Backend 1: 800 connections
Backend 2: 150 connections
Backend 3: 50 connections
```

**원인**:
- 단일 테스트 머신에서 실행 → 모든 요청이 같은 IP
- ip_hash 알고리즘이 같은 backend로 라우팅

**해결**:
1. **Locust 분산 모드** 사용 (여러 IP에서 실행)
   ```bash
   # Master 노드
   locust -f locustfile_websocket_load_test.py --master

   # Worker 노드 1 (다른 IP)
   locust -f locustfile_websocket_load_test.py --worker --master-host=<master-ip>

   # Worker 노드 2 (다른 IP)
   locust -f locustfile_websocket_load_test.py --worker --master-host=<master-ip>
   ```

2. **임시 해결** (테스트 목적):
   - Nginx 설정에서 `ip_hash` 주석 처리 (round-robin)
   - 테스트 후 복구 필수!

---

### 문제 6: Redis Pub/Sub 메시지 전달 실패

**증상**:
```
Application Log: "Redis Pub/Sub 메시지 발행 실패"
```

**원인**:
- Redis Pub/Sub buffer 오버플로우
- Redis 연결 끊김
- Pub/Sub listener 중단

**해결**:
1. Redis Pub/Sub buffer 확인:
   ```bash
   docker exec kindmap-redis redis-cli CONFIG GET client-output-buffer-limit
   ```
2. Buffer 증가 (redis.conf):
   ```
   client-output-buffer-limit pubsub 64mb 16mb 60
   ```
3. Pub/Sub listener 상태 로그 확인

---

## Best Practices

### 1. 프로덕션 테스트 시 주의사항

- **오프 피크 시간대 실행** (새벽 2-5시 권장)
- **점진적 증가** (Step Load 패턴 준수)
- **실시간 모니터링** (CloudWatch + Application Logs)
- **롤백 계획** 준비 (문제 발생 시 즉시 테스트 중단)

### 2. 테스트 전 체크리스트

- [ ] Backend 3개 replica 실행 확인
- [ ] Redis Pub/Sub 활성화 확인
- [ ] 테스트 계정 5개 존재 확인
- [ ] CloudWatch 대시보드 준비
- [ ] Application 로그 모니터링 준비
- [ ] Nginx rate limiting 비활성화 (테스트용)

### 3. 테스트 후 체크리스트

- [ ] Locust HTML 리포트 저장
- [ ] CSV 데이터 백업
- [ ] CloudWatch 메트릭 스냅샷 캡처
- [ ] Application 로그 다운로드
- [ ] Redis 상태 저장
- [ ] Backend 부하 분산 결과 기록

### 4. 반복 테스트

동일한 테스트를 2-3회 반복하여 재현성 확인:
- 응답 시간 일관성
- 에러율 안정성
- 리소스 사용량 패턴

---

## 참고 자료

### 관련 파일
- `locustfile_http_load_test.py` - HTTP REST API 부하 테스트
- `transit-routing/app/api/v1/endpoints/websocket.py` - WebSocket 엔드포인트
- `transit-routing/app/services/redis_pubsub_manager.py` - Redis Pub/Sub 매니저
- `transit-routing/app/core/config.py` - 설정 파일

### Locust 공식 문서
- [Locust Documentation](https://docs.locust.io/)
- [Writing a Locustfile](https://docs.locust.io/en/stable/writing-a-locustfile.html)
- [Custom Load Shapes](https://docs.locust.io/en/stable/custom-load-shape.html)

### WebSocket 테스트
- [websocket-client Library](https://github.com/websocket-client/websocket-client)
- [Locust WebSocket Testing](https://docs.locust.io/en/stable/testing-other-systems.html#websocket)

---

## 문의

테스트 관련 문제 발생 시:
1. Application 로그 확인
2. Locust Failures 탭 확인
3. Redis/Nginx 설정 검토
4. 본 README 문제 해결 섹션 참고

**개발팀 연락처**: (프로젝트 담당자 정보)

---

**마지막 업데이트**: 2025-12-07
**작성자**: Claude Sonnet 4.5
**테스트 환경**: wss://kindmap-for-you.cloud (프로덕션)
