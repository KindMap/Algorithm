from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager
from dotenv import load_dotenv
import logging

# 환경변수 로드
load_dotenv()

from label import Label
from mc_raptor import McRaptor
from anp_weights import ANPWeightCalculator
from database import (
    get_all_stations,
    get_all_sections,
    get_all_transfer_station_conv_scores,
    get_station_by_code,  # get_station_info 대신 사용
)
from config import (
    DISABILITY_TYPES,
    WALKING_SPEED,
    DEFAULT_TRANSFER_DISTANCE,
    CONGESTION_CONFIG,
)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# 전역 변수
raptor_instance: Optional[McRaptor] = None
anp_calculator: Optional[ANPWeightCalculator] = None

# 장애 유형별 선호 편의시설 매핑
PREFERRED_FACILITIES = {
    "PHY": ["elevator", "wheelchair_ramp", "wheelchair_lift"],
    "VIS": ["braille_block", "voice_guide", "screen_door"],
    "AUD": ["visual_display", "screen_door"],
    "ELD": ["elevator", "escalator", "rest_area"],
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global raptor_instance, anp_calculator

    try:
        logger.info("서버 시작: 데이터 로딩 중...")

        # database connection pool 초기화
        from database import initialize_pool

        initialize_pool()
        logger.info("database connection pool 초기화 완료")

        # db에서 모든 데이터 미리 로드
        stations = get_all_stations()
        sections = get_all_sections()
        convenience_scores = get_all_transfer_station_conv_scores()

        logger.info(
            f"로드 완료: 역 {len(stations)}개, 구간 {len(sections)}개, 편의성 점수 {len(convenience_scores)} 개"
        )

        # => anp_calculator 초기화 + 혼잡도 데이터 로드
        anp_calculator = ANPWeightCalculator()

        # McRaptor 초기화 + 그래프 및 맵 사전 연산
        raptor_instance = McRaptor(
            stations=stations,
            sections=sections,
            convenience_scores=convenience_scores,
            anp_calculator=anp_calculator,
        )

        logger.info("RAPTOR 초기화 완료")

    except Exception as e:
        logger.error(f"초기화 실패: {e}")
        raise

    yield

    # Shutdown 전에
    from database import close_pool

    close_pool()
    logger.info("Database connection pool 종료")
    logger.info("서버 종료")


app = FastAPI(title="교통약자 경로탐색 API", version="1.0.0", lifespan=lifespan)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RouteRequest(BaseModel):
    """경로 탐색 요청"""

    origin: str
    destination: str
    departure_time: datetime
    disability_type: str  # PHY, VIS, AUD, ELD


class RouteSegment(BaseModel):
    """경로 구간 정보"""

    station: str
    line: str
    arrival_time: float  # 누적 소요시간 (분)


class TransferStationDetail(BaseModel):
    """환승역 상세 정보"""

    station_name: str
    convenience_score: float
    congestion_score: float
    walking_distance: float  # 미터
    walking_time: float  # 분
    preferred_facilities: Dict[str, bool]  # 선호 편의시설 유무


# 교통약자 유형에 따라 선호 편의시설 유무 정보 포함
class RouteResponse(BaseModel):
    """경로 응답"""

    total_time: float  # 총 소요시간 (분)
    transfers: int  # 환승 횟수
    transfer_difficulty: float  # 환승 난이도 총합
    convenience_score: float  # 평균 편의도 점수
    congestion_score: float  # 평균 혼잡도 점수
    anp_score: float  # ANP 종합 점수
    segments: List[RouteSegment]  # 경로 세그먼트
    transfer_stations: List[str]  # 환승역 목록(이름)
    transfer_details: List[TransferStationDetail]  # 환승역 상세 정보
    preferred_facilities_available: Dict[str, bool]  # 선호 편의시설 유무


class SearchResponse(BaseModel):
    """경로 탐색 응답"""

    routes: List[RouteResponse]
    search_time: float  # 탐색 소요시간 (초)
    message: str


@app.get("/")
async def root():
    """헬스 체크"""
    return {"status": "healthy", "service": "교통약자 경로탐색 API", "version": "1.0.0"}


# 응답 형식 수정!
@app.post("/search", response_model=SearchResponse)
async def search_route(request: RouteRequest):
    """
    교통약자를 위한 최적 경로 탐색

    Args:
        request: 경로 탐색 요청
            - origin: 출발역
            - destination: 도착역
            - departure_time: 출발 시각
            - disability_type: 장애 유형 (PHY/VIS/AUD/ELD)

    Returns:
        SearchResponse: 파레토 최적 경로 목록
    """
    if not raptor_instance:
        raise HTTPException(status_code=500, detail="서버가 초기화되지 않았습니다")

    # 장애 유형 검증
    valid_types = list(DISABILITY_TYPES.keys())
    if request.disability_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"유효하지 않은 장애 유형입니다. 허용: {valid_types}",
        )

    try:
        import time

        start_time = time.time()

        logger.info(
            f"경로 탐색 시작: {request.origin} → {request.destination} "
            f"({request.disability_type}, {request.departure_time})"
        )

        # Mc-RAPTOR로 파레토 최적 경로 탐색
        pareto_routes = raptor_instance.find_routes(
            origin=request.origin,
            destination=request.destination,
            departure_time=request.departure_time,
            disability_type=request.disability_type,
            max_rounds=5,
        )

        if not pareto_routes:
            search_time = time.time() - start_time
            logger.warning(
                f"경로 없음: {request.origin} → {request.destination} ({search_time:.2f}초)"
            )
            return SearchResponse(
                routes=[],
                search_time=search_time,
                message=f"{request.origin}에서 {request.destination}까지 가는 경로를 찾을 수 없습니다",
            )

        # ANP 가중치로 경로 순위 매기기
        ranked_routes = raptor_instance.rank_routes(
            pareto_routes, request.disability_type
        )

        # 상위 5개 경로만 선택
        top_routes = ranked_routes[:5]

        # 응답 형식으로 변환
        response_routes = []
        for label, anp_score in top_routes:
            # [수정] station_cd 기반의 label을 이름 기반으로 변환
            segments = _create_segments(label)
            transfer_details = _create_transfer_details(
                label, request.disability_type, request.departure_time
            )

            # 경로 전체의 편의도/혼잡도 평균 (Label에 이미 계산되어 있음)
            total_convenience = label.convenience_score
            total_congestion = label.congestion_score

            # 환승역 이름 목록 (cd -> name)
            transfer_station_names = [
                raptor_instance.get_station_name_from_cd(cd)
                for cd in label.transfer_stations
            ]

            # 선호 편의시설 유무 집계
            preferred_facility_list = PREFERRED_FACILITIES.get(
                request.disability_type, []
            )
            overall_facilities = {}
            for facility in preferred_facility_list:
                # 모든 환승역에 해당 시설이 있는지 확인
                has_facility = (
                    all(
                        td.preferred_facilities.get(facility, False)
                        for td in transfer_details
                    )
                    if transfer_details
                    else False  # 환승이 없으면 False
                )
                overall_facilities[facility] = has_facility

            response_routes.append(
                RouteResponse(
                    total_time=label.arrival_time,
                    transfers=label.transfers,
                    transfer_difficulty=label.transfer_difficulty,
                    convenience_score=total_convenience,
                    congestion_score=total_congestion,
                    anp_score=anp_score,
                    segments=segments,
                    transfer_stations=transfer_station_names,
                    transfer_details=transfer_details,
                    preferred_facilities_available=overall_facilities,
                )
            )

        search_time = time.time() - start_time

        logger.info(
            f"경로 탐색 완료: {len(pareto_routes)}개 파레토 최적해 중 "
            f"{len(response_routes)}개 반환 (소요시간: {search_time:.2f}초)"
        )

        return SearchResponse(
            routes=response_routes,
            search_time=search_time,
            message=f"{len(response_routes)}개의 최적 경로를 찾았습니다",
        )

    except ValueError as e:
        logger.error(f"입력 오류: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"경로 탐색 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="경로 탐색 중 오류가 발생했습니다")


