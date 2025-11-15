# MC-RAPTOR 알고리즘 코드 구조 문서 v3

본 문서는 Multi-Criteria RAPTOR 알고리즘을 구현한 4개 파일의 클래스, 메서드, 함수를 정리한 문서입니다.

---

## 1. label.py

**파일 경로:** `C:\Users\yunha\Desktop\kindMap_Algorithm\transit-routing\label.py`

### 1.1 Label 클래스

**타입:** 데이터클래스 (dataclass, slots=True - 메모리 최적화)

**목적:** 대중교통 경로 탐색에서 다중 기준 경로 최적화를 위한 라벨(레이블)을 나타내는 핵심 데이터 구조

#### 속성 (Attributes)

| 속성명 | 타입 | 설명 |
|--------|------|------|
| `arrival_time` | `float` | 총 도착 시간 |
| `transfers` | `int` | 환승 횟수 |
| `convenience_sum` | `float` | 누적 편의성 점수 |
| `congestion_sum` | `float` | 누적 혼잡도 점수 |
| `max_transfer_difficulty` | `float` | 경로 중 최대 환승 난이도 |
| `parent_label` | `Optional[Label]` | 부모 라벨 포인터 (트리 구조) |
| `current_station_cd` | `str` | 현재 역 코드 |
| `current_line` | `str` | 현재 노선 |
| `current_direction` | `str` | 현재 진행 방향 |
| `visited_stations` | `frozenset` | 방문한 역 집합 (U-turn 방지용) |
| `depth` | `int` | 라벨 트리에서의 깊이 (기본값: 1) |
| `transfer_info` | `Optional[Tuple[str, str, str]]` | 환승 정보 (역, 출발노선, 도착노선) |
| `is_first_move` | `bool` | 양방향 탐색용 플래그 (기본값: False) |
| `created_round` | `int` | 생성된 라운드 번호 (기본값: 0) |

#### 프로퍼티 (Properties)

| 프로퍼티명 | 반환 타입 | 설명 |
|-----------|----------|------|
| `route_length` | `int` | 경로의 깊이(역 개수) 반환 |
| `avg_convenience` | `float` | 평균 편의성 점수 계산 (convenience_sum / depth) |
| `avg_congestion` | `float` | 평균 혼잡도 점수 계산 (congestion_sum / depth) |

#### 메서드 (Methods)

| 메서드명 | 반환 타입 | 설명 |
|---------|----------|------|
| `reconstruct_route()` | `List[str]` | 라벨 트리를 역추적하여 전체 경로를 재구성, 역 코드 리스트를 올바른 순서로 반환 |
| `reconstruct_lines()` | `List[str]` | 경로의 노선 정보를 재구성 |
| `reconstruct_transfer_info()` | `List[Tuple[str, str, str]]` | 환승 정보를 재구성 |
| `__eq__(other)` | `bool` | 역 코드, 노선, 환승 횟수를 기반으로 동등성 비교 |
| `__hash__()` | `int` | 역 코드, 노선, 환승 횟수를 기반으로 해시값 생성 |
| `dominates(other: Label)` | `bool` | 파레토 지배 관계 확인 - 최소 한 기준에서 더 좋고 다른 기준에서 나쁘지 않으면 True |
| `calculate_weighted_score(weights: Dict[str, float])` | `float` | ANP 가중치를 사용하여 가중 점수/패널티 계산 |

#### 독립 함수 (Standalone Functions)

없음

---

## 2. mc_raptor.py

**파일 경로:** `C:\Users\yunha\Desktop\kindMap_Algorithm\transit-routing\mc_raptor.py`

### 2.1 McRaptor 클래스

**목적:** 파레토 최적화를 사용한 Multi-Criteria RAPTOR 알고리즘 구현

#### 속성 (Attributes)

