# C++ 엔진 간단 성능 테스트 가이드

외부 PostgreSQL을 사용하여 FastAPI 이미지만 빌드 후 C++ 엔진 성능을 빠르게 테스트

## 🎯 개요

- **목적**: C++ 경로 탐색 엔진의 성능만 빠르게 검증
- **구성**: FastAPI + Redis (외부 PostgreSQL 활용)
- **소요 시간**: ~30분 (빌드 15분 + 테스트 10분)

---

## ⚡ 빠른 시작 (5분 안에)

### 1. 환경 변수 설정

```bash
# .env.test 파일 수정
nano .env.test
```

**필수 수정 항목** (외부 PostgreSQL 정보):
```bash
DB_HOST=your-actual-rds-endpoint.amazonaws.com
DB_PORT=5432
DB_NAME=kindmap_db
DB_USER=your_db_user
DB_PASSWORD=your_db_password
```

### 2. FastAPI 이미지 빌드

```bash
# 프로젝트 루트에서 실행
docker build -f Dockerfile.fastapi -t kindmap-fastapi:latest .

# 15-20분 소요 (C++ 컴파일 포함)
```

### 3. 테스트 환경 시작

```bash
# FastAPI + Redis 시작
docker-compose -f docker-compose.cpp-test.yml up -d

# 컨테이너 상태 확인
docker ps
```

### 4. C++ 엔진 동작 확인

```bash
# 헬스체크
curl http://localhost:8001/health | jq

# C++ 엔진 확인 (engine_type: "cpp" 확인)
curl http://localhost:8001/api/v1/info | jq '.engine'
```

### 5. 부하 테스트 실행

```bash
# Locust 설치 (최초 1회)
pip install locust

# 간단한 성능 테스트 실행
cd transit-routing/tests/load
locust -f locustfile_simple_cpp_test.py \
  --host=http://localhost:8001 \
  --users 50 \
  --spawn-rate 5 \
  --run-time 3m \
  --headless \
  --html cpp_test_report.html
```

### 6. 결과 확인

```bash
# HTML 리포트 열기
open cpp_test_report.html

# 또는 실시간 메트릭
curl http://localhost:8001/api/v1/metrics | jq
```

---

## 📊 상세 가이드

### Step 1: 사전 준비

**필수 요구사항:**
- Docker & Docker Compose 설치
- 외부 PostgreSQL 접근 가능
- 8GB+ RAM

**디렉토리 구조:**
```
kindMap_Algorithm/
├── Dockerfile.fastapi
├── docker-compose.cpp-test.yml     ← 신규 (FastAPI + Redis만)
├── .env.test                       ← 신규 (외부 DB 정보)
└── transit-routing/
    └── tests/load/
        └── locustfile_simple_cpp_test.py  ← 신규 (간단한 테스트)
```

### Step 2: 외부 DB 연결 설정

#### A. .env.test 파일 수정

```bash
# 실제 DB 정보로 변경
DB_HOST=your-rds-endpoint.rds.amazonaws.com  # ← 실제 RDS 엔드포인트
DB_PORT=5432
DB_NAME=kindmap_db                           # ← 실제 DB 이름
DB_USER=postgres                             # ← 실제 사용자명
DB_PASSWORD=your-secure-password             # ← 실제 비밀번호
```

#### B. DB 연결 테스트 (선택사항)

로컬에서 먼저 확인:
```bash
# psql 설치되어 있다면
psql -h your-rds-endpoint.rds.amazonaws.com \
     -p 5432 \
     -U postgres \
     -d kindmap_db \
     -c "SELECT COUNT(*) FROM stations;"

# 또는 Python으로
python -c "
import psycopg2
conn = psycopg2.connect(
    host='your-rds-endpoint.rds.amazonaws.com',
    port=5432,
    database='kindmap_db',
    user='postgres',
    password='your-password'
)
print('✓ DB 연결 성공')
conn.close()
"
```

### Step 3: Docker 이미지 빌드

```bash
# 프로젝트 루트 디렉토리에서
cd ~/kindMap_Algorithm

# FastAPI 이미지 빌드 (C++ 엔진 포함)
docker build -f Dockerfile.fastapi -t kindmap-fastapi:latest .
```

**빌드 과정 (15-20분):**
```
[1/7] Installing system dependencies...          (2분)
[2/7] Installing Python packages...              (3분)
[3/7] Downloading Whisper model...               (2분)
[4/7] Compiling C++ pathfinding module...        (5분) ⭐
[5/7] Installing C++ module...                   (1분)
[6/7] Copying files to final image...            (2분)
[7/7] Setting up environment...                  (1분)

Successfully built kindmap-fastapi:latest
```

