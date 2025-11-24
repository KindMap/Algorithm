from typing import Optional
from pydantic import BaseModel, Field, EmailStr
from uuid import UUID

# service별 requests 구조 정의


# 경로 안내 엔드포인트에서 대안으로 제공하는 request
class NavigationStartRequest(BaseModel):
    origin: str = Field(..., description="출발지 역 이름")
    destination: str = Field(..., description="목적지 역 이름")
    disability_type: str = Field(
        default="PHY", description="교통약자 유형 (PHY/VIS/AUD/ELD)"
    )


# 위치 정보 업데이트
class LocationUpdateRequest(BaseModel):
    latitude: float = Field(..., ge=-90, le=90, description="위도")
    longitude: float = Field(..., ge=-180, le=180, description="경도")
    accuracy: Optional[float] = Field(default=50, description="GPS 정확도 (미터)")
    timestamp: Optional[str] = Field(default=None, description="타임스탬프")


# 경로 재탐색
class RecalculateRouteRequest(BaseModel):
    latitude: float = Field(..., ge=-90, le=90, description="현재 위도")
    longitude: float = Field(..., ge=-180, le=180, description="현재 경도")
    disability_type: str = Field(default="PHY", description="교통약자 유형")


# User 회원가입 요청
class UserRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    username: Optional[str] = None
    disability_type: Optional[str] = Field(None, pattern="^(PHY|VIS|AUD|ELD|NONE)$")


# User 로그인 요청
class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str