| 속성명 | 타입 | 설명 |
|--------|------|------|
| `distance_calculator` | `DistanceCalculator` | 거리 계산기 |
| `anp_calculator` | `ANPWeightCalculator` | ANP 가중치 계산기 |
| `transfers` | `Dict` | 환승 데이터 매핑 (역코드, 출발노선, 도착노선) → 환승 정보 |
| `stations` | `Dict` | 역 데이터 (역코드 → 역 정보) |
| `line_stations` | `Dict` | 노선-방향 매핑 |
| `station_order_map` | `Dict` | 역 순서 매핑 (방향 결정용) |
| `disability_type` | `str` | 현재 장애 유형 (기본값: "PHY") |
| `departure_time` | `datetime` | 현재 출발 시간 |

#### 메서드 (Methods)

##### 초기화 및 데이터 로딩

| 메서드명 | 반환 타입 | 설명 |
|---------|----------|------|
| `__init__()` | - | 라우터를 초기화하고 필요한 모든 데이터를 로드 |
| `_load_station_data()` | `None` | 데이터베이스에서 지하철 역 데이터 로드 |
| `_load_line_data()` | `None` | 방향성이 있는 노선 데이터 로드 (U-turn 방지용) |
| `_load_transfers()` | `None` | 환승 데이터 로드 (거리 + 편의성 점수) |

##### 헬퍼 메서드

| 메서드명 | 반환 타입 | 설명 |
|---------|----------|------|
| `_get_station_cd_by_name(station_name: str, line: str)` | `Optional[str]` | 역 이름과 노선으로 역 코드 찾기 |
| `_get_stations_on_line(station_cd: str, line: str)` | `Dict[str, List[str]]` | 노선의 역들을 방향별로 가져오기 |
| `_get_available_lines(station_cd: str)` | `List[str]` | 역에서 이용 가능한 노선 목록 |
| `_calculate_travel_time(from_cd: str, to_cd: str)` | `float` | 두 역 사이의 이동 시간 계산 |

##### 핵심 라우팅

| 메서드명 | 반환 타입 | 설명 |
|---------|----------|------|
| `find_routes(origin_cd: str, destination_cd_set: Set[str], departure_time: datetime, disability_type: str, max_rounds: int)` | `List[Label]` | 파레토 최적화를 사용한 Multi-Criteria RAPTOR 메인 경로 탐색 메서드 |
| `_create_new_label(...)` | `Label` | ANP 점수 계산과 함께 새 라벨 생성 |
| `_update_pareto_frontier(new_label: Label, existing_labels: List[Label])` | `bool` | 파레토 프론티어 업데이트, 지배당한 라벨 제거 |
| `rank_routes(routes: List[Label], disability_type: str)` | `List[Tuple[Label, float]]` | 패널티 점수로 경로를 순위화하고 중복 제거 |

##### 점수 계산

| 메서드명 | 반환 타입 | 설명 |
|---------|----------|------|
| `_get_convenience_score(station_cd: str, disability_type: str)` | `float` | ANP 편의성 점수 가져오기 |
| `_get_congestion_score(station_cd: str, line: str, direction: str, time: datetime)` | `float` | 혼잡도 점수 가져오기 |
| `_determine_direction(from_station_cd: str, to_station_cd: str, line: str)` | `str` | 이동 방향 결정 |

#### 독립 함수 (Standalone Functions)

없음

---

## 3. database.py

**파일 경로:** `C:\Users\yunha\Desktop\kindMap_Algorithm\transit-routing\database.py`

**클래스:** 없음 (함수 모듈)

### 3.1 전역 변수

| 변수명 | 타입 | 설명 |
|--------|------|------|
| `_connection_pool` | Connection Pool | PostgreSQL 연결 풀 (싱글톤 패턴) |
| `_distance_calculator` | `DistanceCalculator` | DistanceCalculator 인스턴스 (지연 초기화) |

### 3.2 함수 목록

#### 연결 풀 관리

| 함수명 | 반환 타입 | 설명 |
|--------|----------|------|
| `initialize_pool()` | `None` | 데이터베이스 연결 풀 초기화 (최소 10개, 최대 50개 연결) |
| `close_pool()` | `None` | 풀의 모든 연결 닫기 |

