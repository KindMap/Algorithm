"""
singleton caching 전략 사용
Thread Lock으로 서버 시작 시 한 번만 로드하여 메모리에 유지
전역 상태
모든 서비스가 동일한 캐시 인스턴스 참조
=> static 정적 데이터이므로 유리
=> unit test가 어렵지만 MVP 제작이 우선이므로 싱글톤 선택
"""

import logging
from typing import Dict, List, Optional, Tuple
from threading import Lock

logger = logging.getLogger(__name__)

_cache_lock = Lock()
_cache_init = False

# cache data
_stations_cache: Dict[str, Dict] = {}  # {station_cd: station_info}
_stations_list_cache: List[Dict] = []
_station_name_map_cache: Dict[str, str] = {}  # {name: station_cd}
_sections_cache: List[Dict] = []
_transfer_conv_cache: Dict[str, Dict] = {}  # {station_cd: conv_scores}
_lines_cache: Dict[str, List[str]] = {}  # {line: [station_cd, ...]}

_facility_cache: Dict[str, Dict] = {}  # {station_name: facility_info}
_congestion_cache: Dict[Tuple[str, str, str, str], Dict[str, float]] = {}
# {(station_cd, line, direction, day_type): {time_slot: congestion_value}}


def initialize_cache():
    """
    서버 시작 시 모든 정적 데이터를 메모리에 로드
    Thread-safe singleton pattern
    """
    import os

    global _cache_init
    global _stations_cache, _stations_list_cache, _station_name_map_cache
    global _lines_cache, _transfer_conv_cache

    with _cache_lock:
        if _cache_init:
            logger.info("캐시가 이미 초기화되었습니다.")
            return

        # 테스트 모드 체크: DB 연결 스킵 => for local unit test
        # if os.getenv("TESTING") == "true":
        #     _cache_init = True
        #     logger.info("테스트 모드: 캐시 초기화 스킵")
        #     return

        from app.db.database import (
            get_all_stations,
            get_all_sections,
            get_all_transfer_station_conv_scores,
            get_all_facility_data,
            get_all_congestion_data,
            _load_facility_rows,
        )

        logger.info("데이터 캐시 초기화 시작")

        # 1. 역 정보 로드
        _stations_list_cache = get_all_stations()
        _stations_cache = {s["station_cd"]: s for s in _stations_list_cache}
        _station_name_map_cache = {
            s["name"]: s["station_cd"] for s in _stations_list_cache
        }

        # 호선별 역 코드 매핑
        for station in _stations_list_cache:
            line = station["line"]
            station_cd = station["station_cd"]

            if line not in _lines_cache:
                _lines_cache[line] = []

            if station_cd not in _lines_cache[line]:
                _lines_cache[line].append(station_cd)

        logger.info(f"✓ 역 데이터 로드 완료: {len(_stations_cache)}개")
        logger.info(f"✓ 호선 데이터 로드 완료: {len(_lines_cache)}개 노선")

        # 2. 구간 정보 로드
        _sections_cache = get_all_sections()
        logger.info(f"✓ 구간 데이터 로드 완료: {len(_sections_cache)}개")

        # 3. 환승역 편의성 점수 정보 로드(레거시)
        transfer_list = get_all_transfer_station_conv_scores()
        _transfer_conv_cache = {t["station_cd"]: t for t in transfer_list}
        logger.info(f"✓ 환승역 데이터 로드 완료: {len(_transfer_conv_cache)}개")

        # 4. 환승역 편의시설 상세 정보 로드
        facility_list = get_all_facility_data()
        for fac in facility_list:
            # station_name을 key로 사용
            _facility_cache[fac["station_name"]] = fac

        logger.info(f"✓ 편의시설 데이터 로드 완료: {len(_facility_cache)}개 역")

        # 5. 혼잡도 정보 로드
        # 검색 효율을 위해 (station_cd, line, direction, day_type)을 복합 키로 사용
        congestion_list = get_all_congestion_data()

        # 30분 단위 time columns (t_0, t_30, ... t_1410) 미리 생성
        time_columns = [f"t_{i}" for i in range(0, 24 * 60, 30)]

        for row in congestion_list:
            key = (
                row["station_cd"],
                row["line"],
                row.get("direction", "up"),  # 기본값 처리
                row.get("day_type", "weekday"),
            )

            # 시간대별 데이터만 추출하여 경량화
            time_data = {}
            for col in time_columns:
                val = row.get(col)
                if val is not None:
                    # 0~100 퍼센트 값을 0.0~1.0 비율로 변환하여 저장 (엔진 사용 편의성)
                    time_data[col] = float(val) / 100.0 if val is not None else 0.0

            _congestion_cache[key] = time_data

        logger.info(f"✓ 혼잡도 데이터 로드 완료: {len(_congestion_cache)}개 항목")

        _cache_init = True
        logger.info("데이터 캐시 초기화 완료")


