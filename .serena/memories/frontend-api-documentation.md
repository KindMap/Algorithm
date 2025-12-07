# KindMap Transit Routing API - 프론트엔드 연동 가이드

## 프로젝트 개요

**서비스**: KindMap Backend v4.0.0  
**목적**: 서울 지하철 실시간 접근성 경로 안내 시스템  
**현재 브랜치**: jwt-login-implement (JWT 구현 예정, 현재 미활성)  
**Base URL**: `http://your-domain/api/v1` (Nginx 프록시 경유)  
**API 문서**: `/docs` (Swagger UI), `/redoc` (ReDoc)

## 아키텍처

```
[프론트엔드] → [Nginx:80] → [FastAPI:8001] → [PostgreSQL + Redis]
```

- **Nginx**: CORS 처리 및 라우팅을 담당하는 리버스 프록시
- **FastAPI**: Python 비동기 백엔드 (WebSocket 지원)
- **Redis**: 세션 관리 (4시간 TTL)
- **PostgreSQL**: 역/노선 데이터 저장소

---

## 1. API 엔드포인트 개요

### 사용 가능한 엔드포인트

| 카테고리 | 엔드포인트 | 메소드 | 설명 |
|----------|----------|--------|------|
| **경로 계산** | `/api/v1/navigation/calculate` | POST | 상위 3개 경로 계산 (WebSocket 대신 REST 사용 가능) |
| **역 검색** | `/api/v1/stations/search` | GET | 자동완성용 역 검색 |
| **역 유효성 검사** | `/api/v1/stations/validate` | POST | 역명 유효성 검증 |
| **노선 정보** | `/api/v1/stations/lines` | GET | 전체 지하철 노선 조회 |
| **실시간 내비게이션** | `/api/v1/ws/{user_id}` | WebSocket | 실시간 경로 안내 |
| **헬스 체크** | `/health` | GET | 서버 상태 확인 |
| **API 정보** | `/api/v1/info` | GET | API 메타데이터 |

---

## 2. 인증 및 권한

### 현재 상태 (jwt-login-implement 브랜치)

**⚠️ 중요**: JWT 인증이 **현재 구현되어 있지 않음** (브랜치명과 무관)

**설치된 의존성** (requirements.txt):
```python
python-jose[cryptography]==3.3.0  # JWT 라이브러리
passlib[bcrypt]==1.7.4            # 비밀번호 해싱
slowapi==0.1.9                    # Rate limiting
```

### 현재 API 접근
- **인증 불필요** - 모든 엔드포인트 자유 접근
- **CORS**: 모든 origin 허용 (`allow_origins=["*"]`)
- **헤더**: 특별한 인증 헤더 불필요

### 향후 예상 구현
JWT 구현 시 예상 형식:
```http
Authorization: Bearer <jwt_token>
```

---

## 3. CORS 설정

**현재 설정** (`main.py`):

```python
CORS 설정:
- allow_origins: ["*"]  # 모든 origin 허용 (개발 모드)
- allow_credentials: true
- allow_methods: ["*"]
- allow_headers: ["*"]
```

**프로덕션 설정** (주석 처리됨):
```python
# 권장 프로덕션 origin:
- http://localhost:3000
- http://localhost:8080
- https://kindmap.kr  # 프로덕션 도메인
```

---

## 4. REST API 엔드포인트

### 4.1 경로 계산

**엔드포인트**: `POST /api/v1/navigation/calculate`

**설명**: ANP(Analytic Network Process) 다기준 최적화를 사용하여 상위 3개 최적 경로 계산

**요청 본문**:
```json
{
  "origin": "강남",
  "destination": "서울역",
  "disability_type": "PHY"
}
```

**요청 매개변수**:

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|------|------|------|--------|------|
| `origin` | string | 예 | - | 출발지 역명 (한글) |
| `destination` | string | 예 | - | 목적지 역명 (한글) |
| `disability_type` | string | 아니오 | "PHY" | 장애 유형: PHY/VIS/AUD/ELD |

**장애 유형**:
- **PHY**: 지체장애 (휠체어 사용자)
- **VIS**: 시각장애
- **AUD**: 청각장애
- **ELD**: 고령자

**응답** (`200 OK`):
```json
{
  "route_id": null,
  "origin": "강남",
  "destination": "서울역",
  "routes": [
    {
      "rank": 1,
      "route_sequence": ["2000000222", "2000000223", "1000000133"],
      "route_lines": ["2호선", "2호선", "1호선"],
      "total_time": 25.5,
      "transfers": 1,
      "transfer_stations": ["2000000223"],
      "transfer_info": [
        ["2000000223", "2호선", "1호선"]
      ],
      "score": 0.3542,
      "avg_convenience": 0.85,
      "avg_congestion": 0.57,
      "max_transfer_difficulty": 0.42
    },
    {
      "rank": 2,
      "route_sequence": [...],
      "total_time": 28.3,
      "transfers": 2,
      ...
    },
    {
      "rank": 3,
      "route_sequence": [...],
      "total_time": 30.1,
      "transfers": 1,
      ...
    }
  ],
  "total_routes_found": 15,
  "routes_returned": 3
}
```

