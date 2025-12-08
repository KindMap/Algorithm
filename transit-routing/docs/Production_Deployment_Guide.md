# 프로덕션 배포 가이드

## 목차
1. [환경 설정](#환경-설정)
2. [C++ 엔진 빌드](#c-엔진-빌드)
3. [Docker 배포](#docker-배포)
4. [환경 변수 설정](#환경-변수-설정)
5. [성능 모니터링](#성능-모니터링)
6. [헬스체크 및 모니터링](#헬스체크-및-모니터링)
7. [로깅 설정](#로깅-설정)
8. [트러블슈팅](#트러블슈팅)

---

## 환경 설정

### 요구사항
- Python 3.11+
- PostgreSQL 12+
- Redis 6+
- C++ 컴파일러 (GCC 7+ 또는 Clang 5+)
- CMake 3.15+
- Nginx (프록시용)

### Python 의존성 설치
```bash
cd transit-routing
pip install -r requirements.txt
```

---

## C++ 엔진 빌드

### AWS EC2 Linux 환경

```bash
# 1. 빌드 도구 설치 (Amazon Linux 2)
sudo yum update -y
sudo yum install -y gcc-c++ cmake3 make

# Python 개발 헤더 설치
sudo yum install -y python3-devel

# 2. pybind11 설치
pip install pybind11

# 3. C++ 엔진 빌드
cd transit-routing/cpp_src
mkdir -p build
cd build

# CMake 구성 (Release 모드)
cmake3 .. -DCMAKE_BUILD_TYPE=Release

# 빌드 (병렬 컴파일)
make -j$(nproc)

# 4. 빌드 확인
ls -lh pathfinding_cpp*.so
# 출력: pathfinding_cpp.cpython-311-x86_64-linux-gnu.so
```

### Ubuntu/Debian 환경

```bash
# 1. 빌드 도구 설치
sudo apt-get update
sudo apt-get install -y build-essential cmake python3-dev

# 2. pybind11 설치
pip install pybind11

# 3. C++ 엔진 빌드
cd transit-routing/cpp_src
mkdir -p build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
```

### 빌드 검증

```python
# Python에서 모듈 테스트
python3 -c "import pathfinding_cpp; print('C++ module loaded successfully!')"
```

---

## Docker 배포

### Dockerfile (개선 버전)

```dockerfile
# 멀티 스테이지 빌드
FROM python:3.11-slim as builder

# 빌드 의존성 설치
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install pybind11

# C++ 엔진 빌드
COPY transit-routing/cpp_src ./cpp_src
RUN cd cpp_src && \
    mkdir build && cd build && \
    cmake .. -DCMAKE_BUILD_TYPE=Release && \
    make -j$(nproc)

# 런타임 이미지
FROM python:3.11-slim

# 런타임 의존성만 설치
RUN apt-get update && apt-get install -y \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python 의존성 복사
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

# C++ 엔진 복사
COPY --from=builder /app/cpp_src/build/pathfinding_cpp*.so ./cpp_src/build/

# 애플리케이션 코드 복사
COPY transit-routing .

# PYTHONPATH 설정
ENV PYTHONPATH=/app:/app/cpp_src/build

# 헬스체크
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8001/health')"

# 실행
EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "4"]
```

### Docker Compose (프로덕션)

```yaml
version: '3.8'

services:
  fastapi:
    build:
      context: .
      dockerfile: Dockerfile.fastapi
    image: ${FASTAPI_IMAGE_URI}
    container_name: kindmap-fastapi
    env_file:
      - .env.production
    environment:
      - USE_CPP_ENGINE=true
      - ENABLE_PERFORMANCE_MONITORING=true
      - ENABLE_CACHE_METRICS=true
    expose:
      - 8001
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped
    networks:
      - kindmap-network

  nginx:
    image: ${NGINX_IMAGE_URI}
    container_name: kindmap-nginx
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/conf.d:/etc/nginx/conf.d:ro
      - ./ssl:/etc/nginx/ssl:ro
    depends_on:
      - fastapi
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped
    networks:
      - kindmap-network

  postgres:
    image: postgres:15
    container_name: kindmap-postgres
    environment:
      POSTGRES_DB: ${DB_NAME}
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped
    networks:
      - kindmap-network

  redis:
    image: redis:7-alpine
    container_name: kindmap-redis
    command: redis-server --appendonly yes
    volumes:
      - redis-data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped
    networks:
      - kindmap-network

volumes:
  postgres-data:
  redis-data:

networks:
  kindmap-network:
    driver: bridge
```

---

## 환경 변수 설정

### .env.production 파일

```bash
# 애플리케이션 설정
PROJECT_NAME=KindMap Backend
VERSION=4.0.0
DEBUG=false
PORT=8001

# 데이터베이스
DB_HOST=your-rds-endpoint.rds.amazonaws.com
DB_PORT=5432
DB_NAME=kindmap_db
DB_USER=postgres
DB_PASSWORD=your-secure-password

# Redis
REDIS_HOST=your-redis-endpoint
REDIS_PORT=6379
REDIS_MAX_CONNECTIONS=50

# Redis Pub/Sub
REDIS_PUBSUB_ENABLED=true
REDIS_PUBSUB_CHANNEL=kindmap_events

# 세션 및 캐시
SESSION_TTL_SECONDS=1800
ROUTE_CACHE_TTL_SECONDS=1209600

# C++ 엔진 사용
USE_CPP_ENGINE=true

# 성능 모니터링
ENABLE_PERFORMANCE_MONITORING=true
SLOW_REQUEST_THRESHOLD_MS=1000
ENABLE_CACHE_METRICS=true

# CORS
ALLOWED_ORIGINS=https://kindmap-for-you.cloud,https://www.kindmap-for-you.cloud

# JWT (향후 사용)
JWT_SECRET_KEY=your-jwt-secret-key-change-this
JWT_ALGORITHM=HS256

# Celery (백그라운드 작업)
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2
```

### 환경별 설정 분리

```bash
# 개발 환경
.env.development
USE_CPP_ENGINE=false
DEBUG=true
ENABLE_PERFORMANCE_MONITORING=false

# 스테이징 환경
.env.staging
USE_CPP_ENGINE=true
DEBUG=false
ENABLE_PERFORMANCE_MONITORING=true

# 프로덕션 환경
.env.production
USE_CPP_ENGINE=true
DEBUG=false
ENABLE_PERFORMANCE_MONITORING=true
SLOW_REQUEST_THRESHOLD_MS=500
```

---

## 성능 모니터링

### 미들웨어 활성화

FastAPI 애플리케이션에 이미 통합되어 있습니다:

```python
# app/main.py
if settings.ENABLE_PERFORMANCE_MONITORING:
    app.add_middleware(PerformanceMonitoringMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
```

### 메트릭 조회

```bash
# 성능 메트릭 API
curl http://localhost:8001/api/v1/metrics

# 응답 예시
{
  "summary": {
    "total_requests": 1234,
    "average_elapsed_time_ms": 245.67,
    "slow_requests": 12,
    "error_requests": 3,
    "success_rate": 99.76
  },
  "top_paths": [
    {
      "path": "POST /api/v1/navigation/calculate",
      "count": 567,
      "avg_time_ms": 320.45,
      "slow_count": 8,
      "error_count": 1
    }
  ],
  "configuration": {
    "slow_request_threshold_ms": 1000,
    "monitoring_enabled": true
  }
}
```

### 로그 분석

모든 요청은 JSON 형식으로 로깅됩니다:

```json
{
  "event": "http_request",
  "method": "POST",
  "path": "/api/v1/navigation/calculate",
  "status_code": 200,
  "elapsed_time_ms": 345.67,
  "slow_request": false,
  "client_host": "192.168.1.100"
}
```

---

## 헬스체크 및 모니터링

### 헬스체크 엔드포인트

```bash
curl http://localhost:8001/health

# 응답 예시
{
  "status": "healthy",
  "version": "4.0.0",
  "timestamp": 1702123456.789,
  "components": {
    "database": "healthy",
    "redis": "healthy",
    "pathfinding_engine": "healthy"
  },
  "engine": {
    "engine_type": "cpp",
    "engine_class": "PathfindingServiceCPP",
    "cpp_enabled": true,
    "description": "C++ pathfinding_cpp 모듈 (고성능)"
  },
  "performance": {
    "total_requests": 1234,
    "average_elapsed_time_ms": 245.67,
    "slow_requests": 12,
    "error_requests": 3,
    "success_rate": 99.76
  }
}
```

### 모니터링 도구 통합

#### Prometheus (선택사항)

```python
# requirements.txt에 추가
prometheus-fastapi-instrumentator==6.1.0

# app/main.py에 추가
from prometheus_fastapi_instrumentator import Instrumentator

Instrumentator().instrument(app).expose(app)
```

#### CloudWatch (AWS)

```python
# CloudWatch 로그 그룹 생성
aws logs create-log-group --log-group-name /aws/kindmap/fastapi

# 로그 스트림 생성
aws logs create-log-stream \
  --log-group-name /aws/kindmap/fastapi \
  --log-stream-name production-$(date +%Y%m%d)
```

---

## 로깅 설정

### 로그 레벨

```python
# 프로덕션: INFO
logging.basicConfig(level=logging.INFO)

# 개발: DEBUG
logging.basicConfig(level=logging.DEBUG)
```

### 로그 로테이션

```python
# logging_config.py
import logging
from logging.handlers import RotatingFileHandler

handler = RotatingFileHandler(
    'logs/kindmap.log',
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5
)
handler.setFormatter(
    logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
)

logging.getLogger().addHandler(handler)
```

---

## 트러블슈팅

### 1. C++ 모듈 import 실패

**문제**:
```
ImportError: No module named 'pathfinding_cpp'
```

**해결**:
```bash
# PYTHONPATH 설정
export PYTHONPATH=$PYTHONPATH:/app/cpp_src/build

# 또는 Docker에서
ENV PYTHONPATH=/app:/app/cpp_src/build
```

### 2. 느린 응답 시간

**체크리스트**:
- [ ] C++ 엔진이 Release 모드로 빌드되었는지 확인
- [ ] Redis 캐시가 활성화되어 있는지 확인
- [ ] 데이터베이스 연결 풀 설정 확인
- [ ] /api/v1/metrics 엔드포인트로 성능 분석

**해결**:
```bash
# 메트릭 조회
curl http://localhost:8001/api/v1/metrics

# 느린 요청 로그 확인
grep "느린 요청 감지" logs/kindmap.log
```

### 3. 메모리 부족

**해결**:
```bash
# Docker 메모리 제한 증가
docker run -m 4g ...

# 또는 docker-compose.yml
services:
  fastapi:
    mem_limit: 4g
```

---

## 배포 체크리스트

### 배포 전
- [ ] C++ 엔진 빌드 완료
- [ ] 환경 변수 설정 (.env.production)
- [ ] 데이터베이스 마이그레이션 완료
- [ ] Redis 연결 테스트
- [ ] SSL 인증서 설정 (HTTPS)
- [ ] CORS 설정 확인

### 배포 후
- [ ] 헬스체크 정상 확인
- [ ] 성능 메트릭 모니터링
- [ ] 로그 확인 (에러 없는지)
- [ ] 경로 계산 API 테스트
- [ ] WebSocket 연결 테스트
- [ ] 부하 테스트 (선택사항)

### 모니터링 설정
- [ ] CloudWatch 알람 설정
- [ ] 헬스체크 모니터링
- [ ] 에러 알림 설정
- [ ] 성능 대시보드 구성

---

## 성능 최적화 팁

### 1. C++ 엔진 사용
```bash
USE_CPP_ENGINE=true
```
→ 5~10배 성능 향상

### 2. Redis 캐싱 적극 활용
```bash
ROUTE_CACHE_TTL_SECONDS=1209600  # 14일
```

### 3. 연결 풀 최적화
```python
# DB 연결 풀
max_connections=50

# Redis 연결 풀
REDIS_MAX_CONNECTIONS=50
```

### 4. Uvicorn workers 조정
```bash
uvicorn app.main:app --workers 4 --host 0.0.0.0 --port 8001
```

---

## 요약

프로덕션 배포 시 핵심:
1. ✅ C++ 엔진 빌드 및 활성화 (USE_CPP_ENGINE=true)
2. ✅ 성능 모니터링 활성화
3. ✅ 헬스체크 및 메트릭 모니터링
4. ✅ 환경별 설정 분리
5. ✅ 로그 수집 및 분석

이 가이드를 따라 안정적이고 고성능의 프로덕션 환경을 구축할 수 있습니다.
