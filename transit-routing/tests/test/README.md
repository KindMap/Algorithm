# Transit-Routing 테스트 가이드

## 📋 목차
1. [테스트 환경 설정](#테스트-환경-설정)
2. [테스트 실행 방법](#테스트-실행-방법)
3. [테스트 구조](#테스트-구조)
4. [테스트 커버리지](#테스트-커버리지)

---

## 🔧 테스트 환경 설정

### 1. 필수 패키지 설치

```bash
# 프로젝트 루트 디렉토리에서 실행
cd transit-routing

# 테스트 의존성 설치
pip install -r test/requirements-test.txt
```

### 2. 환경 변수 설정

테스트를 위한 `.env.test` 파일 생성 (선택 사항):

```env
DEBUG=True
REDIS_HOST=localhost
REDIS_PORT=6379
DB_HOST=localhost
DB_PORT=5432
DB_NAME=test_db
DB_USER=test_user
DB_PASSWORD=test_password
```

---

## 🚀 테스트 실행 방법

### 전체 테스트 실행

```bash
# 프로젝트 루트에서
pytest test/

# 또는 상세한 출력과 함께
pytest test/ -v

# 실패한 테스트만 다시 실행
pytest test/ --lf
```

### 특정 테스트 파일 실행

```bash
# PathfindingService 테스트만 실행
pytest test/test_pathfinding_service.py

# GuidanceService 테스트만 실행
pytest test/test_guidance_service.py

# WebSocket 테스트만 실행
pytest test/test_websocket.py
```

### 특정 테스트 클래스/메서드 실행

```bash
# 특정 테스트 클래스
pytest test/test_pathfinding_service.py::TestPathfindingService

# 특정 테스트 메서드
pytest test/test_pathfinding_service.py::TestPathfindingService::test_calculate_route_success

# 키워드로 필터링
pytest test/ -k "distance"
```

### 테스트 커버리지 확인

```bash
# 커버리지 측정
pytest test/ --cov=app --cov-report=html

# 커버리지 리포트 확인
# htmlcov/index.html 파일을 브라우저로 열기

# 터미널에서 커버리지 확인
pytest test/ --cov=app --cov-report=term-missing
```

### 병렬 실행 (빠른 테스트)

```bash
# pytest-xdist 설치 필요
pip install pytest-xdist

# 4개의 프로세스로 병렬 실행
pytest test/ -n 4
```

---

## 📁 테스트 구조

```
test/
├── conftest.py                      # Pytest 설정 및 공통 Fixture
├── test_pathfinding_service.py      # PathfindingService 테스트
├── test_guidance_service.py         # GuidanceService 테스트
├── test_redis_client.py             # RedisSessionManager 테스트
├── test_distance_calculator.py      # DistanceCalculator 테스트
├── test_cache.py                    # Cache 모듈 테스트
├── test_websocket.py                # WebSocket 엔드포인트 테스트
├── test_routing_local.py            # 로컬 통합 테스트 (기존)
├── requirements-test.txt            # 테스트 의존성
└── README.md                        # 이 파일
```

---

## 🧪 테스트 파일별 설명

### 1. `conftest.py`
- **공통 Fixture 정의**
  - `mock_redis_client`: Mock Redis 클라이언트
  - `sample_stations`: 테스트용 역 데이터
  - `sample_route_data`: 테스트용 경로 데이터
  - `seoul_gps_coords`: 서울 지역 GPS 좌표

### 2. `test_pathfinding_service.py` (11개 테스트)
- ✅ 서비스 초기화
- ✅ 정상적인 경로 계산
- ✅ 유효하지 않은 출발지/목적지 처리
- ✅ 경로를 찾을 수 없는 경우
- ✅ 여러 경로 반환
- ✅ 모든 장애 유형 테스트
- ✅ 경로 정보 반올림 처리

### 3. `test_guidance_service.py` (15개 테스트)
- ✅ KD-Tree를 사용한 최근접 역 검색
- ✅ GPS 좌표 검증
- ✅ 경로 상 내비게이션
- ✅ 경로 이탈 감지
- ✅ 목적지 도착 감지
- ✅ 환승역 안내
- ✅ 진행률 계산
- ✅ KD-Tree 성능 테스트

### 4. `test_redis_client.py` (11개 테스트)
- ✅ 세션 생성/조회/삭제
- ✅ 경로 변경
- ✅ 위치 업데이트
- ✅ 세션 TTL (4시간)
- ✅ 전체 경로 저장

### 5. `test_distance_calculator.py` (15개 테스트)
- ✅ Haversine 공식 정확도
- ✅ 알려진 위치 간 거리 계산
- ✅ 거리 계산의 대칭성
- ✅ 남북/동서/대각선 방향 거리
- ✅ 단거리/장거리 계산

### 6. `test_cache.py` (11개 테스트)
- ✅ 싱글톤 패턴
- ✅ 역 딕셔너리 조회
- ✅ 역 이름 ↔ 역 코드 변환
- ✅ 노선 딕셔너리 조회
- ✅ 스레드 안전성

### 7. `test_websocket.py` (18개 테스트)
- ✅ 연결 관리 (연결/해제)
- ✅ 중복 연결 처리
- ✅ 최대 연결 수 제한
- ✅ 메시지 전송
- ✅ 경로 계산/위치 업데이트
- ✅ 경로 변경/재계산
- ✅ 내비게이션 종료

---

## 📊 테스트 커버리지

### 목표 커버리지
- **전체**: 80% 이상
- **핵심 서비스**: 90% 이상
  - PathfindingService
  - GuidanceService
  - RedisSessionManager
  - WebSocket handlers

### 현재 커버리지 확인

```bash
pytest test/ --cov=app --cov-report=term-missing

# 예상 출력:
# app/services/pathfinding_service.py    95%
# app/services/guidance_service.py       92%
# app/db/redis_client.py                 88%
# app/algorithms/distance_calculator.py  100%
# app/api/v1/endpoints/websocket.py      85%
```

---

## 🔍 테스트 작성 가이드

### 1. 테스트 명명 규칙
```python
def test_<기능>_<시나리오>():
    """테스트 설명"""
    # Given (준비)
    # When (실행)
    # Then (검증)
```

### 2. Fixture 사용
```python
def test_example(sample_stations, mock_redis_client):
    # Fixture를 파라미터로 받아서 사용
    assert len(sample_stations) > 0
```

### 3. Mock 사용
```python
from unittest.mock import patch, MagicMock

@patch("app.services.pathfinding_service.McRaptor")
def test_with_mock(mock_raptor_class):
    mock_raptor_class.return_value.find_routes.return_value = [...]
```

### 4. 비동기 테스트
```python
@pytest.mark.asyncio
async def test_async_function():
    result = await async_function()
    assert result is not None
```

---

## ⚠️ 주의사항

### 1. 실제 데이터베이스 사용 금지
- 테스트는 Mock을 사용하여 DB 접근을 피해야 합니다
- 통합 테스트가 필요한 경우 별도의 테스트 DB 사용

### 2. 외부 의존성 최소화
- Redis, PostgreSQL 등은 Mock으로 대체
- 실제 서비스 호출 금지

### 3. 테스트 독립성
- 각 테스트는 독립적으로 실행 가능해야 함
- 테스트 간 상태 공유 금지

### 4. 빠른 실행 시간
- 단위 테스트는 1초 이내 실행
- 느린 테스트는 별도 마커로 분리

---

## 🐛 문제 해결

### ImportError 발생 시
```bash
# PYTHONPATH 설정
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# 또는 프로젝트 루트에서 실행
cd transit-routing
pytest test/
```

### ModuleNotFoundError: No module named 'app'
```bash
# 프로젝트가 올바른 위치에 있는지 확인
pwd
# /path/to/kindMap_Algorithm/transit-routing

# 상위 디렉토리로 이동하지 말고 현재 위치에서 실행
pytest test/
```

### Async 테스트 실패 시
```bash
# pytest-asyncio 설치 확인
pip install pytest-asyncio

# pytest.ini 또는 setup.cfg 확인
# [tool:pytest]
# asyncio_mode = auto
```

---

## 📝 추가 리소스

- [Pytest 공식 문서](https://docs.pytest.org/)
- [Pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
- [Pytest-cov](https://pytest-cov.readthedocs.io/)
- [unittest.mock](https://docs.python.org/3/library/unittest.mock.html)

---

## ✅ 테스트 체크리스트

새로운 기능 추가 시:
- [ ] 단위 테스트 작성 (함수/메서드별)
- [ ] 예외 상황 테스트
- [ ] Edge case 테스트
- [ ] 통합 테스트 (필요 시)
- [ ] 커버리지 80% 이상 유지
- [ ] 모든 테스트 통과 확인

코드 수정 시:
- [ ] 관련 테스트 업데이트
- [ ] 회귀 테스트 실행
- [ ] 커버리지 감소 여부 확인