**응답 필드**:

| 필드 | 타입 | 설명 |
|------|------|------|
| `route_id` | string\|null | REST API는 항상 null (WebSocket 세션에만 설정됨) |
| `origin` | string | 출발지 역명 |
| `destination` | string | 목적지 역명 |
| `routes` | array | 최대 3개의 경로 객체 배열 (ANP 점수로 순위 지정) |

**경로 객체 필드**:

| 필드 | 타입 | 단위 | 설명 |
|------|------|------|------|
| `rank` | integer | - | 경로 순위 (1-3, 1이 최선) |
| `route_sequence` | array[string] | - | 역 코드 순서 목록 |
| `route_lines` | array[string] | - | 노선명 순서 목록 |
| `total_time` | float | 분 | 총 이동 시간 |
| `transfers` | integer | - | 환승 횟수 |
| `transfer_stations` | array[string] | - | 환승역 코드 목록 |
| `transfer_info` | array[tuple] | - | 환승 상세: [station_cd, from_line, to_line] |
| `score` | float | - | ANP 가중 점수 (낮을수록 좋음) |
| `avg_convenience` | float | 0-1 | 평균 편의시설 점수 |
| `avg_congestion` | float | 0-1 | 평균 혼잡도 (0.57 = 57% 가득) |
| `max_transfer_difficulty` | float | 0-1 | 경로 내 최대 환승 난이도 |

**에러 응답**:

**400 Bad Request** (역을 찾을 수 없음):
```json
{
  "detail": {
    "message": "출발지 역을 찾을 수 없습니다: 존재하지않는역",
    "code": "STATION_NOT_FOUND"
  }
}
```

**400 Bad Request** (경로 없음):
```json
{
  "detail": {
    "message": "강남에서 서울역까지 경로를 찾을 수 없습니다",
    "code": "ROUTE_NOT_FOUND"
  }
}
```

**500 Internal Server Error**:
```json
{
  "detail": "경로 계산 중 오류 발생: ..."
}
```

**예제 cURL**:
```bash
curl -X POST "http://your-domain/api/v1/navigation/calculate" \
  -H "Content-Type: application/json" \
  -d '{
    "origin": "강남",
    "destination": "서울역",
    "disability_type": "PHY"
  }'
```

**예제 JavaScript (Fetch)**:
```javascript
const response = await fetch('http://your-domain/api/v1/navigation/calculate', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    origin: '강남',
    destination: '서울역',
    disability_type: 'PHY'
  })
});

const data = await response.json();
console.log(`${data.routes_returned}개의 경로 발견`);
console.log(`최적 경로: ${data.routes[0].total_time}분, ${data.routes[0].transfers}회 환승`);
```

---

### 4.2 역 검색 (자동완성)

**엔드포인트**: `GET /api/v1/stations/search`

**설명**: 자동완성 기능을 위한 키워드 기반 역 검색

**쿼리 매개변수**:

| 매개변수 | 타입 | 필수 | 기본값 | 범위 | 설명 |
|----------|------|------|--------|------|------|
| `q` | string | 예 | - | 1-50자 | 검색 키워드 |
| `limit` | integer | 아니오 | 10 | 1-50 | 최대 결과 수 |

**응답** (`200 OK`):
```json
{
  "keyword": "강남",
  "count": 3,
  "results": [
    {
      "station_cd": "2000000222",
      "name": "강남",
      "line": "2호선",
      "lat": 37.4979,
      "lng": 127.0276
    },
    {
      "station_cd": "3000000329",
      "name": "강남구청",
      "line": "3호선",
      "lat": 37.5172,
      "lng": 127.0473
    }
  ]
}
```

**예제 요청**:
```bash
GET /api/v1/stations/search?q=강남&limit=5
```

**예제 JavaScript**:
```javascript
const searchStations = async (keyword) => {
  const response = await fetch(
    `http://your-domain/api/v1/stations/search?q=${encodeURIComponent(keyword)}&limit=10`
  );
  const data = await response.json();
  return data.results;
};
```

---

### 4.3 역 유효성 검사

**엔드포인트**: `POST /api/v1/stations/validate`

**설명**: 역명이 시스템에 존재하는지 검증

**쿼리 매개변수**:

| 매개변수 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `station_name` | string | 예 | 검증할 역명 |

**응답** (`200 OK` - 유효함):
```json
{
  "valid": true,
  "station_cd": "2000000222",
  "station_name": "강남"
}
```

**응답** (`200 OK` - 유효하지 않음):
```json
{
  "valid": false,
  "message": "'존재하지않는역' 역을 찾을 수 없습니다"
}
```

---

### 4.4 전체 노선 조회

**엔드포인트**: `GET /api/v1/stations/lines`

**설명**: 모든 지하철 노선과 역 조회

**응답** (`200 OK`):
```json
{
  "lines": {
    "1호선": ["1000000100", "1000000101", ...],
    "2호선": ["2000000201", "2000000202", ...],
    "3호선": [...],
    ...
  },
  "total_lines": 23
}
```

---

## 5. WebSocket API (실시간 내비게이션)

### 5.1 WebSocket 연결

**엔드포인트**: `ws://your-domain/api/v1/ws/{user_id}`