#### 컨텍스트 매니저

| 함수명 | 반환 타입 | 설명 |
|--------|----------|------|
| `get_db_connection()` | Context Manager | 데이터베이스 연결 가져오기 컨텍스트 매니저 |
| `get_db_cursor(cursor_factory=RealDictCursor)` | Context Manager | 자동 커밋/롤백 기능이 있는 데이터베이스 커서 컨텍스트 매니저 |

#### 헬퍼 함수

| 함수명 | 반환 타입 | 설명 |
|--------|----------|------|
| `get_distance_calculator()` | `DistanceCalculator` | DistanceCalculator 인스턴스 반환 (지연 초기화) |

#### 역 쿼리

| 함수명 | 반환 타입 | 설명 |
|--------|----------|------|
| `get_all_stations(line: Optional[str])` | `List[Dict]` | 모든 역 가져오기, 선택적으로 노선으로 필터링 |
| `get_station_by_code(station_cd: str)` | `Optional[Dict]` | 역 코드로 단일 역 가져오기 |
| `get_stations_by_codes(station_cds: List[str])` | `List[Dict]` | 여러 역에 대한 배치 쿼리 |
| `get_station_info(station_id: str)` | `Dict[str, any]` | station_id로 역 정보(코드와 이름) 가져오기 |
| `get_station_code(station_id: str)` | `str` | station_id로 station_cd 가져오기 |

#### 구간 쿼리

| 함수명 | 반환 타입 | 설명 |
|--------|----------|------|
| `get_all_sections(line: Optional[str])` | `List[Dict]` | 모든 지하철 구간 가져오기 |

#### 환승 쿼리

| 함수명 | 반환 타입 | 설명 |
|--------|----------|------|
| `get_all_transfer_station_conv_scores()` | `List[Dict]` | 모든 환승역 편의성 점수 가져오기 |
| `get_transfer_conv_score_by_code(station_cd: str)` | `Optional[Dict]` | 역 코드로 환승 편의성 점수 가져오기 |
| `get_transfer_distance(station_cd: str, from_line: str, to_line: str)` | `float` | 역에서 노선 간 환승 거리 가져오기 |

#### 공간 쿼리 (PostGIS)

| 함수명 | 반환 타입 | 설명 |
|--------|----------|------|
| `get_nearby_stations(lat: float, lon: float, radius_km: float)` | `List[Dict]` | 반경 내의 역 찾기 |

#### 거리 계산

| 함수명 | 반환 타입 | 설명 |
|--------|----------|------|
| `calculate_route_distance(route_station_cds: List[str])` | `Dict` | Haversine 공식을 사용한 총 경로 거리 계산 |

---

## 4. anp_weights.py

**파일 경로:** `C:\Users\yunha\Desktop\kindMap_Algorithm\transit-routing\anp_weights.py`

### 4.1 ANPWeightCalculator 클래스

**목적:** 다양한 장애 유형에 대한 ANP(Analytic Network Process) 가중치 계산

#### 속성 (Attributes)

| 속성명 | 타입 | 설명 |
|--------|------|------|
| `pairwise_matrices` | `Dict` | 각 장애 유형별 쌍대비교 행렬 |
| `_facility_preferences_cache` | `Optional[Dict]` | 캐시된 시설 선호도 |
| `congestion_data` | `Dict` | 데이터베이스에서 미리 로드된 혼잡도 데이터 |

#### 메서드 (Methods)

##### 초기화

| 메서드명 | 반환 타입 | 설명 |
|---------|----------|------|
| `__init__()` | - | 쌍대비교 행렬을 초기화하고 혼잡도 데이터 로드 |

##### 행렬 정의

