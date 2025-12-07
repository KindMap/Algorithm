# JWT Authentication API - Frontend Integration Guide

## 개요 (Overview)

이 문서는 KindMap 프로젝트의 JWT 기반 인증 API를 프론트엔드와 연동하기 위한 가이드입니다.

This document provides a guide for integrating the KindMap project's JWT-based authentication API with the frontend.

**Base URL:** `/api/v1/auth`

---

## 주요 엔드포인트 (API Endpoints)

### 1. 회원가입 (User Registration)

**Endpoint:** `POST /api/v1/auth/register`

**Request Body (JSON):**
```json
{
  "email": "user@example.com",           // 필수, 이메일 형식
  "password": "password123",              // 필수, 최소 8자
  "username": "myusername",               // 선택
  "disability_type": "PHY"                // 선택: PHY, VIS, AUD, ELD, NONE
}
```

**장애 유형 (Disability Types):**
- `PHY`: 지체장애 (휠체어 사용자)
- `VIS`: 시각장애
- `AUD`: 청각장애
- `ELD`: 고령자
- `NONE`: 해당 없음

**성공 응답 (201 Created):**
```json
{
  "user_id": "12345678-1234-5678-1234-567812345678",
  "email": "user@example.com",
  "username": "myusername",
  "disability_type": "PHY",
  "created_at": "2024-01-01T12:00:00"
}
```

**에러 응답:**
- **400 Bad Request:** 이미 등록된 이메일
  ```json
  {
    "detail": "이미 사용 중인 이메일입니다."
  }
  ```
- **422 Validation Error:** 잘못된 이메일 형식, 비밀번호 길이 부족, 잘못된 장애 유형

---

### 2. 로그인 (Login)

**Endpoint:** `POST /api/v1/auth/login`

**⚠️ 중요:** 요청 형식은 `application/x-www-form-urlencoded` (OAuth2 표준)

**Request Body (Form Data):**
```
username=user@example.com&password=password123
```

**참고사항:**
- 필드 이름이 `username`이지만, **이메일 주소**를 입력해야 함
- JSON이 아닌 form-urlencoded 형식 사용

**JavaScript 예제:**
```javascript
const formData = new URLSearchParams();
formData.append('username', 'user@example.com');  // 이메일을 username 필드에
formData.append('password', 'password123');

const response = await fetch('/api/v1/auth/login', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/x-www-form-urlencoded',
  },
  body: formData
});
```