**프로토콜**: WebSocket (ws:// 또는 wss://)

**연결 매개변수**:
- `user_id`: 사용자/세션 고유 식별자 (string)

**연결 제한**:
- 최대 동시 연결: 1000개
- 중복 연결: 이전 연결 자동 종료
- Keep-alive: 20초마다 Ping/Pong

**예제 연결 (JavaScript)**:
```javascript
const userId = 'user_12345'; // 고유 사용자 식별자
const ws = new WebSocket(`ws://your-domain/api/v1/ws/${userId}`);

ws.onopen = (event) => {
  console.log('WebSocket 연결됨');
};

ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  console.log('수신:', message.type, message);
  handleMessage(message);
};

ws.onerror = (error) => {
  console.error('WebSocket 에러:', error);
};

ws.onclose = (event) => {
  console.log('WebSocket 종료:', event.code, event.reason);
};
```

---

### 5.2 WebSocket 메시지 타입

#### 클라이언트 → 서버 메시지

##### 5.2.1 내비게이션 시작

**타입**: `start_navigation`

**목적**: 초기 경로 계산 및 내비게이션 세션 생성

**페이로드**:
```json
{
  "type": "start_navigation",
  "origin": "강남",
  "destination": "서울역",
  "disability_type": "PHY"
}
```

**서버 응답**: `route_calculated` (5.3.1 참조)

---

##### 5.2.2 위치 업데이트

**타입**: `location_update`

**목적**: 실시간 안내를 위한 현재 GPS 위치 전송

**페이로드**:
```json
{
  "type": "location_update",
  "latitude": 37.4979,
  "longitude": 127.0276,
  "accuracy": 50
}
```

**필드**:

| 필드 | 타입 | 필수 | 범위 | 단위 | 설명 |
|------|------|------|------|------|------|
| `latitude` | float | 예 | -90~90 | 도 | GPS 위도 |
| `longitude` | float | 예 | -180~180 | 도 | GPS 경도 |
| `accuracy` | float | 아니오 | - | 미터 | GPS 정확도 (기본값: 50) |

**서버 응답**: `navigation_update`, `route_deviation`, 또는 `arrival` (5.3.2-5.3.4 참조)

**예제**:
```javascript
// GPS 위치 가져오기
navigator.geolocation.getCurrentPosition((position) => {
  ws.send(JSON.stringify({
    type: 'location_update',
    latitude: position.coords.latitude,
    longitude: position.coords.longitude,
    accuracy: position.coords.accuracy
  }));
});
```

---

##### 5.2.3 경로 전환

**타입**: `switch_route`

**목적**: 계산된 상위 3개 경로 중 다른 경로로 전환

**페이로드**:
```json
{
  "type": "switch_route",
  "target_rank": 2
}
```

**필드**:
- `target_rank`: 정수 (1, 2, 또는 3) - 대상 경로 순위

**서버 응답**: `route_switched` (5.3.5 참조)

---

##### 5.2.4 경로 재계산

**타입**: `recalculate_route`

**목적**: 현재 위치에서 경로 재계산 (경로 이탈 후 사용)

**페이로드**:
```json
{
  "type": "recalculate_route",
  "latitude": 37.4979,
  "longitude": 127.0276,
  "disability_type": "PHY"
}
```

**서버 응답**: `route_recalculated` (5.3.6 참조)

---

##### 5.2.5 내비게이션 종료

**타입**: `end_navigation`

**목적**: 내비게이션 세션 종료 및 정리

**페이로드**:
```json
{
  "type": "end_navigation"
}
```

**서버 응답**: `navigation_ended` (5.3.7 참조)

---

##### 5.2.6 Ping

**타입**: `ping`

**목적**: 연결 유지

**페이로드**:
```json
{
  "type": "ping"
}
```

**서버 응답**: `pong`

---

#### 서버 → 클라이언트 메시지

##### 5.3.1 경로 계산됨

**타입**: `route_calculated`

**전송 시점**: `start_navigation` 메시지 후

**페이로드**:
```json
{
  "type": "route_calculated",
  "route_id": "550e8400-e29b-41d4-a716-446655440000",
  "origin": "강남",
  "origin_cd": "2000000222",
  "destination": "서울역",
  "destination_cd": "1000000133",
  "routes": [
    {
      "rank": 1,
      "route_sequence": ["2000000222", "2000000223", "1000000133"],
      "route_lines": ["2호선", "2호선", "1호선"],
      "total_time": 25.5,
      "transfers": 1,
      "transfer_stations": ["2000000223"],
      "transfer_info": [["2000000223", "2호선", "1호선"]],
      "score": 0.3542,
      "avg_convenience": 0.85,
      "avg_congestion": 0.57,
      "max_transfer_difficulty": 0.42
    },
    {...},
    {...}
  ],
  "total_routes_found": 15,
  "routes_returned": 3,
  "selected_route_rank": 1
}
```

**세션 데이터** (Redis에 4시간 저장):
- Route ID
- 계산된 3개 경로 전체
- 현재 선택된 경로 (기본값: rank 1)
- 출발지/목적지 정보

---

##### 5.3.2 내비게이션 업데이트

**타입**: `navigation_update`

**전송 시점**: `location_update` 메시지 후 (정상 내비게이션)

**페이로드**:
```json
{
  "type": "navigation_update",
  "current_station": "2000000222",
  "current_station_name": "강남",
  "next_station": "2000000223",
  "next_station_name": "역삼",
  "distance_to_next": 845.32,
  "remaining_stations": 5,
  "is_transfer": false,
  "transfer_from_line": null,
  "transfer_to_line": null,
  "message": "역삼 방향으로 이동 중 (약 845m)",
  "progress_percent": 45
}
```

**필드**:

| 필드 | 타입 | 단위 | 설명 |
|------|------|------|------|
| `current_station` | string | - | 현재 역 코드 |
| `current_station_name` | string | - | 현재 역명 |
| `next_station` | string\|null | - | 다음 역 코드 |
| `next_station_name` | string\|null | - | 다음 역명 |
| `distance_to_next` | float | 미터 | 다음 역까지 거리 |
| `remaining_stations` | integer | - | 남은 역 수 |
| `is_transfer` | boolean | - | 다음 역이 환승역인지 여부 |
| `transfer_from_line` | string\|null | - | 환승 출발 노선 |
| `transfer_to_line` | string\|null | - | 환승 도착 노선 |
| `message` | string | - | 사용자 안내 메시지 |
| `progress_percent` | integer | % | 진행률 (0-100) |

**환승 예제**:
```json
{
  "type": "navigation_update",
  "current_station": "2000000222",
  "current_station_name": "강남",
  "next_station": "2000000223",
  "next_station_name": "역삼",
  "distance_to_next": 120.5,
  "remaining_stations": 3,
  "is_transfer": true,
  "transfer_from_line": "2호선",
  "transfer_to_line": "1호선",
  "message": "역삼에서 2호선 → 1호선 환승하세요",
  "progress_percent": 67
}
```

---

##### 5.3.3 경로 이탈

**타입**: `route_deviation`

**전송 시점**: 사용자 위치가 계획된 경로에 없을 때

**페이로드**:
```json
{
  "type": "route_deviation",
  "message": "경로를 이탈했습니다. 경로를 다시 계산합니다.",
  "current_location": "3000000315",
  "nearest_station": "압구정",
  "suggested_action": "재계산을 권장합니다"
}
```

**권장 조치**: 자동으로 `recalculate_route` 메시지 전송 또는 사용자에게 프롬프트

---

##### 5.3.4 도착

**타입**: `arrival`

**전송 시점**: 사용자가 목적지에 도착했을 때

**페이로드**:
```json
{
  "type": "arrival",
  "message": "목적지에 도착했습니다!",
  "destination": "서울역",
  "destination_cd": "1000000133"
}
```

---

##### 5.3.5 경로 전환됨

**타입**: `route_switched`

**전송 시점**: `switch_route` 메시지 후

**페이로드**:
```json
{
  "type": "route_switched",
  "selected_route_rank": 2,
  "route_sequence": ["2000000222", "..."],
  "route_lines": ["2호선", "..."],
  "total_time": 28.3,
  "transfers": 2,
  "transfer_stations": ["...", "..."],
  "message": "2순위 경로로 변경되었습니다"
}
```

---

##### 5.3.6 경로 재계산됨

**타입**: `route_recalculated`

**전송 시점**: `recalculate_route` 메시지 후

**페이로드**: `route_calculated`와 동일한 구조

```json
{
  "type": "route_recalculated",
  "route_id": "new-uuid",
  "origin": "압구정",
  "destination": "서울역",
  "routes": [...],
  "message": "경로가 재계산되었습니다"
}
```

---

##### 5.3.7 내비게이션 종료됨

**타입**: `navigation_ended`

**전송 시점**: `end_navigation` 메시지 후

**페이로드**:
```json
{
  "type": "navigation_ended",
  "message": "내비게이션을 종료했습니다",
  "route_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

---

##### 5.3.8 연결됨

**타입**: `connected`

**전송 시점**: WebSocket 연결 즉시

**페이로드**:
```json
{
  "type": "connected",
  "user_id": "user_12345",
  "message": "서버 연결 성공",
  "server_version": "4.0.0"
}
```

---

##### 5.3.9 에러

**타입**: `error`

**전송 시점**: 에러 발생 시

**페이로드**:
```json
{
  "type": "error",
  "message": "출발지와 목적지가 필요합니다",
  "code": "MISSING_PARAMETERS",
  "timestamp": "unique-id"
}
```

**에러 코드**:

| 코드 | 설명 |
|------|------|
| `MISSING_PARAMETERS` | 필수 매개변수 누락 |
| `MISSING_LOCATION` | GPS 좌표 필요 |
| `NO_ACTIVE_SESSION` | 활성 내비게이션 세션 없음 |
| `STATION_NOT_FOUND` | 역명을 찾을 수 없음 |
| `ROUTE_NOT_FOUND` | 사용 가능한 경로 없음 |
| `INVALID_ROUTE_RANK` | 경로 순위는 1-3이어야 함 |
| `ROUTE_SWITCH_FAILED` | 경로 전환 실패 |
| `NAVIGATION_ERROR` | 일반 내비게이션 에러 |
| `RECALCULATION_ERROR` | 경로 재계산 실패 |
| `UNKNOWN_MESSAGE_TYPE` | 유효하지 않은 메시지 타입 |
| `INTERNAL_SERVER_ERROR` | 서버 에러 |
| `DUPLICATE_CONNECTION` | 다른 기기에서 연결됨 |

---

##### 5.3.10 연결 해제됨

**타입**: `disconnected`

**전송 시점**: 서버에 의해 연결 종료될 때

**페이로드**:
```json
{
  "type": "disconnected",
  "reason": "다른 기기에서 연결됨",
  "code": "DUPLICATE_CONNECTION"
}
```

---

### 5.4 완전한 WebSocket 예제

```javascript
class NavigationClient {
  constructor(userId) {
    this.userId = userId;
    this.ws = null;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 5;
  }

  connect() {
    this.ws = new WebSocket(`ws://your-domain/api/v1/ws/${this.userId}`);
    
    this.ws.onopen = () => {
      console.log('내비게이션 서비스에 연결됨');
      this.reconnectAttempts = 0;
      this.startPingInterval();
    };

    this.ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      this.handleMessage(message);
    };

    this.ws.onerror = (error) => {
      console.error('WebSocket 에러:', error);
    };

    this.ws.onclose = (event) => {
      console.log('WebSocket 종료:', event.code, event.reason);
      this.stopPingInterval();
      this.attemptReconnect();
    };
  }

  startPingInterval() {
    this.pingInterval = setInterval(() => {
      this.send({ type: 'ping' });
    }, 15000); // 15초마다
  }

  stopPingInterval() {
    if (this.pingInterval) {
      clearInterval(this.pingInterval);
    }
  }

  send(message) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
    } else {
      console.error('WebSocket이 연결되지 않음');
    }
  }

  startNavigation(origin, destination, disabilityType = 'PHY') {
    this.send({
      type: 'start_navigation',
      origin,
      destination,
      disability_type: disabilityType
    });
  }

  updateLocation(latitude, longitude, accuracy = 50) {
    this.send({
      type: 'location_update',
      latitude,
      longitude,
      accuracy
    });
  }

  switchRoute(targetRank) {
    this.send({
      type: 'switch_route',
      target_rank: targetRank
    });
  }

  recalculateRoute(latitude, longitude, disabilityType = 'PHY') {
    this.send({
      type: 'recalculate_route',
      latitude,
      longitude,
      disability_type: disabilityType
    });
  }

  endNavigation() {
    this.send({ type: 'end_navigation' });
  }

  handleMessage(message) {
    switch (message.type) {
      case 'connected':
        console.log('서버 버전:', message.server_version);
        break;

      case 'route_calculated':
        console.log(`경로 계산됨: ${message.routes_returned}개 경로`);
        console.log('최적 경로:', message.routes[0]);
        // UI에 경로 옵션 표시
        break;

      case 'navigation_update':
        console.log(`현재: ${message.current_station_name}`);
        console.log(`다음: ${message.next_station_name} (${message.distance_to_next}m)`);
        console.log(`진행률: ${message.progress_percent}%`);
        
        if (message.is_transfer) {
          console.log(`환승: ${message.transfer_from_line} → ${message.transfer_to_line}`);
        }
        // UI에 안내 정보 업데이트
        break;

      case 'route_deviation':
        console.warn('경로 이탈 감지!');
        // 사용자에게 프롬프트 또는 자동 재계산
        if (confirm('경로를 이탈했습니다. 재계산하시겠습니까?')) {
          navigator.geolocation.getCurrentPosition((pos) => {
            this.recalculateRoute(pos.coords.latitude, pos.coords.longitude);
          });
        }
        break;

      case 'arrival':
        console.log('목적지 도착!');
        // 도착 알림 표시
        break;

      case 'route_switched':
        console.log(`경로 ${message.selected_route_rank}번으로 전환됨`);
        break;

      case 'error':
        console.error(`에러 [${message.code}]:`, message.message);
        // UI에서 에러 처리
        break;

      case 'pong':
        // 하트비트 응답
        break;

      default:
        console.log('알 수 없는 메시지 타입:', message.type);
    }
  }

  attemptReconnect() {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++;
      const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
      console.log(`${delay}ms 후 재연결 시도 (${this.reconnectAttempts}회)`);
      setTimeout(() => this.connect(), delay);
    } else {
      console.error('최대 재연결 시도 횟수 도달');
    }
  }

  disconnect() {
    this.stopPingInterval();
    if (this.ws) {
      this.ws.close();
    }
  }
}

