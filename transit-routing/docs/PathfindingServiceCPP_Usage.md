# PathfindingServiceCPP 사용 가이드

## 개요

**PathfindingServiceCPP**는 C++로 구현된 고성능 Multi-Criteria RAPTOR 알고리즘을 사용하는 경로 탐색 서비스입니다. Python 버전의 `PathfindingService`와 동일한 인터페이스를 제공하지만, 핵심 알고리즘 실행 속도가 **5~10배 빠릅니다**.

## 특징

### ✅ 장점
- **고성능**: C++ 네이티브 코드로 구현된 RAPTOR 알고리즘
- **메모리 효율**: Label Pool 기반 메모리 재사용
- **Thread-safe**: 동시 요청 처리 최적화
- **호환성**: Python PathfindingService와 동일한 API

### ⚠️ 요구사항
- C++17 컴파일러 (GCC 7+ 또는 Clang 5+)
- pybind11 라이브러리
- CMake 3.15+
- Python 3.11+

## 설치

### 1. C++ 엔진 빌드

```bash
cd transit-routing/cpp_src

# CMake 빌드 디렉토리 생성
mkdir -p build
cd build

# CMake 구성 (Release 모드)
cmake .. -DCMAKE_BUILD_TYPE=Release

# 빌드
make -j$(nproc)

# 설치 (선택사항)
sudo make install
```

**빌드 결과**: `pathfinding_cpp.cpython-311-x86_64-linux-gnu.so` 파일 생성

### 2. Python에서 확인

```python
# C++ 모듈 import 테스트
import pathfinding_cpp

print("C++ 모듈 로드 성공!")
print(f"사용 가능한 클래스: {dir(pathfinding_cpp)}")
# 출력: ['DataContainer', 'Label', 'McRaptorEngine', ...]
```

## 기본 사용법

### PathfindingServiceCPP 초기화

```python
from app.services.pathfinding_service_cpp import PathfindingServiceCPP

# 서비스 초기화 (데이터 로드 포함 - 5~10초 소요)
service = PathfindingServiceCPP()
```

**초기화 과정**:
1. C++ `pathfinding_cpp` 모듈 import
2. 데이터베이스에서 역/노선/환승/혼잡도 데이터 로드
3. C++ `DataContainer`에 데이터 전송
4. `McRaptorEngine` 초기화
5. Redis 캐시 클라이언트 연결

### 경로 계산

```python
# 기본 경로 계산
result = service.calculate_route(
    origin_name="강남",
    destination_name="서울역",
    disability_type="PHY"  # PHY/VIS/AUD/ELD
)

print(f"발견된 경로: {result['total_routes_found']}개")
print(f"반환된 경로: {len(result['routes'])}개")

# 최적 경로 정보
best_route = result['routes'][0]
print(f"순위: {best_route['rank']}")
print(f"소요시간: {best_route['total_time']}분")
print(f"환승: {best_route['transfers']}회")
print(f"ANP 점수: {best_route['score']}")
```

## 프로덕션 배포

### 환경 변수

```bash
# .env 파일
ROUTE_CACHE_TTL_SECONDS=1209600  # 14일
ENABLE_CACHE_METRICS=true
USE_CPP_ENGINE=true  # C++ 엔진 사용 여부
```

## 요약

PathfindingServiceCPP는 기존 Python 버전과 **100% 호환되는 인터페이스**를 제공하면서도 **5~10배 빠른 성능**을 달성합니다.