def _create_segments(label: Label) -> List[RouteSegment]:
    """
    Label로부터 RouteSegment 리스트 생성

    Args:
        label(station_cd 기반) => RouteSegment(이름 기반) 리스트 생성

    Returns:
        List[RouteSegment]: 구간별 정보
    """
    segments = []
    cumulative_time = 0.0
    time_per_segment = 2.0  # 기본 구간 이동시간 (분)

    # label.route -> List[staion_cd]
    for i, station_cd in enumerate(label.route):
        if i == 0:
            cumulative_time = 0.0
        else:
            cumulative_time = (
                label.arrival_time
                if (i == len(label.route) - 1)
                else time_per_segment * i
            )

        if i < len(label.lines):
            line = label.lines[i]
        else:
            line = label.lines[-1] if label.lines else "Unknown"

        # station_cd -> station_name 변환
        station_name = raptor_instance.get_station_name_from_cd(station_cd)

        segments.append(
            RouteSegment(station=station_name, line=line, arrival_time=cumulative_time)
        )

    return segments


def _create_transfer_details(
    label: Label, disability_type: str, departure_time: datetime
) -> List[TransferStationDetail]:
    """
    staion_cd 기반 조회 + 환승 컨텍스트 활용하여 환승역 상세 정보 생성

    Args:
        label: 경로 라벨
        disability_type: 장애 유형
        departure_time: 출발 시각

    Returns:
        List[TransferStationDetail]: 환승역 상세 정보 목록
    """
    # 전역 인스턴스 사용
    global raptor_instance, anp_calculator

    transfer_details = []
    preferred_facility_list = PREFERRED_FACILITIES.get(disability_type, [])
    walking_speed = WALKING_SPEED.get(disability_type, 1.0)

    # label.transfer_context 에서 (station_cd, from_line, to_line) 정보를 가져옴
    for station_cd, from_line, to_line in label.transfer_context:
        try:
            # station_cd로 역 이름, 기본 호선 등 기본 정보 조회
            station_info = raptor_instance.get_station_info_from_cd(station_cd)
            station_name = station_info.get("name", "Unknown")

            # station_cd로 편의도 점수 계산
            convenience_score = raptor_instance._calculate_convenience_score_cached(
                station_cd
            )
            # label.route에서 현재 환승역의 다음 역을 찾아 실제 진행 방향을 파악
            try:
                # 현재 환승역이 경로상 몇 번째인지 찾기
                current_idx = label.route.index(station_cd)
                # 경로상의 바로 다음 역
                next_station_cd = label.route[current_idx + 1]

                # to_line을 기준으로 방향 결정
                direction = raptor_instance._determine_direction(
                    station_cd, next_station_cd, to_line
                )
            except (ValueError, IndexError):
                # 기본 방향 up으로 설정
                direction = "up"

            congestion_score = anp_calculator.get_congestion_from_rds(
                station_cd, to_line, direction, departure_time
            )

            # (station_cd, from_line, to_line)을 사용하여 정확한 환승 거리 조회
            walking_distance = raptor_instance._get_transfer_distance_cached(
                station_cd, from_line, to_line
            )

            walking_time = (
                anp_calculator.calculate_transfer_walking_time(
                    walking_distance, disability_type
                )
                / 60.0
            )  # 초 -> 분

            # 편의 시설 테이블 별도 구현 필요!!!
            # 우선 transfer_station_convenience에 존재하지 않으면 없다고 판단
            # 추후 db table 구축 후 수정하기!!!
            facilities_data = raptor_instance.convenience_scores.get(station_cd)

            # station_cd가 존재한다면 -> 있다고 판단
            if facilities_data:
                preferred_facilities = {
                    facility: facilities_data.get(facility, False)
                    for facility in preferred_facility_list
                }
            else:
                # station_cd가 존재하지 않는다면 -> 없다고 판단
                preferred_facilities = {
                    facility: False for facility in preferred_facility_list
                }

            transfer_details.append(
                TransferStationDetail(
                    station_name=station_name,
                    convenience_score=convenience_score,
                    congestion_score=congestion_score,
                    walking_distance=walking_distance,
                    walking_time=walking_time,
                    preferred_facilities=preferred_facilities,
                )
            )

        except Exception as e:
            logger.warning(f"환승역 정보 조회 실패 ({station_cd}): {e}")
            # [수정] station_cd -> station_name 변환
            transfer_details.append(
                TransferStationDetail(
                    station_name=raptor_instance.get_station_name_from_cd(station_cd),
                    convenience_score=0.0,
                    congestion_score=CONGESTION_CONFIG["default_value"],
                    walking_distance=DEFAULT_TRANSFER_DISTANCE,
                    walking_time=DEFAULT_TRANSFER_DISTANCE / walking_speed / 60.0,
                    preferred_facilities={
                        facility: False for facility in preferred_facility_list
                    },
                )
            )

    return transfer_details