// 사용법
const client = new NavigationClient('user_12345');
client.connect();

// 내비게이션 시작
client.startNavigation('강남', '서울역', 'PHY');

// 위치 추적 (예: 5초마다)
setInterval(() => {
  navigator.geolocation.getCurrentPosition((position) => {
    client.updateLocation(
      position.coords.latitude,
      position.coords.longitude,
      position.coords.accuracy
    );
  });
}, 5000);
```

---

## 6. 데이터 모델

### 6.1 Station (역)

```typescript
interface Station {
  station_cd: string;      // 역 코드 (예: "2000000222")
  name: string;            // 역명 (한글)
  line: string;            // 노선명 (예: "2호선")
  lat: number;             // 위도
  lng: number;             // 경도
  station_id?: string;     // 선택적 외부 ID
}
```

### 6.2 Route (경로)

```typescript
interface Route {
  rank: number;                        // 경로 순위 (1-3)
  route_sequence: string[];            // 역 코드 순서
  route_lines: string[];               // 노선명 순서
  total_time: number;                  // 총 소요 시간(분)
  transfers: number;                   // 환승 횟수
  transfer_stations: string[];         // 환승역 코드
  transfer_info: [string, string, string][]; // [station_cd, from_line, to_line]
  score: number;                       // ANP 점수 (낮을수록 좋음)
  avg_convenience: number;             // 평균 편의성 (0-1)
  avg_congestion: number;              // 평균 혼잡도 (0-1)
  max_transfer_difficulty: number;     // 최대 환승 난이도 (0-1)
}
```

### 6.3 완전한 TypeScript 정의

```typescript
// 요청 타입
interface NavigationStartRequest {
  origin: string;
  destination: string;
  disability_type?: 'PHY' | 'VIS' | 'AUD' | 'ELD';
}