**성공 응답 (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**에러 응답:**
- **401 Unauthorized:** 잘못된 이메일 또는 비밀번호
  ```json
  {
    "detail": "이메일 혹은 비밀번호를 잘못 입력하셨습니다."
  }
  ```
- **400 Bad Request:** 비활성화된 사용자
  ```json
  {
    "detail": "만료된 사용자입니다."
  }
  ```

**동작 방식:**
- 로그인 성공 시 `last_login` 시간 업데이트
- Refresh token이 데이터베이스에 저장됨
- 새로운 로그인 시 이전 refresh token은 무효화됨 (단일 기기 로그인 정책)

---

### 3. 토큰 갱신 (Token Refresh)

**Endpoint:** `POST /api/v1/auth/refresh`

**Request Body (JSON):**
```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**성공 응답 (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",    // 새로운 access token
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."   // 새로운 refresh token
}
```

**에러 응답:**
- **401 Unauthorized:** 유효하지 않거나 만료된 refresh token
  ```json
  {
    "detail": "Invalid refresh token"
  }
  ```

**동작 방식:**
- 토큰 서명 및 만료 시간 검증
- 토큰 타입이 "refresh"인지 확인 (access token 오용 방지)
- 데이터베이스 화이트리스트에서 토큰 존재 여부 확인
- 새로운 토큰 쌍 발급 및 기존 refresh token 교체
- 기존 refresh token은 자동으로 무효화됨

**권장 사용 패턴:**
```javascript
// Access token 만료 전에 자동 갱신
setInterval(async () => {
  const refreshToken = getStoredRefreshToken();
  const response = await fetch('/api/v1/auth/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken })
  });
  
  if (response.ok) {
    const { access_token, refresh_token } = await response.json();
    saveTokens(access_token, refresh_token);
  }
}, 25 * 60 * 1000);  // 25분마다 (access token 만료 30분 전)
```

---

### 4. 로그아웃 (Logout)

**Endpoint:** `POST /api/v1/auth/logout`

**Headers:**
```
Authorization: Bearer <access_token>
```

**성공 응답 (200 OK):**
```json
{
  "message": "Successfully logged out"
}
```

**에러 응답:**
- **401 Unauthorized:** 인증되지 않았거나 유효하지 않은 토큰
  ```json
  {
    "detail": "Not authenticated"
  }
  ```

**동작 방식:**
- 유효한 access token 필요
- 사용자의 모든 refresh token을 데이터베이스에서 삭제
- Access token은 만료 시간까지 유효함 (stateless JWT)
- 클라이언트는 저장된 토큰을 삭제해야 함

---

### 5. 현재 사용자 정보 조회 (Get Current User Info)

**Endpoint:** `GET /api/v1/auth/me`

**Headers:**
```
Authorization: Bearer <access_token>
```

**성공 응답 (200 OK):**
```json
{
  "user_id": "12345678-1234-5678-1234-567812345678",
  "email": "user@example.com",
  "username": "myusername",
  "disability_type": "PHY",
  "created_at": "2024-01-01T12:00:00"
}
```

**에러 응답:**
- **401 Unauthorized:** 인증되지 않음
- **400 Bad Request:** 비활성화된 사용자

---

## 토큰 사용 방법 (Token Usage)

### Authorization Header 설정

보호된 엔드포인트 요청 시 access token을 포함:

```javascript
const response = await fetch('/api/v1/auth/me', {
  method: 'GET',
  headers: {
    'Authorization': `Bearer ${accessToken}`
  }
});
```

### 토큰 형식 (Token Format)

JWT 토큰 페이로드:
```json
{
  "sub": "12345678-1234-5678-1234-567812345678",  // 사용자 ID (UUID)
  "exp": 1234567890,                               // 만료 시간 (Unix timestamp)
  "type": "access" 또는 "refresh"                  // 토큰 타입
}
```

### 토큰 만료 시간 (Token Expiration)

- **Access Token:** 30분
- **Refresh Token:** 7일

### 인증 모드 (Authentication Modes)

백엔드는 두 가지 인증 모드를 지원합니다:

1. **선택적 인증 (Optional Authentication):**
   - 토큰이 있으면 사용자 정보 반환
   - 토큰이 없거나 유효하지 않으면 `null` 반환
   - 에러를 발생시키지 않음
   - 로그인 여부에 따라 다르게 동작하는 엔드포인트에 사용

2. **필수 인증 (Required Authentication):**
   - 유효한 access token 필요
   - 인증되지 않으면 401 에러
   - 비활성 사용자는 400 에러
   - 보호된 엔드포인트에 사용

---

## 완전한 인증 플로우 (Complete Authentication Flows)

### 회원가입 및 로그인 플로우

```
1. 회원가입: POST /api/v1/auth/register
   → 사용자 객체 반환 (토큰 없음)

2. 로그인: POST /api/v1/auth/login
   → access_token + refresh_token 반환
   → 토큰을 안전하게 저장

3. 사용자 정보 조회: GET /api/v1/auth/me
   → Authorization 헤더 포함
   → 사용자 프로필 반환
```

### 토큰 갱신 플로우

```
1. Access token 만료 (30분 후)

2. 토큰 갱신: POST /api/v1/auth/refresh
   → 요청 본문에 refresh_token 포함
   → 새로운 access_token + refresh_token 반환
   → 기존 토큰을 새 토큰으로 교체

3. 새로운 access_token으로 계속 사용
```

### 로그아웃 플로우

```
1. 로그아웃: POST /api/v1/auth/logout
   → Authorization 헤더 포함
   → 모든 refresh token이 데이터베이스에서 삭제됨
   → Access token은 만료까지 유효함
   → 클라이언트는 저장된 토큰 삭제
```

---

## 에러 처리 (Error Handling)

### HTTP 상태 코드

| 코드 | 의미 | 주요 원인 |
|------|------|-----------|
| 200 | 성공 | 로그인, 토큰 갱신, 로그아웃, 데이터 조회 성공 |
| 201 | 생성됨 | 회원가입 성공 |
| 400 | 잘못된 요청 | 비활성 사용자, 중복 이메일 |
| 401 | 인증 실패 | 잘못된 자격 증명, 만료된 토큰, 토큰 없음 |
| 422 | 유효성 검증 실패 | 잘못된 이메일 형식, 필수 필드 누락, 비밀번호 길이 부족 |
| 500 | 서버 에러 | 데이터베이스 오류, 예상치 못한 예외 |

### 에러 응답 형식

```json
{
  "detail": "한국어 또는 영어 에러 메시지"
}
```

일부 에러는 추가 헤더 포함:
```json
{
  "detail": "Not authenticated",
  "headers": {
    "WWW-Authenticate": "Bearer"
  }
}
```

### 전역 에러 처리 권장 사항

```javascript
// 401 에러 발생 시 자동으로 토큰 갱신 시도
async function fetchWithAuth(url, options = {}) {
  const accessToken = getStoredAccessToken();
  
  const response = await fetch(url, {
    ...options,
    headers: {
      ...options.headers,
      'Authorization': `Bearer ${accessToken}`
    }
  });
  
  if (response.status === 401) {
    // 토큰 갱신 시도
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      // 원래 요청 재시도
      return fetch(url, {
        ...options,
        headers: {
          ...options.headers,
          'Authorization': `Bearer ${getStoredAccessToken()}`
        }
      });
    } else {
      // 로그인 페이지로 리다이렉트
      redirectToLogin();
    }
  }
  
  return response;
}
```

---

## 보안 고려사항 (Security Considerations)

### 토큰 저장

**권장 사항:**
- **httpOnly 쿠키** 사용 (XSS 공격 방지)
- localStorage 사용 시 XSS 취약점 주의
- sessionStorage는 탭 닫으면 삭제됨

**예제 (쿠키 사용):**
```javascript
// 서버에서 Set-Cookie 헤더로 설정하는 것이 가장 안전
// 프론트엔드에서 직접 접근 불가능한 httpOnly 쿠키로 설정
```

### CORS 설정

현재 개발 환경에서는 모든 origin 허용:
- `allow_origins=["*"]`
- Credentials 허용
- 모든 메서드 허용
- 모든 헤더 허용

**⚠️ 프로덕션 배포 시 특정 도메인만 허용하도록 변경 필요**

### 보안 기능

1. **비밀번호 보안:**
   - bcrypt를 사용한 해싱
   - 자동 salt 생성
   - 평문 비밀번호 저장 안 함

2. **토큰 보안:**
   - 토큰 타입 구분 (access/refresh)
   - Refresh token 화이트리스트 (데이터베이스 저장)
   - 단일 기기 로그인 정책
   - Stateless access token (데이터베이스 조회 불필요)
   - 자동 만료

3. **공격 방지:**
   - Replay 공격: Refresh token 화이트리스트
   - 토큰 오용: 타입 검사로 access token을 refresh로 사용 방지
   - 무차별 대입 공격: bcrypt 느린 해싱
   - XSS/CSRF: 토큰을 안전하게 저장 (httpOnly 쿠키 권장)

---

## 테스트 예제 (Testing Examples)

### cURL 예제

**회원가입:**
```bash
curl -X POST "http://localhost:8001/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "password123",
    "username": "testuser",
    "disability_type": "PHY"
  }'
```

**로그인:**
```bash
curl -X POST "http://localhost:8001/api/v1/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=test@example.com&password=password123"
```

**사용자 정보 조회:**
```bash
curl -X GET "http://localhost:8001/api/v1/auth/me" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

**토큰 갱신:**
```bash
curl -X POST "http://localhost:8001/api/v1/auth/refresh" \
  -H "Content-Type: application/json" \
  -d '{
    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
  }'