**빌드 검증:**
```bash
# 이미지 확인
docker images | grep kindmap-fastapi
# kindmap-fastapi   latest   xxx   2 minutes ago   1.2GB

# C++ 모듈 로드 테스트
docker run --rm kindmap-fastapi:latest \
  python -c "import pathfinding_cpp; print('✓ C++ module OK')"
```

### Step 4: 테스트 환경 실행

#### A. Docker Compose로 시작

```bash
# FastAPI + Redis 시작
docker-compose -f docker-compose.cpp-test.yml up -d

# 예상 출력:
# Creating network "kindmap-test-network" ... done
# Creating kindmap-redis-test ... done
# Creating kindmap-fastapi-test ... done
```

#### B. 컨테이너 상태 확인

```bash
# 모든 컨테이너가 healthy 상태여야 함
docker ps

# 예상 출력:
# CONTAINER ID   IMAGE                   STATUS                   PORTS
# abc123         kindmap-fastapi:latest  Up 30 seconds (healthy)  0.0.0.0:8001->8001/tcp
# def456         redis:7-alpine          Up 35 seconds (healthy)  0.0.0.0:6379->6379/tcp
```

#### C. 로그 확인

```bash
# FastAPI 시작 로그
docker logs kindmap-fastapi-test

# ========================================
# KindMap Backend 시작 중...
# ========================================
# 1/4 PostgreSQL 연결 풀 초기화 중...     ← 외부 DB 연결
# 2/4 역 정보 캐시 초기화 중...
# 3/4 Redis 세션 클라이언트 초기화 중...
# 4/4 Redis Pub/Sub 초기화 중...
# ========================================
# KindMap Backend 시작 완료!
# ========================================
```

**DB 연결 실패 시:**
```
ERROR: could not connect to server
```
→ `.env.test`의 DB 정보 재확인

#### D. C++ 엔진 활성화 확인

```bash
# 헬스체크 전체 정보
curl -s http://localhost:8001/health | jq

# 예상 응답:
# {
#   "status": "healthy",
#   "engine": {
#     "engine_type": "cpp",              ← C++ 확인!
#     "engine_class": "PathfindingServiceCPP",
#     "cpp_enabled": true,
#     "description": "C++ pathfinding_cpp 모듈 (고성능)"
#   },
#   "components": {
#     "database": "healthy",             ← 외부 DB 연결 성공
#     "redis": "healthy",
#     "pathfinding_engine": "healthy"
#   }
# }

# 엔진 정보만 확인
curl -s http://localhost:8001/api/v1/info | jq '.engine'

# cpp_enabled: true 확인!
```

### Step 5: 수동 경로 계산 테스트

부하 테스트 전에 수동으로 1회 테스트:

```bash
# 경로 계산 요청
curl -X POST http://localhost:8001/api/v1/navigation/calculate \
  -H "Content-Type: application/json" \
  -d '{
    "origin": "강남",
    "destination": "서울역",
    "departure_time": "2024-12-10 09:00:00",
    "disability_type": "PHY"
  }' | jq

# 예상 응답:
# {
#   "routes": [
#     {
#       "rank": 1,
#       "total_time": 25.5,
#       "transfers": 1,
#       "segments": [...]
#     }
#   ],
#   "processing_time_ms": 145.67  ← C++ 엔진: ~100-200ms
# }
```

**성공 기준:**
- ✅ 응답 시간 < 500ms
- ✅ `routes` 배열에 최소 1개 경로
- ✅ 에러 없음

### Step 6: Locust 부하 테스트

#### A. Locust 설치

```bash
# Python 가상환경 (권장)
python3 -m venv venv
source venv/bin/activate

# Locust 설치
pip install locust
```

#### B. 웹 UI 모드

```bash
cd transit-routing/tests/load

# Locust 웹 서버 시작
locust -f locustfile_simple_cpp_test.py

# 브라우저에서 접속: http://localhost:8089
```

**웹 UI 설정:**
- Number of users: `50`
- Spawn rate: `5`
- Host: `http://localhost:8001`
- **Start swarming** 클릭

#### C. CLI 헤드리스 모드 (권장)

```bash
# 3분 테스트 실행
locust -f locustfile_simple_cpp_test.py \
  --host=http://localhost:8001 \
  --users 50 \
  --spawn-rate 5 \
  --run-time 3m \
  --headless \
  --html cpp_engine_test_report.html

# 실행 중 실시간 통계 출력:
# Type     Name                   # reqs   # fails  Median  Average  Min  Max
# POST     /api/v1/navigation...  1234     5 (0%)   145     167      82   523
# GET      /health                456      0 (0%)   12      15       8    45
```

#### D. 실시간 모니터링

**터미널 1: Locust 실행**
```bash
locust -f locustfile_simple_cpp_test.py
```