@app.get("/stations")
async def get_stations():
    """전체 역 목록 조회"""
    if not raptor_instance:
        raise HTTPException(status_code=500, detail="서버가 초기화되지 않았습니다")
    try:
        # raptor 인스턴스에 사전 연산된 station_name_to_cds 맵의 키를 사용
        station_names = list(raptor_instance.station_name_to_cds.keys())
        station_names.sort()
        return {"total": len(station_names), "stations": station_names}
    except Exception as e:
        logger.error(f"역 목록 조회 실패: {e}")
        raise HTTPException(status_code=500, detail="역 목록을 가져올 수 없습니다")


@app.get("/station/{station_name}")
async def get_station_detail(station_name: str):
    """특정 역 상세 정보 조회 (해당 이름을 가진 모든 station_cd 반환)"""
    if not raptor_instance:
        raise HTTPException(status_code=500, detail="서버가 초기화되지 않았습니다")
    try:
        # raptor 인스턴스의 맵을 조회
        station_cds = raptor_instance.station_name_to_cds.get(station_name)
        if not station_cds:
            raise HTTPException(
                status_code=404, detail=f"역 '{station_name}'을 찾을 수 없습니다"
            )

        # DB에서 각 station_cd의 상세 정보 조회
        station_details = []
        for cd in station_cds:
            # get_station_by_code는 DB를 조회함
            info = get_station_by_code(cd)
            if info:
                station_details.append(info)

        return {
            "name": station_name,
            "count": len(station_details),
            "details": station_details,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"역 정보 조회 실패: {e}")
        raise HTTPException(status_code=500, detail="역 정보를 가져올 수 없습니다")


