from fastapi import APIRouter, HTTPException, status, Depends, Body
from fastapi.security import OAuth2PasswordRequestForm
from app.models.requests import UserRegisterRequest
from app.models.responses import TokenResponse, UserResponse, TokenPayload
from app.services.auth_service import AuthService
from app.auth.security import create_access_token, create_refresh_token
from app.api.deps import get_current_user, get_current_active_user

router = APIRouter()  # auth/ 가 중복되지 않도록 수정


@router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
async def register(user_data: UserRegisterRequest):
    if AuthService.email_exists(user_data.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이미 사용 중인 이메일입니다.",
        )

    user = AuthService.create_user(
        email=user_data.email,
        password=user_data.password,
        username=user_data.username,
        disability_type=user_data.disability_type,
    )

    # Pydantic rsponse_model이 자동으로 User -> UserResponse 변환
    return user


@router.post("/login", response_model=TokenResponse)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    # OAuth2PasswordRequestForm은 username, password 필드이지만
    # 현재 email을 ID로 사용하므로 form_data.username <- email
    user = AuthService.authenticate_user(form_data.username, form_data.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 혹은 비밀번호를 잘못 입력하셨습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="만료된 사용자입니다."
        )

    access_token = create_access_token(subject=str(user.user_id))
    refresh_token = create_refresh_token(user.user_id)

    AuthService.save_refresh_token(user.user_id, refresh_token)

    return TokenResponse(
        access_token=access_token, refresh_token=refresh_token, token_type="bearer"
    )


# 토큰 갱신 -> Token 정보 반환
@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    # Body에서 JSON 형태로 토큰을 받도록 강제 => Query Param 방지
    refresh_token: str = Body(..., embed=True)
):
    user_id = AuthService.verify_refresh_token(refresh_token)

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    access_token = create_access_token(subject=str(user_id))
    new_refresh_token = create_refresh_token(user_id)

    # 기존 토큰을 대체
    AuthService.save_refresh_token(user_id, new_refresh_token)

    return TokenResponse(
        access_token=access_token, refresh_token=new_refresh_token, token_type="bearer"
    )


@router.post("/logout")
async def logout(
    # 로그인 안 한 사람이 로그아웃 할 수 없도록 active user 의존성 사용
    current_user=Depends(get_current_active_user),
):
    AuthService.revoke_refresh_tokens(current_user.user_id)
    return {"message": "Successfully logged out"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    # 로그인 필수
    current_user=Depends(get_current_active_user),
):
    return current_user  # response_model이 자동 변환


# 추후 구현할 엔드포인트
# 비밀번호 변경, 비밀번호 찾기/초기화, 이메일 중복 확인, 회원 탈퇴