def get_stations_dict() -> Dict[str, Dict]:
    """
    역 정보 딕셔너리 반환 {station_cd: station_info}

    Returns:
        {
            "0222": {"station_cd": "0222", "name": "강남", "line": "2호선", ...},
            ...
        }
    """
    if not _cache_init:
        initialize_cache()
    return _stations_cache


def get_stations_list() -> List[Dict]:
    """
    역 정보 리스트 반환
    """
    if not _cache_init:
        initialize_cache()
    return _stations_list_cache


def get_station_name_map() -> Dict[str, str]:
    """
    역 이름 → 코드 매핑 반환 {name: station_cd}

    Returns:
        {"강남": "0222", "역삼": "0223", ...}
    """
    if not _cache_init:
        initialize_cache()
    return _station_name_map_cache


def get_sections_list() -> List[Dict]:
    """
    구간 정보 리스트 반환
    """
    if not _cache_init:
        initialize_cache()
    return _sections_cache


def get_transfer_conv_dict() -> Dict[str, Dict]:
    """
    환승역 편의성 정보 반환 {station_cd: conv_scores}
    """
    if not _cache_init:
        initialize_cache()
    return _transfer_conv_cache


def get_station_by_code(station_cd: str) -> Optional[Dict]:
    """
    캐시에서 역 정보 조회

    Args:
        station_cd: 역 코드

    Returns:
        역 정보 딕셔너리 또는 None
    """
    if not _cache_init:
        initialize_cache()
    return _stations_cache.get(station_cd)


def get_station_name_by_code(station_cd: str) -> str:
    """
    캐시에서 역 이름 조회

    Args:
        station_cd: 역 코드

    Returns:
        역 이름 (없으면 station_cd 반환)
    """
    station = get_station_by_code(station_cd)
    return station["name"] if station else station_cd


def get_station_cd_by_name(station_name: str) -> Optional[str]:
    """
    캐시에서 역 코드 조회 (정확 일치 → 부분 일치)

    Args:
        station_name: 역 이름

    Returns:
        역 코드 또는 None
    """
    if not _cache_init:
        initialize_cache()

    station_name = station_name.strip()

    # 1단계: 정확 일치
    if station_name in _station_name_map_cache:
        return _station_name_map_cache[station_name]

    # 2단계: 부분 일치
    for name, cd in _station_name_map_cache.items():
        if station_name in name or name in station_name:
            logger.debug(f"부분 일치: {station_name} → {name} ({cd})")
            return cd

    # 3단계: DB 쿼리 (캐시 미스 - 드물게 발생)
    logger.warning(f"캐시에서 역을 찾을 수 없음, DB 조회 시도: {station_name}")
    from app.db.database import get_station_cd_by_name as db_get_station_cd

    return db_get_station_cd(station_name)


def search_stations_by_name(keyword: str, limit: int = 10) -> List[Dict]:
    """
    캐시에서 역 검색 (자동완성용)

    Args:
        keyword: 검색 키워드
        limit: 최대 결과 수

    Returns:
        검색 결과 리스트
    """
    if not _cache_init:
        initialize_cache()

    keyword = keyword.strip().lower()
    results = []

    for station in _stations_list_cache:
        name_lower = station["name"].lower()

        # 검색 조건
        if keyword in name_lower:
            # 우선순위 계산
            if name_lower == keyword:
                priority = 1  # 정확 일치
            elif name_lower.startswith(keyword):
                priority = 2  # 시작 일치
            else:
                priority = 3  # 부분 일치

            results.append({**station, "_priority": priority})

    # 우선순위 정렬
    results.sort(key=lambda x: (x["_priority"], len(x["name"]), x["name"]))

    # _priority 필드 제거
    for r in results:
        r.pop("_priority", None)

    return results[:limit]


def get_transfer_conv_by_code(station_cd: str) -> Optional[Dict]:
    """
    캐시에서 환승역 편의성 정보 조회
    """
    if not _cache_init:
        initialize_cache()
    return _transfer_conv_cache.get(station_cd)