interface LocationUpdateRequest {
  latitude: number;      // -90 ~ 90
  longitude: number;     // -180 ~ 180
  accuracy?: number;     // 미터
  timestamp?: string;
}

interface RecalculateRouteRequest {
  latitude: number;
  longitude: number;
  disability_type?: string;
}

// 응답 타입
interface RouteCalculatedResponse {
  route_id: string | null;
  origin: string;
  destination: string;
  routes: Route[];
  total_routes_found: number;
  routes_returned: number;
}

interface NavigationUpdateResponse {
  current_station: string;
  current_station_name: string;
  next_station: string | null;
  next_station_name: string | null;
  distance_to_next: number | null;
  remaining_stations: number;
  is_transfer: boolean;
  transfer_from_line: string | null;
  transfer_to_line: string | null;
  message: string;
  progress_percent: number;
}

interface StationSearchResponse {
  keyword: string;
  count: number;
  results: Station[];
}

interface StationValidateResponse {
  valid: boolean;
  station_cd?: string;
  station_name?: string;
  message?: string;
}

interface ErrorResponse {
  error: string;
  code?: string;
}
```

---

## 7. 에러 처리

### 7.1 HTTP 상태 코드

| 상태 코드 | 설명 | 사용 |
|-----------|------|------|
| `200` | OK | 성공적인 요청 |
| `400` | Bad Request | 잘못된 매개변수, 역을 찾을 수 없음 |
| `404` | Not Found | 엔드포인트를 찾을 수 없음 |
| `500` | Internal Server Error | 서버 에러 |
| `503` | Service Unavailable | 헬스 체크 실패 |

### 7.2 커스텀 에러 코드

| 코드 | HTTP 상태 | 설명 |
|------|-----------|------|
| `STATION_NOT_FOUND` | 400 | 데이터베이스에서 역명을 찾을 수 없음 |
| `ROUTE_NOT_FOUND` | 400 | 역 간 사용 가능한 경로 없음 |
| `SESSION_NOT_FOUND` | 400 | 활성 내비게이션 세션 없음 |
| `INVALID_LOCATION` | 400 | GPS 좌표가 유효하지 않거나 범위를 벗어남 |
| `INTERNAL_ERROR` | 500 | 일반 내부 에러 |

### 7.3 에러 처리 예제

```javascript
async function calculateRoute(origin, destination, disabilityType) {
  try {
    const response = await fetch('/api/v1/navigation/calculate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ origin, destination, disability_type: disabilityType })
    });

    if (!response.ok) {
      const error = await response.json();
      
      // 특정 에러 코드 처리
      if (error.detail?.code === 'STATION_NOT_FOUND') {
        alert(`역을 찾을 수 없습니다: ${error.detail.message}`);
      } else if (error.detail?.code === 'ROUTE_NOT_FOUND') {
        alert('경로를 찾을 수 없습니다. 다른 역을 선택해주세요.');
      } else {
        alert('오류가 발생했습니다: ' + error.detail);
      }
      return null;
    }

    return await response.json();
    
  } catch (error) {
    console.error('네트워크 에러:', error);
    alert('서버와 통신할 수 없습니다.');
    return null;
  }
}
```

---

## 8. 성능 및 제한사항

### 8.1 API 제한

| 리소스 | 제한 | 비고 |
|--------|------|------|
| WebSocket 연결 | 1000개 동시 | 서버 인스턴스당 |
| 경로 계산 시간 | < 1초 | 일반적인 응답 시간 |
| 세션 TTL | 4시간 | Redis 세션 만료 |
| 반환되는 최대 경로 수 | 3개 | 상위 3개 순위 경로 |
| 최대 검색 결과 | 50개 | 역 검색 제한 |
| WebSocket 타임아웃 | 300초 | 읽기/쓰기 타임아웃 |

### 8.2 최적화 팁

1. **WebSocket**: 사용자당 단일 연결 사용, 여러 내비게이션에 재사용
2. **위치 업데이트**: 3-5초마다 전송, 더 자주 전송하지 말 것
3. **역 검색**: 검색 입력 디바운싱 (300-500ms)
4. **경로 캐싱**: 클라이언트 측에서 경로 계산 캐싱
5. **연결**: 재연결에 지수 백오프 구현

---

## 9. 시스템 설정

### 9.1 환경 변수

```bash
# 서버
DEBUG=false
PORT=8001
SECRET_KEY=your-secret-key-here