**터미널 2: 성능 메트릭 모니터링**
```bash
# 5초마다 메트릭 갱신
watch -n 5 'curl -s http://localhost:8001/api/v1/metrics | jq ".summary"'

# 출력:
# {
#   "total_requests": 1234,
#   "average_elapsed_time_ms": 167.89,  ← C++ 목표: < 300ms
#   "slow_requests": 12,                 ← 500ms 이상
#   "error_requests": 3,
#   "success_rate": 99.76
# }
```

**터미널 3: FastAPI 로그**
```bash
# 실시간 로그
docker logs -f kindmap-fastapi-test

# 성능 로그만
docker logs kindmap-fastapi-test | grep "PERFORMANCE:"
```

**터미널 4: 리소스 사용량**
```bash
# CPU, 메모리 모니터링
docker stats kindmap-fastapi-test

# 예상:
# CONTAINER           CPU %   MEM USAGE / LIMIT
# kindmap-fastapi...  40-50%  700-900MB / 1GB
```

### Step 7: 결과 분석

#### A. Locust HTML 리포트

```bash
# 리포트 열기
open cpp_engine_test_report.html  # macOS
xdg-open cpp_engine_test_report.html  # Linux
start cpp_engine_test_report.html  # Windows
```

**확인 항목:**
1. **Statistics 탭**
   - `/api/v1/navigation/calculate`:
     - Median: ~150ms (목표)
     - 95%ile: ~400ms (목표)
     - Failures: < 1%

2. **Charts 탭**
   - Response Times 그래프: 안정적인 추세선
   - Total Requests/s: 15-25 req/s (C++ 기대치)

#### B. 성능 메트릭 API

```bash
# 전체 통계
curl -s http://localhost:8001/api/v1/metrics | jq

# 요약 정보만
curl -s http://localhost:8001/api/v1/metrics | jq '.summary'

# 경로별 통계 (상위 10개)
curl -s http://localhost:8001/api/v1/metrics | jq '.top_paths'
```

#### C. 성능 목표 달성 여부

| 지표 | C++ 목표 | Python (참고) | 판정 기준 |
|------|----------|---------------|----------|
| 평균 응답 시간 | < 300ms | 500-800ms | Locust Average |
| P95 응답 시간 | < 500ms | 1500-2500ms | Locust 95%ile |
| 처리량 (RPS) | > 15 req/s | 5-10 req/s | Locust RPS |
| 에러율 | < 1% | - | Locust Failures |
| 메모리 사용 | < 1GB | 150-200MB | docker stats |

**성공 기준:**
- ✅ **C++ 엔진 활성화** (`engine_type: "cpp"`)
- ✅ **평균 응답 < 300ms** (Python 대비 2-3배 빠름)
- ✅ **에러율 < 1%**
- ✅ **처리량 > 15 req/s**

---

## 🔍 트러블슈팅

### 문제 1: FastAPI 컨테이너 시작 실패

**증상:**
```bash
docker ps -a
# STATUS: Exited (1)
```

**원인 확인:**
```bash
docker logs kindmap-fastapi-test
```

#### 원인 A: 외부 DB 연결 실패
```
ERROR: could not connect to server: Connection refused
```

**해결:**
```bash
# 1. .env.test 정보 재확인
cat .env.test | grep DB_

# 2. 로컬에서 DB 연결 테스트
telnet your-rds-endpoint.amazonaws.com 5432

# 3. 보안 그룹 확인 (AWS RDS)
# - 인바운드 규칙: PostgreSQL (5432) 허용
# - 소스: 현재 IP 또는 0.0.0.0/0 (테스트용)

# 4. 재시작
docker-compose -f docker-compose.cpp-test.yml restart fastapi
```

#### 원인 B: C++ 모듈 import 실패
```
ModuleNotFoundError: No module named 'pathfinding_cpp'
```

**해결:**
```bash
# 1. 이미지 재빌드
docker build -f Dockerfile.fastapi -t kindmap-fastapi:latest . 2>&1 | tee build.log

# 2. 빌드 로그에서 C++ 컴파일 확인
grep -i "compiling c++" build.log

# 3. 수동 테스트
docker run --rm kindmap-fastapi:latest python -c "import pathfinding_cpp"
```

### 문제 2: C++ 엔진이 비활성화됨

**증상:**
```bash
curl http://localhost:8001/api/v1/info | jq '.engine'
# {
#   "engine_type": "python",  ← Python으로 fallback!
#   "cpp_enabled": false
# }
```

**원인:** 환경 변수 `USE_CPP_ENGINE=true` 미적용

**해결:**
```bash
# 1. 환경 변수 확인
docker exec kindmap-fastapi-test env | grep CPP
# USE_CPP_ENGINE=true 확인

# 2. docker-compose.cpp-test.yml 확인
cat docker-compose.cpp-test.yml | grep USE_CPP

# 3. 재시작
docker-compose -f docker-compose.cpp-test.yml down
docker-compose -f docker-compose.cpp-test.yml up -d
```