```

**로그아웃:**
```bash
curl -X POST "http://localhost:8001/api/v1/auth/logout" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

### JavaScript/TypeScript 예제

**React/Next.js 인증 컨텍스트 예제:**

```typescript
import { createContext, useContext, useState, useEffect } from 'react';

interface User {
  user_id: string;
  email: string;
  username?: string;
  disability_type?: string;
  created_at: string;
}

interface AuthContextType {
  user: User | null;
  login: (email: string, password: string) => Promise<boolean>;
  logout: () => Promise<void>;
  register: (data: RegisterData) => Promise<boolean>;
}

const AuthContext = createContext<AuthContextType>(null!);

export function AuthProvider({ children }) {
  const [user, setUser] = useState<User | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState<string | null>(null);

  // 토큰 자동 갱신
  useEffect(() => {
    const interval = setInterval(async () => {
      if (refreshToken) {
        await refreshAccessToken();
      }
    }, 25 * 60 * 1000); // 25분마다

    return () => clearInterval(interval);
  }, [refreshToken]);

  const login = async (email: string, password: string) => {
    try {
      const formData = new URLSearchParams();
      formData.append('username', email);
      formData.append('password', password);

      const response = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: formData,
      });

      if (response.ok) {
        const { access_token, refresh_token } = await response.json();
        setAccessToken(access_token);
        setRefreshToken(refresh_token);
        
        // 사용자 정보 가져오기
        await fetchUserInfo(access_token);
        return true;
      }
      return false;
    } catch (error) {
      console.error('Login error:', error);
      return false;
    }
  };

  const fetchUserInfo = async (token: string) => {
    const response = await fetch('/api/v1/auth/me', {
      headers: {
        'Authorization': `Bearer ${token}`,
      },
    });

    if (response.ok) {
      const userData = await response.json();
      setUser(userData);
    }
  };

  const refreshAccessToken = async () => {
    try {
      const response = await fetch('/api/v1/auth/refresh', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });

      if (response.ok) {
        const { access_token, refresh_token } = await response.json();
        setAccessToken(access_token);
        setRefreshToken(refresh_token);
        return true;
      }
      return false;
    } catch (error) {
      console.error('Token refresh error:', error);
      return false;
    }
  };

  const logout = async () => {
    try {
      if (accessToken) {
        await fetch('/api/v1/auth/logout', {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${accessToken}`,
          },
        });
      }
    } finally {
      setUser(null);
      setAccessToken(null);
      setRefreshToken(null);
    }
  };

  const register = async (data: RegisterData) => {
    try {
      const response = await fetch('/api/v1/auth/register', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(data),
      });

      return response.ok;
    } catch (error) {
      console.error('Registration error:', error);
      return false;
    }
  };

  return (
    <AuthContext.Provider value={{ user, login, logout, register }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
```

---

## 데이터베이스 스키마 (Database Schema Reference)

### Users 테이블
```sql
users (
  user_id UUID PRIMARY KEY,
  email VARCHAR UNIQUE NOT NULL,
  password_hash VARCHAR NOT NULL,
  username VARCHAR,
  disability_type VARCHAR,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT NOW(),
  last_login TIMESTAMP
)
```

### Refresh Tokens 테이블
```sql
refresh_tokens (
  user_id UUID REFERENCES users(user_id),
  token VARCHAR NOT NULL,
  expires_at TIMESTAMP NOT NULL
)
```

---

## 관련 파일 경로 (Related File Paths)

백엔드 코드 참조:

- **API 엔드포인트:** `transit-routing/app/api/v1/endpoints/auth.py`
- **보안 유틸리티:** `transit-routing/app/auth/security.py`
- **인증 서비스:** `transit-routing/app/services/auth_service.py`
- **의존성:** `transit-routing/app/api/deps.py`
- **모델:** `transit-routing/app/models/`
- **설정:** `transit-routing/app/core/config.py`
- **테스트:** `transit-routing/test/test_auth_*.py`

---

## 주의사항 및 알려진 이슈 (Notes and Known Issues)

1. **로그인 폼 데이터:** JSON이 아닌 `application/x-www-form-urlencoded` 형식 사용
2. **이메일을 username 필드에:** OAuth2 표준으로 "username" 필드에 이메일 입력
3. **토큰 저장:** httpOnly 쿠키 또는 안전한 저장소 사용 권장
4. **토큰 갱신:** Access token 만료 전에 자동 갱신 구현
5. **로그아웃 후 정리:** 클라이언트 측 토큰 삭제 필수
6. **전역 에러 처리:** 401 에러 발생 시 재인증 트리거
7. **CORS:** 프로덕션 배포 시 허용 도메인 제한 필요

---

## 문의 및 지원 (Support)

백엔드 API 관련 문의사항이나 버그 리포트는 백엔드 팀에 문의하세요.

**최종 업데이트:** 2025-11-24
**API 버전:** v1
**백엔드 브랜치:** `jwt-login-implement`