# 데이터베이스
DB_HOST=your-rds-endpoint
DB_PORT=5432
DB_NAME=kindmap_db
DB_USER=postgres
DB_PASSWORD=your-password

# Redis
REDIS_HOST=your-redis-host
REDIS_PORT=6379

# Celery (선택 사항 - 비동기 로깅용)
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2
```

### 9.2 Nginx 설정

```nginx
# nginx/conf.d/kindmap_api.conf
upstream fastapi_backend {
    server fastapi:8001;
}

server {
    listen 80;
    
    # API 엔드포인트
    location /api/ {
        proxy_pass http://fastapi_backend;
        
        # WebSocket 지원
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # 헤더
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        
        # 타임아웃
        proxy_connect_timeout 60s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
    }
    
    # 헬스 체크
    location = /health {
        proxy_pass http://fastapi_backend/health;
    }
    
    # API 문서
    location ~ ^/(docs|redoc|openapi\.json) {
        proxy_pass http://fastapi_backend;
    }
}
```

---

## 10. 테스트 엔드포인트

### 10.1 헬스 체크

```bash
curl http://your-domain/health
```

**응답**:
```json
{
  "status": "healthy",
  "version": "4.0.0",
  "timestamp": "1700000000.0",
  "components": {
    "database": "healthy",
    "redis": "healthy"
  }
}
```

### 10.2 API 정보

```bash
curl http://your-domain/api/v1/info
```

**응답**:
```json
{
  "api_version": "v1",
  "service": "KindMap Backend",
  "version": "4.0.0",
  "endpoints": {
    "websocket": {
      "url": "ws://localhost:8001/api/v1/ws/{user_id}",
      "description": "실시간 경로 안내 WebSocket"
    },
    "rest": {
      "calculate_route": "POST /api/v1/navigation/calculate",
      "search_stations": "GET /api/v1/stations/search",
      "validate_station": "POST /api/v1/stations/validate",
      "get_lines": "GET /api/v1/stations/lines"
    }
  },
  "documentation": {
    "swagger": "/docs",
    "redoc": "/redoc"
  },
  "supported_disability_types": {
    "PHY": "지체장애 (휠체어 사용자)",
    "VIS": "시각장애",
    "AUD": "청각장애",
    "ELD": "고령자"
  }
}
```

---

## 11. 프론트엔드 개발 시 중요 사항

### 11.1 현재 수정 사항 (jwt-login-implement 브랜치)

다음 변경으로 `route_id`를 적절히 처리합니다:

1. **navigation.py**: REST API 응답에서 `route_id` 제거 (WebSocket 전용)
2. **domain.py**: `RouteInfo.route_id`를 `Optional[str]`로 변경
3. **responses.py**: `RouteCalculatedResponse.route_id`를 선택 사항으로 변경

**영향**: 
- REST API 호출은 `route_id: null` 반환
- WebSocket 세션은 실제 route ID 생성 및 반환
- route ID가 있는 세션 기반 내비게이션은 WebSocket 사용

### 11.2 인증 상태

**⚠️ 중요**: `jwt-login-implement` 브랜치임에도 불구하고:
- **JWT 인증이 현재 활성화되어 있지 않음**
- **권한 헤더 불필요**
- **사용자 인증 엔드포인트 없음**
- 라이브러리는 설치되었지만 통합되지 않음

**권장사항**: 향후 JWT 통합 계획:
```javascript
// 향후 구현
const headers = {
  'Content-Type': 'application/json',
  'Authorization': `Bearer ${jwtToken}`  // 현재 사용되지 않음
};
```

### 11.3 GPS 위치 검증

시스템은 서울 수도권 지역의 GPS 좌표를 검증합니다:
- **위도**: 36.0 ~ 39.0
- **경도**: 126.4 ~ 127.6

이 범위를 벗어난 위치는 `INVALID_LOCATION` 에러로 거부됩니다.

### 11.4 장애 유형 최적화

ANP(Analytic Network Process)를 사용하여 장애 유형별로 경로를 다르게 최적화합니다:

- **PHY (지체/휠체어)**: 환승 및 환승 난이도 최소화
- **VIS (시각)**: 편의시설 및 안전성 우선
- **AUD (청각)**: 시각 정보 시스템 강조
- **ELD (고령자)**: 혼잡도 및 보행 거리 감소

### 11.5 세션 관리

**WebSocket 세션**:
- Redis에 4시간 TTL로 저장
- 쉬운 전환을 위해 계산된 3개 경로 모두 포함
- 연결 해제 또는 만료 시 자동 정리
- user_id당 하나의 세션 (중복 연결 시 이전 연결 대체)

**REST API**:
- 상태 비저장, 세션 저장소 없음
- 각 요청은 독립적
- 내비게이션 없는 간단한 경로 계산용

---

## 12. 마이그레이션 경로 및 로드맵

### 12.1 현재에서 향후로 (예상)

| 기능 | 현재 상태 | 예상 향후 |
|------|----------|-----------|
| 인증 | 없음 | JWT Bearer 토큰 |
| CORS | 모든 origin 허용 | 특정 도메인으로 제한 |
| 사용자 관리 | 사용자 없음 | 사용자 등록/로그인 |
| Rate Limiting | 없음 | 사용자당 rate limit |
| API 버전 관리 | v1만 | v2 지원, 사용 중단 알림 |

### 12.2 주의해야 할 주요 변경사항

JWT 구현 시 예상되는 사항:
1. **401 Unauthorized** 유효한 토큰 없이 요청 시 응답
2. **새 엔드포인트**: `/api/v1/auth/login`, `/api/v1/auth/register`, `/api/v1/auth/refresh`
3. **필수 헤더**: `Authorization: Bearer <token>`
4. **사용자별 경로**: 사용자 계정에 저장된 경로

---

## 부록 A: 완전한 코드 예제

### A.1 React 통합 예제

```jsx
import React, { useState, useEffect, useCallback } from 'react';

