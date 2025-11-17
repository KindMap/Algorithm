"""
singleton caching 전략 사용
Thread Lock으로 서버 시작 시 한 번만 로드하여 메모리에 유지
전역 상태
모든 서비스가 동일한 캐시 인스턴스 참조
=> static 정적 데이터이므로 유리
=> unit test가 어렵지만 MVP 제작이 우선이므로 싱글톤 선택
"""

import logging
from typing import Dict, List, Optional
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
        if os.getenv("TESTING") == "true":
            _cache_init = True
            logger.info("테스트 모드: 캐시 초기화 스킵")
            return

        from app.db.database import (
            get_all_stations,
            get_all_sections,
            get_all_transfer_station_conv_scores,
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

        # 3. 환승역 편의성 정보 로드
        transfer_list = get_all_transfer_station_conv_scores()
        _transfer_conv_cache = {t["station_cd"]: t for t in transfer_list}
        logger.info(f"✓ 환승역 데이터 로드 완료: {len(_transfer_conv_cache)}개")

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
    global _lines_cache

    with _cache_lock:
        _stations_cache.clear()
        _stations_list_cache.clear()
        _station_name_map_cache.clear()
        _sections_cache.clear()
        _transfer_conv_cache.clear()
        _lines_cache.clear()
        _cache_init = False
        logger.info("캐시 초기화됨")


def reload_cache():
    """
    캐시 재로드
    """
    clear_cache()
    initialize_cache()