| 메서드명 | 반환 타입 | 설명 |
|---------|----------|------|
| `_get_phy_matrix()` | `np.ndarray` | 휠체어 사용자 우선순위: 환승 > 난이도 > 편의성 > 혼잡도 > 시간 |
| `_get_vis_matrix()` | `np.ndarray` | 시각장애 우선순위: 편의성 > 난이도 > 환승 > 혼잡도 > 시간 |
| `_get_aud_matrix()` | `np.ndarray` | 청각장애 우선순위: 편의성 > 시간 > 난이도 > 환승 > 혼잡도 |
| `_get_eld_matrix()` | `np.ndarray` | 고령자 우선순위: 혼잡도 > 난이도 > 환승 > 편의성 > 시간 |

##### 가중치 계산

| 메서드명 | 반환 타입 | 설명 |
|---------|----------|------|
| `calculate_weights(disability_type: str)` | `Dict[str, float]` | 고유값 분해를 사용한 ANP 가중치 계산 |
| `_calculate_consistency_ratio(matrix: np.ndarray, max_eigenvalue: float)` | `float` | 일관성 비율(CR) 계산 |

##### 시간 계산

| 메서드명 | 반환 타입 | 설명 |
|---------|----------|------|
| `calculate_transfer_walking_time(transfer_distance: float, disability_type: str)` | `float` | 환승 보행 시간 계산 |

##### 혼잡도

| 메서드명 | 반환 타입 | 설명 |
|---------|----------|------|
| `_load_all_congestion_from_db()` | `Dict` | 시작 시 모든 혼잡도 데이터 미리 로드 |
| `get_congestion_from_rds(station_cd: str, line: str, direction: str, departure_time: datetime)` | `float` | 미리 로드된 데이터에서 혼잡도 점수 가져오기 (0.0-1.0+) |
| `_get_day_type(dt: datetime)` | `str` | 요일 유형 반환 (평일/토요일/일요일) |
| `_get_time_column(dt: datetime)` | `str` | datetime을 컬럼명으로 변환 (30분 간격) |
| `calculate_route_congestion_score(route_segments: List[Dict], departure_time: datetime)` | `float` | 전체 경로의 평균 혼잡도 계산 |

##### 난이도 및 편의성

| 메서드명 | 반환 타입 | 설명 |
|---------|----------|------|
| `calculate_transfer_difficulty(transfer_distance: float, facility_scores: Dict, disability_type: str)` | `float` | 환승 난이도 계산 (0.0-1.0) |
| `calculate_convenience_score(disability_type: str, facility_scores: Dict[str, float])` | `float` | 가중 편의성 점수 계산 (0.0-5.0) |

##### 시설 선호도

| 메서드명 | 반환 타입 | 설명 |
|---------|----------|------|
| `_load_facility_preferences_from_db()` | `Dict[str, Dict[str, float]]` | 데이터베이스에서 시설 선호도 로드 |
| `_get_default_facility_preferences()` | `Dict[str, Dict[str, float]]` | DB 실패 시 기본 시설 선호도 반환 |
| `get_facility_weights(disability_type: str)` | `Dict[str, float]` | 캐싱과 함께 시설 가중치 반환 |

#### 독립 함수 (Standalone Functions)

없음

---

## 전체 시스템 요약

4개의 파일이 함께 작동하여 정교한 다중 기준 대중교통 경로 탐색 시스템을 구현합니다:

1. **label.py**: 파레토 최적화를 사용한 경로 상태를 나타내는 핵심 데이터 구조
2. **mc_raptor.py**: Multi-Criteria RAPTOR 알고리즘을 구현하는 메인 라우팅 알고리즘
3. **database.py**: 연결 풀링과 쿼리 함수를 제공하는 데이터베이스 접근 계층
4. **anp_weights.py**: 다양한 사용자 유형에 대한 ANP 기반 가중치 계산 및 혼잡도/편의성 점수 산출

시스템은 5가지 기준(이동 시간, 환승 횟수, 환승 난이도, 편의성, 혼잡도)을 기반으로 경로를 최적화하며, 장애 유형(PHY, VIS, AUD, ELD)에 따라 서로 다른 우선순위를 적용합니다.

---

**문서 작성일:** 2025-11-11
**버전:** v3
