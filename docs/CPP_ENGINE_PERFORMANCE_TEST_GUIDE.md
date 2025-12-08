# C++ 엔진 성능 테스트 가이드

FastAPI 이미지만 빌드하여 C++ 경로 탐색 엔진의 성능을 간단히 테스트하는 방법

## 📋 목차

1. [사전 준비](#사전-준비)
2. [Docker 이미지 빌드](#docker-이미지-빌드)
3. [테스트 환경 실행](#테스트-환경-실행)
4. [Locust 부하 테스트](#locust-부하-테스트)
5. [결과 분석](#결과-분석)
6. [트러블슈팅](#트러블슈팅)

---

## 사전 준비

### 1. 필수 요구사항

- Docker 20.10 이상
- Docker Compose 2.0 이상
- Python 3.11 (Locust 실행용)
- 8GB+ RAM (권장)

### 2. 디렉토리 구조 확인

```
kindMap_Algorithm/
├── Dockerfile.fastapi              # FastAPI 이미지 빌드 파일
├── docker-compose.simple-test.yml  # 테스트용 구성 (신규)
├── transit-routing/
│   ├── tests/load/
│   │   └── locustfile_simple_cpp_test.py  # 간단한 테스트용 (신규)
│   └── ...
└── docs/
    └── CPP_ENGINE_PERFORMANCE_TEST_GUIDE.md  # 이 파일
```

---

## Docker 이미지 빌드

### 1단계: FastAPI 이미지 빌드

```bash
# 프로젝트 루트 디렉토리에서 실행
cd ~/kindMap_Algorithm

# FastAPI 이미지 빌드 (15-20분 소요)
docker build -f Dockerfile.fastapi -t kindmap-fastapi:latest .
```

**빌드 과정:**
- Python 의존성 설치
- Faster-Whisper 모델 다운로드 (~150MB)
- **C++ 모듈 컴파일** ⭐
- 최종 이미지 생성 (~1.2GB)

**빌드 성공 확인:**
```bash
# 이미지 확인
docker images | grep kindmap-fastapi

# 예상 출력:
# kindmap-fastapi   latest   abc123def456   2 minutes ago   1.2GB
```

**C++ 모듈 빌드 검증:**
```bash
# 컨테이너 임시 실행하여 C++ 모듈 확인
docker run --rm kindmap-fastapi:latest python -c "import pathfinding_cpp; print('✓ C++ module loaded successfully')"

# 성공 시 출력:
# ✓ C++ module loaded successfully
```

---

## 테스트 환경 실행

### 방법 1: 완전한 환경 (PostgreSQL + Redis + FastAPI) ⭐ 권장

실제 경로 계산까지 테스트 가능

#### A. DB 데이터 준비 (선택사항)

**DB 덤프 파일이 있는 경우:**
```bash
# DB 덤프를 준비
# docker-compose.simple-test.yml의 postgres 볼륨 마운트 설정 활성화
# volumes:
#   - ./db_dump.sql:/docker-entrypoint-initdb.d/init.sql
```

**DB 데이터가 없는 경우:**
- 헬스체크와 API 응답 속도만 테스트 가능
- 실제 경로 계산은 "데이터 없음" 에러 발생 (정상)

#### B. 테스트 환경 시작

```bash
# docker-compose로 전체 스택 시작
docker-compose -f docker-compose.simple-test.yml up -d

# 예상 출력:
# Creating network "kindmap-test-network" ... done
# Creating kindmap-postgres-test ... done
# Creating kindmap-redis-test ... done
# Creating kindmap-fastapi-test ... done
```

#### C. 서비스 상태 확인

```bash
# 컨테이너 상태 확인
docker ps

# 예상 출력 (모두 healthy 상태여야 함):
# CONTAINER ID   IMAGE                    STATUS                   PORTS
# abc123         kindmap-fastapi:latest   Up 30 seconds (healthy)  0.0.0.0:8001->8001/tcp
# def456         redis:7-alpine           Up 35 seconds (healthy)  0.0.0.0:6379->6379/tcp
# ghi789         postgres:15-alpine       Up 40 seconds (healthy)  0.0.0.0:5432->5432/tcp
```

#### D. FastAPI 로그 확인

```bash
# FastAPI 시작 로그 확인
docker logs kindmap-fastapi-test

# C++ 엔진 초기화 확인:
# ========================================
# KindMap Backend 시작 중...
# ========================================
# 1/4 PostgreSQL 연결 풀 초기화 중...
# 2/4 역 정보 캐시 초기화 중...
# 3/4 Redis 세션 클라이언트 초기화 중...
# 4/4 Redis Pub/Sub 초기화 중...
# ========================================
# KindMap Backend 시작 완료!
# ========================================
```

#### E. C++ 엔진 동작 확인

```bash
# 헬스체크
curl http://localhost:8001/health | jq

# 예상 응답:
# {
#   "status": "healthy",
#   "engine": {
#     "engine_type": "cpp",           ← C++ 엔진 확인
#     "engine_class": "PathfindingServiceCPP",
#     "cpp_enabled": true,
#     "description": "C++ pathfinding_cpp 모듈 (고성능)"
#   }
# }

# API 정보 확인
curl http://localhost:8001/api/v1/info | jq '.engine'

# C++ 엔진이 활성화되었는지 확인
```

---

## Locust 부하 테스트

### 1단계: Locust 설치

```bash
# Python 가상환경 생성 (권장)
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Locust 설치
pip install locust
```

### 2단계: 테스트 시나리오 선택

#### 옵션 A: 간단한 C++ 성능 테스트 (신규) ⭐ 권장

```bash
cd transit-routing/tests/load

# 간단한 테스트용 locustfile 사용
locust -f locustfile_simple_cpp_test.py
```

**특징:**
- 인증 없음 (로그인 불필요)
- 경로 계산 성능만 집중
- 동시 사용자 50명 목표
- 응답 시간 500ms 기준

#### 옵션 B: 기존 프로덕션 테스트

```bash
# 기존 locustfile 사용 (로그인 필요)
locust -f locustfile_http_load_test.py

# 주의: 이 파일은 프로덕션 환경용이므로 로그인 계정 필요
```

### 3단계: Locust 웹 UI 실행

```bash
# 브라우저에서 접속
# http://localhost:8089
```

**테스트 설정:**
- **Number of users**: 50 (동시 사용자)
- **Spawn rate**: 5 (초당 증가율)
- **Host**: http://localhost:8001

**Start swarming** 클릭

### 4단계: CLI 모드 실행 (헤드리스)

```bash
# 웹 UI 없이 CLI로 실행
locust -f locustfile_simple_cpp_test.py \
  --host=http://localhost:8001 \
  --users 50 \
  --spawn-rate 5 \
  --run-time 5m \
  --headless \
  --html cpp_engine_test_report.html

# 5분 후 자동 종료 및 리포트 생성
```

### 5단계: 실시간 모니터링

**터미널 1: Locust 실행**
```bash
locust -f locustfile_simple_cpp_test.py
```

**터미널 2: FastAPI 로그 모니터링**
```bash
# 실시간 로그 확인
docker logs -f kindmap-fastapi-test

# 성능 메트릭 필터링
docker logs kindmap-fastapi-test | grep "PERFORMANCE:"
```

**터미널 3: 성능 메트릭 API 확인**
```bash
# 5초마다 메트릭 조회
watch -n 5 'curl -s http://localhost:8001/api/v1/metrics | jq ".summary"'

# 예상 출력:
# {
#   "total_requests": 1234,
#   "average_elapsed_time_ms": 245.67,
#   "slow_requests": 12,
#   "error_requests": 3,
#   "success_rate": 99.76
# }
```

**터미널 4: 컨테이너 리소스 모니터링**
```bash
# CPU, 메모리 사용량 실시간 확인
docker stats kindmap-fastapi-test

# 예상:
# CONTAINER           CPU %   MEM USAGE / LIMIT   MEM %
# kindmap-fastapi-test   45%     800MB / 1GB         80%
```

---

## 결과 분석

### 1. Locust 리포트 확인

**웹 UI에서 확인:**
- **Statistics** 탭: 요청별 통계
  - Requests: 총 요청 수
  - Fails: 실패 수
  - Median: 중간값 응답 시간
  - 95%ile: P95 응답 시간
  - Average: 평균 응답 시간

- **Charts** 탭: 실시간 그래프
  - Total Requests per Second
  - Response Times (ms)
  - Number of Users

**HTML 리포트:**
```bash
# 생성된 리포트 열기
open cpp_engine_test_report.html  # macOS
# 또는
xdg-open cpp_engine_test_report.html  # Linux
# 또는
start cpp_engine_test_report.html  # Windows
```

### 2. 성능 목표 달성 여부

#### C++ 엔진 성능 목표

| 지표 | 목표 | Python 엔진 (참고) | C++ 엔진 (기대) |
|------|------|-------------------|----------------|
| **평균 응답 시간** | < 500ms | 500-800ms | 80-150ms |
| **P95 응답 시간** | < 1000ms | 1500-2500ms | 200-400ms |
| **처리량 (RPS)** | > 20 req/s | 5-10 req/s | 20-30 req/s |
| **에러율** | < 1% | - | < 1% |
| **메모리 사용** | < 1GB | 150-200MB | 80-120MB |

#### Python vs C++ 비교

| 항목 | Python | C++ | 개선율 |
|------|--------|-----|--------|
| 단순 경로 계산 | 500-800ms | 80-150ms | **5-6배** |
| 복잡 경로 계산 | 1500-2500ms | 200-400ms | **6-8배** |
| 메모리 사용 | 150-200MB | 80-120MB | 1.5-2배 절감 |

### 3. 병목 지점 분석

```bash
# 느린 요청 분석
docker logs kindmap-fastapi-test | grep "느린 요청" | tail -20

# 에러 로그 확인
docker logs kindmap-fastapi-test | grep -E "ERROR|Exception"

# 경로별 성능 통계
curl -s http://localhost:8001/api/v1/metrics | jq '.top_paths'
```

---

## 트러블슈팅

### 문제 1: FastAPI 컨테이너가 시작하지 않음

**증상:**
```bash
docker ps -a
# STATUS: Exited (1) 30 seconds ago
```

**원인 확인:**
```bash
docker logs kindmap-fastapi-test
```

**일반적인 원인:**

#### A. C++ 모듈 import 실패
```
ImportError: cannot import name 'pathfinding_cpp'
```

**해결:**
```bash
# 1. 이미지 재빌드
docker build -f Dockerfile.fastapi -t kindmap-fastapi:latest .

# 2. 빌드 로그에서 C++ 컴파일 확인
# "Compiling C++ module..." 메시지 확인

# 3. 모듈 확인
docker run --rm kindmap-fastapi:latest python -c "import pathfinding_cpp"
```

#### B. PostgreSQL 연결 실패
```
ERROR: DB 헬스 체크 실패: could not connect to server
```

**해결:**
```bash
# PostgreSQL이 healthy 상태인지 확인
docker ps | grep postgres

# PostgreSQL 로그 확인
docker logs kindmap-postgres-test

# 재시작
docker-compose -f docker-compose.simple-test.yml restart postgres
```

#### C. Redis 연결 실패
```
ERROR: Redis 헬스 체크 실패
```

**해결:**
```bash
# Redis 상태 확인
docker exec kindmap-redis-test redis-cli ping
# 출력: PONG

# Redis 재시작
docker-compose -f docker-compose.simple-test.yml restart redis
```

### 문제 2: Locust에서 모든 요청 실패

**증상:**
```
Fails: 100%, "Connection refused"
```

**해결:**
```bash
# 1. FastAPI 헬스체크
curl http://localhost:8001/health

# 2. 포트 확인
netstat -tlnp | grep 8001  # Linux
lsof -i :8001  # macOS

# 3. 방화벽 확인
sudo ufw status  # Ubuntu
sudo firewall-cmd --list-all  # CentOS

# 4. Docker 포트 매핑 확인
docker ps | grep 8001
```

### 문제 3: 응답 시간이 목표보다 느림

**증상:**
```
평균 응답 시간: 2000ms (목표: < 500ms)
```

**원인 분석:**

#### A. C++ 엔진이 비활성화됨
```bash
# 엔진 확인
curl http://localhost:8001/api/v1/info | jq '.engine'

# cpp_enabled: false인 경우
# → Python 엔진으로 fallback됨
```

**해결:**
```bash
# 환경 변수 확인
docker exec kindmap-fastapi-test env | grep CPP

# USE_CPP_ENGINE=true 확인
# 없으면 docker-compose.simple-test.yml 수정 후 재시작
docker-compose -f docker-compose.simple-test.yml down
docker-compose -f docker-compose.simple-test.yml up -d
```

#### B. DB 데이터 없음
```
ERROR: No data found for station
```

**해결:**
```bash
# DB에 데이터 삽입 필요
# 실제 프로덕션 DB에서 덤프 가져오기

# 또는 테스트 데이터 생성 스크립트 실행 (있는 경우)
```

#### C. 메모리 부족
```bash
# 시스템 메모리 확인
free -h

# Docker 메모리 사용량
docker stats

# Swap 추가
sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
sudo mkswap /swapfile
sudo swapon /swapfile
```

### 문제 4: C++ 모듈이 로드되지 않음

**증상:**
```python
ModuleNotFoundError: No module named 'pathfinding_cpp'
```

**원인:**
- 빌드 중 C++ 컴파일 실패
- pybind11 설치 누락
- CMake 설정 오류

**해결:**
```bash
# 1. 빌드 로그 상세 확인
docker build -f Dockerfile.fastapi -t kindmap-fastapi:latest . 2>&1 | tee build.log

# 2. C++ 컴파일 에러 찾기
grep -E "error|ERROR|failed" build.log

# 3. 수동 빌드 테스트
docker run --rm -it kindmap-fastapi:latest bash
cd /app/transit-routing
pip install -e . -v  # verbose 모드로 재설치
```

---

## 테스트 종료 및 정리

### 1. Locust 중지

```bash
# 웹 UI에서 "Stop" 버튼 클릭
# 또는 터미널에서 Ctrl+C
```

### 2. Docker 환경 중지

```bash
# 컨테이너 중지
docker-compose -f docker-compose.simple-test.yml down

# 볼륨도 삭제 (DB 데이터 포함)
docker-compose -f docker-compose.simple-test.yml down -v

# 네트워크 정리
docker network prune -f
```

### 3. 리소스 정리

```bash
# 사용하지 않는 이미지 삭제
docker image prune -a

# 전체 Docker 시스템 정리 (주의!)
docker system prune -a --volumes
```

---

## 요약: 간단한 테스트 실행 명령어

```bash
# 1. 이미지 빌드
docker build -f Dockerfile.fastapi -t kindmap-fastapi:latest .

# 2. 테스트 환경 시작
docker-compose -f docker-compose.simple-test.yml up -d

# 3. C++ 엔진 확인
curl http://localhost:8001/health | jq '.engine'

# 4. Locust 설치 (최초 1회)
pip install locust

# 5. 부하 테스트 실행 (CLI)
cd transit-routing/tests/load
locust -f locustfile_simple_cpp_test.py \
  --host=http://localhost:8001 \
  --users 50 \
  --spawn-rate 5 \
  --run-time 5m \
  --headless \
  --html report.html

# 6. 결과 확인
open report.html

# 7. 정리
docker-compose -f docker-compose.simple-test.yml down
```

---

## 추가 리소스

- [Locust 공식 문서](https://docs.locust.io/)
- [Docker Compose 문서](https://docs.docker.com/compose/)
- [FastAPI 공식 문서](https://fastapi.tiangolo.com/)

---

**작성일**: 2024-12-08  
**버전**: 1.0.0