### 문제 3: 응답 시간이 너무 느림

**증상:**
```
Locust 평균 응답: 2000ms (목표: < 300ms)
```

**원인 파악:**
```bash
# 1. 실제 엔진 확인
curl http://localhost:8001/api/v1/info | jq '.engine.engine_type'
# "cpp"인지 확인 (python이면 fallback됨)

# 2. DB 응답 시간 확인
docker logs kindmap-fastapi-test | grep "DB query"

# 3. 네트워크 지연 확인
ping your-rds-endpoint.amazonaws.com
# 평균 < 10ms 권장

# 4. 컨테이너 리소스 확인
docker stats kindmap-fastapi-test
# CPU > 90% → workers 증가 고려
```

**해결:**
```bash
# 1. C++ 엔진 강제 활성화 재확인
docker-compose -f docker-compose.cpp-test.yml down
# docker-compose.cpp-test.yml의 USE_CPP_ENGINE: "true" 확인
docker-compose -f docker-compose.cpp-test.yml up -d

# 2. 메모리 제한 완화 (필요시)
# docker-compose.cpp-test.yml에 추가:
# deploy:
#   resources:
#     limits:
#       memory: 2G  # 1GB → 2GB

# 3. DB 연결 풀 설정 확인
# config.py의 DB_CONFIG 확인
```

### 문제 4: Locust에서 모든 요청 실패

**증상:**
```
Locust: 100% failures - "Connection refused"
```

**해결:**
```bash
# 1. FastAPI 헬스체크
curl http://localhost:8001/health
# 응답 없으면 컨테이너 재시작

# 2. 포트 확인
netstat -tlnp | grep 8001  # Linux
lsof -i :8001  # macOS

# 3. 컨테이너 상태
docker ps | grep fastapi
# STATUS가 "healthy"인지 확인

# 4. Locust host 설정 확인
# locustfile에서 host = "http://localhost:8001" 확인
```

---

## 🧹 테스트 종료 및 정리

### 1. Locust 중지
```bash
# 웹 UI: Stop 버튼 클릭
# CLI: Ctrl+C
```

### 2. Docker 환경 정리
```bash
# 컨테이너 중지
docker-compose -f docker-compose.cpp-test.yml down

# 네트워크 정리
docker network prune -f

# 리소스 정리 (선택)
docker system prune -f
```

### 3. 리포트 백업
```bash
# 테스트 결과 백업
mkdir -p test_results
mv cpp_engine_test_report.html test_results/report_$(date +%Y%m%d_%H%M%S).html
```

---

## 📋 체크리스트

**배포 전:**
- [ ] `.env.test`에 실제 DB 정보 입력
- [ ] 외부 DB 연결 테스트 성공
- [ ] FastAPI 이미지 빌드 완료
- [ ] C++ 모듈 로드 확인

**테스트 중:**
- [ ] C++ 엔진 활성화 확인 (`engine_type: "cpp"`)
- [ ] 헬스체크 통과
- [ ] 수동 경로 계산 성공
- [ ] Locust 테스트 실행

**테스트 후:**
- [ ] 평균 응답 시간 < 300ms
- [ ] 에러율 < 1%
- [ ] HTML 리포트 저장
- [ ] Docker 컨테이너 정리

---

## 📈 예상 성능

### C++ 엔진 vs Python 엔진

| 시나리오 | Python | C++ | 개선율 |
|---------|--------|-----|--------|
| 간단한 경로 (1-2 환승) | 500-800ms | **100-200ms** | 4-5배 |
| 복잡한 경로 (3+ 환승) | 1500-2500ms | **250-500ms** | 5-6배 |
| 동시 50명 평균 | 700ms | **180ms** | 3.9배 |
| 처리량 (req/s) | 8-12 | **20-30** | 2.5배 |

---

## 🎯 요약: 한 줄 명령어

```bash
# 1. DB 정보 설정
nano .env.test  # DB_HOST, DB_USER, DB_PASSWORD 수정

# 2. 빌드 & 실행
docker build -f Dockerfile.fastapi -t kindmap-fastapi:latest . && \
docker-compose -f docker-compose.cpp-test.yml up -d

# 3. C++ 엔진 확인
curl http://localhost:8001/health | jq '.engine'

# 4. 부하 테스트
pip install locust && \
cd transit-routing/tests/load && \
locust -f locustfile_simple_cpp_test.py \
  --host=http://localhost:8001 \
  --users 50 --spawn-rate 5 --run-time 3m \
  --headless --html report.html

# 5. 결과 확인
open report.html
```

---

**작성일**: 2024-12-08  
**업데이트**: 외부 PostgreSQL 환경 대응