@app.get("/disability-types")
async def get_disability_types():
    """지원하는 장애 유형 목록"""
    return {
        "types": [
            {"code": code, "name": name, "description": name}
            for code, name in DISABILITY_TYPES.items()
        ]
    }


@app.get("/anp-weights/{disability_type}")
async def get_anp_weights(disability_type: str):
    """특정 장애 유형의 ANP 가중치 조회"""
    if not anp_calculator:
        raise HTTPException(
            status_code=500, detail="ANP 계산기가 초기화되지 않았습니다"
        )

    valid_types = list(DISABILITY_TYPES.keys())
    if disability_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"유효하지 않은 장애 유형입니다. 허용: {valid_types}",
        )

    try:
        weights = anp_calculator.calculate_weights(disability_type)

        return {
            "disability_type": disability_type,
            "disability_name": DISABILITY_TYPES[disability_type],
            "weights": weights,
            "description": {
                "travel_time": "총 소요시간",
                "transfers": "환승 횟수",
                "transfer_difficulty": "환승 난이도",
                "convenience": "편의도",
                "congestion": "혼잡도",
            },
        }
    except Exception as e:
        logger.error(f"ANP 가중치 조회 실패: {e}")
        raise HTTPException(status_code=500, detail="ANP 가중치를 계산할 수 없습니다")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