const NavigationApp = () => {
  const [ws, setWs] = useState(null);
  const [connected, setConnected] = useState(false);
  const [routes, setRoutes] = useState([]);
  const [currentGuidance, setCurrentGuidance] = useState(null);
  const [origin, setOrigin] = useState('');
  const [destination, setDestination] = useState('');

  // WebSocket 연결
  useEffect(() => {
    const userId = `user_${Date.now()}`;
    const websocket = new WebSocket(`ws://your-domain/api/v1/ws/${userId}`);

    websocket.onopen = () => {
      console.log('연결됨');
      setConnected(true);
    };

    websocket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      handleWebSocketMessage(message);
    };

    websocket.onclose = () => {
      console.log('연결 해제됨');
      setConnected(false);
    };

    setWs(websocket);

    return () => websocket.close();
  }, []);

  const handleWebSocketMessage = useCallback((message) => {
    switch (message.type) {
      case 'route_calculated':
        setRoutes(message.routes);
        break;
      case 'navigation_update':
        setCurrentGuidance(message);
        break;
      case 'route_deviation':
        alert('경로 이탈! 재계산 중...');
        break;
      case 'arrival':
        alert('목적지 도착!');
        break;
      default:
        console.log('메시지:', message);
    }
  }, []);

  const startNavigation = () => {
    if (ws && connected) {
      ws.send(JSON.stringify({
        type: 'start_navigation',
        origin,
        destination,
        disability_type: 'PHY'
      }));
    }
  };

  const updateLocation = useCallback(() => {
    if (navigator.geolocation && ws && connected) {
      navigator.geolocation.getCurrentPosition((position) => {
        ws.send(JSON.stringify({
          type: 'location_update',
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
          accuracy: position.coords.accuracy
        }));
      });
    }
  }, [ws, connected]);

  // 5초마다 위치 자동 업데이트
  useEffect(() => {
    if (routes.length > 0) {
      const interval = setInterval(updateLocation, 5000);
      return () => clearInterval(interval);
    }
  }, [routes, updateLocation]);

  return (
    <div>
      <h1>KindMap 내비게이션</h1>
      
      <div>
        <input 
          value={origin} 
          onChange={(e) => setOrigin(e.target.value)}
          placeholder="출발지"
        />
        <input 
          value={destination} 
          onChange={(e) => setDestination(e.target.value)}
          placeholder="목적지"
        />
        <button onClick={startNavigation} disabled={!connected}>
          경로 검색
        </button>
      </div>

      {routes.length > 0 && (
        <div>
          <h2>경로 옵션</h2>
          {routes.map((route, idx) => (
            <div key={idx}>
              <h3>경로 {route.rank}</h3>
              <p>소요시간: {route.total_time}분</p>
              <p>환승: {route.transfers}회</p>
            </div>
          ))}
        </div>
      )}

      {currentGuidance && (
        <div>
          <h2>현재 안내</h2>
          <p>현재 역: {currentGuidance.current_station_name}</p>
          <p>다음 역: {currentGuidance.next_station_name}</p>
          <p>거리: {currentGuidance.distance_to_next}m</p>
          <p>진행률: {currentGuidance.progress_percent}%</p>
          <p>{currentGuidance.message}</p>
        </div>
      )}
    </div>
  );
};

export default NavigationApp;
```

---

## 요약

이 포괄적인 분석은 프론트엔드 개발자가 KindMap 대중교통 경로 안내 API와 통합하는 데 필요한 모든 정보를 제공합니다. 시스템은 현재 브랜치명과 무관하게 인증이 없으며, REST 및 WebSocket 프로토콜을 모두 사용하고, 접근성 요구를 위한 정교한 다기준 경로 최적화를 제공합니다.