def get_lines_dict() -> Dict[str, List[str]]:
    """
    호선별 역 코드 딕셔너리 반환 {line: [station_cd, ...]}

    Returns:
        {
            "1호선": ["0150", "0151", ...],
            "2호선": ["0201", "0202", ...],
            ...
        }
    """
    if not _cache_init:
        initialize_cache()
    return _lines_cache


def get_stations_by_line(line: str) -> List[str]:
    """
    특정 호선의 역 코드 리스트 반환

    Args:
        line: 호선명 (예: "1호선", "2호선")

    Returns:
        역 코드 리스트 (예: ["0201", "0202", ...])

    Example:
        >>> get_stations_by_line("2호선")
        ["0201", "0202", "0203", ...]
    """
    if not _cache_init:
        initialize_cache()
    return _lines_cache.get(line, [])


def get_line_by_station_cd(station_cd: str) -> Optional[str]:
    """
    역 코드로 호선명 조회

    Args:
        station_cd: 역 코드

    Returns:
        호선명 또는 None

    Example:
        >>> get_line_by_station_cd("0222")
        "2호선"
    """
    station = get_station_by_code(station_cd)
    return station["line"] if station else None


def clear_cache():
    """
    캐시 초기화 (테스트용)
    """
    global _cache_init
    global _stations_cache, _stations_list_cache, _station_name_map_cache
    global _sections_cache, _transfer_conv_cache
    global _lines_cache, _facility_cache, _congestion_cache

    with _cache_lock:
        _stations_cache.clear()
        _stations_list_cache.clear()
        _station_name_map_cache.clear()
        _sections_cache.clear()
        _transfer_conv_cache.clear()
        _lines_cache.clear()
        _facility_cache.clear()
        _congestion_cache.clear()

        _cache_init = False
        logger.info("캐시 초기화됨")


def reload_cache():
    """
    캐시 재로드
    """
    clear_cache()
    initialize_cache()


def get_facility_info_by_name(station_name: str) -> Optional[Dict]:
    """
    역 이름으로 편의시설 정보 조회
    Args:
        station_name: 역 이름 (예: "강남")
    Returns:
        편의시설 정보 Dict 또는 None
    """
    if not _cache_init:
        initialize_cache()
    return _facility_cache.get(station_name)


def get_facility_info_by_cd(station_cd: str) -> Optional[Dict]:
    """
    역 코드로 편의시설 정보 조회
    (역 코드로 이름을 찾은 후 편의시설 조회)
    """
    if not _cache_init:
        initialize_cache()

    station_name = get_station_name_by_code(station_cd)
    if not station_name:
        return None

    return _facility_cache.get(station_name)


def get_congestion_data(
    station_cd: str, line: str, direction: str, day_type: str
) -> Optional[Dict[str, float]]:
    """
    특정 역, 노선, 방향, 요일의 시간대별 혼잡도 조회

    Args:
        station_cd: 역 코드
        line: 호선
        direction: 방향 (up/down/in/out)
        day_type: 요일 구분 (weekday/sat/sun)

    Returns:
        {"t_540": 0.3, "t_570": 0.5, ...} 또는 None
    """
    if not _cache_init:
        initialize_cache()

    key = (station_cd, line, direction, day_type)
    return _congestion_cache.get(key)


def get_all_congestion_cache() -> Dict:
    """
    C++ 엔진 초기화용 전체 혼잡도 데이터 반환
    """
    if not _cache_init:
        initialize_cache()
    return _congestion_cache


def refresh_facility_scores(self):
    """
    [New] 편의시설 점수 갱신 (C++ 엔진 업데이트)
    이 메서드가 스케줄러와 초기화 시점에 호출됩니다.
    """
    try:
        # 1. DB에서 데이터 로드
        facility_rows = self._load_facility_rows()

        if not facility_rows:
            logger.warning("업데이트할 편의시설 데이터가 없습니다.")
            return

        # 2. C++ 메서드 호출 (질문하신 메서드가 호출되는 지점)
        # update_facility_scores는 bindings.cpp에 바인딩되어 있어야 함
        self.data_container.update_facility_scores(facility_rows)

        logger.info(
            f"✅ C++ 엔진 편의시설 점수 업데이트 완료 ({len(facility_rows)}개 역 그룹)"
        )

    except Exception as e:
        logger.error(f"C++ 엔진 업데이트 중 오류 발생: {e}")
