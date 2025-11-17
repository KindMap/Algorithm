import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from typing import List, Dict, Optional
from contextlib import contextmanager
import logging

from app.algorithms.distance_calculator import DistanceCalculator
from app.core.config import settings

logger = logging.getLogger(__name__)

_connection_pool = None
_distance_calculator = None


def get_distance_calculator() -> DistanceCalculator:
    global _distance_calculator
    if _distance_calculator is None:
        _distance_calculator = DistanceCalculator(cache_file="distance_cache.pkl")
    return _distance_calculator


def initialize_pool():
    global _connection_pool
    if _connection_pool is None:
        # AWS EC2 t3.medium 기준 최대
        _connection_pool = pool.ThreadedConnectionPool(
            minconn=10, maxconn=50, **settings.DB_CONFIG
        )
        logger.info("Database connection pool initialized")


def close_pool():
    global _connection_pool
    if _connection_pool:
        _connection_pool.closeall()
        logger.info("Database connection pool closed")


@contextmanager
def get_db_connection():
    if _connection_pool is None:
        raise RuntimeError("Connection pool이 초기화되지 않았습니다")

    connection = None
    try:
        connection = _connection_pool.getconn()
        yield connection
    except psycopg2.Error as e:
        logger.error(f"Database error: {e}")
        if connection:
            connection.rollback()
        raise
    finally:
        if connection:
            _connection_pool.putconn(connection)


@contextmanager
def get_db_cursor(cursor_factory=RealDictCursor):
    with get_db_connection() as connection:
        cursor = connection.cursor(cursor_factory=cursor_factory)
        try:
            yield cursor
            connection.commit()
        except Exception as e:
            connection.rollback()
            logger.error(f"Transaction rolled back: {e}")
            raise
        finally:
            cursor.close()


def get_all_stations(line: Optional[str] = None) -> List[Dict]:
    if line:
        query = """
        SELECT station_id, line, name, lat, lng, station_cd
        FROM subway_station
        WHERE line = %(line)s
        ORDER BY station_id
        """
        params = {"line": line}
    else:
        query = """
        SELECT station_id, line, name, lat, lng, station_cd
        FROM subway_station
        ORDER BY station_id
        """
        params = None

    with get_db_cursor() as cursor:
        cursor.execute(query, params)
        return cursor.fetchall()


def get_station_by_code(station_cd: str) -> Optional[Dict]:
    query = """
    SELECT station_id, line, name, lat, lng, station_cd
    FROM subway_station
    WHERE station_cd = %(station_cd)s
    """

    with get_db_cursor() as cursor:
        cursor.execute(query, {"station_cd": station_cd})
        return cursor.fetchone()


def get_stations_by_codes(station_cds: List[str]) -> List[Dict]:
    query = """
    SELECT station_id, line, name, lat, lng, station_cd
    FROM subway_station
    WHERE station_cd = ANY(%(station_cd)s)
    ORDER BY array_position(%(station_cd)s, station_cd)
    """

    with get_db_cursor() as cursor:
        cursor.execute(query, {"station_cd": station_cds})
        return cursor.fetchall()


def get_all_sections(line: Optional[str] = None) -> List[Dict]:
    if line:
        query = """
        SELECT section_id, line, up_station_name, down_station_name, section_order, via_coordinates
        FROM subway_section
        WHERE line = %(line)s
        ORDER BY section_order
        """
        params = {"line": line}
    else:
        query = """
        SELECT section_id, line, up_station_name, down_station_name, section_order, via_coordinates
        FROM subway_section
        ORDER BY line, section_order
        """
        params = None

    with get_db_cursor() as cursor:
        cursor.execute(query, params)
        return cursor.fetchall()


def get_all_transfer_station_conv_scores() -> List[Dict]:
    query = """
    SELECT * FROM transfer_station_convenience
    ORDER BY station_cd
    """

    with get_db_cursor() as cursor:
        cursor.execute(query)
        return cursor.fetchall()


def get_transfer_conv_score_by_code(station_cd: str) -> Optional[Dict]:
    query = """
    SELECT * FROM transfer_station_convenience
    WHERE station_cd = %(station_cd)s
    """

    with get_db_cursor() as cursor:
        cursor.execute(query, {"station_cd": station_cd})
        return cursor.fetchone()


def get_station_code(station_id: str) -> str:
    query = """
    SELECT station_cd 
    FROM subway_station 
    WHERE station_id = %(station_id)s
    """

    try:
        with get_db_cursor() as cursor:
            cursor.execute(query, {"station_id": station_id})
            result = cursor.fetchone()

            if result:
                return result["station_cd"]
            else:
                logger.warning(f"역 코드 없음: {station_id}")
                return None

    except Exception as e:
        logger.error(f"역 코드 조회 실패: {e}")
        return None


def get_station_info(station_id: str) -> Dict[str, any]:
    query = """
    SELECT station_cd, name as station_name
    FROM subway_station
    WHERE station_id = %(station_id)s
    """

    try:
        with get_db_cursor() as cursor:
            cursor.execute(query, {"station_id": station_id})
            result = cursor.fetchone()

            if result:
                return {
                    "station_cd": result["station_cd"],
                    "station_name": result["station_name"],
                }
            else:
                return None

    except Exception as e:
        logger.error(f"역 정보 조회 실패: {e}")
        return None


def get_transfer_distance(station_cd: str, from_line: str, to_line: str) -> float:
    from app.core.config import DEFAULT_TRANSFER_DISTANCE

    query = """
    SELECT distance
    FROM transfer_distance_time
    WHERE station_cd = %(station_cd)s 
    AND line_num = %(line_num)s
    AND transfer_line = %(to_line)s
    """

    try:
        line_num = from_line

        with get_db_cursor() as cursor:
            cursor.execute(
                query,
                {"station_cd": station_cd, "line_num": line_num, "to_line": to_line},
            )
            result = cursor.fetchone()

            if result:
                return float(result["distance"])
            else:
                return DEFAULT_TRANSFER_DISTANCE

    except Exception as e:
        logger.error(f"환승 거리 조회 실패: {e}")
        return DEFAULT_TRANSFER_DISTANCE


def get_station_cd_by_name(station_name: str) -> Optional[str]:
    """
    역 이름으로 station_cd 조회 (정확 일치 → 부분 일치)

    Args:
        station_name: 검색할 역 이름

    Returns:
        station_cd 또는 None

    Example:
        >>> get_station_cd_by_name("강남")
        "0222"
        >>> get_station_cd_by_name("강남역")  # 부분 일치
        "0222"
    """
    station_name = station_name.strip()

    # 1단계: 정확히 일치하는 역 찾기
    query_exact = """
    SELECT station_cd, name, line
    FROM subway_station
    WHERE TRIM(name) = %(station_name)s
    LIMIT 1
    """

    with get_db_cursor() as cursor:
        cursor.execute(query_exact, {"station_name": station_name})
        result = cursor.fetchone()

        if result:
            logger.debug(
                f"역 찾음 (정확 일치): {result['name']} ({result['line']}) - {result['station_cd']}"
            )
            return result["station_cd"]

        # 2단계: 부분 일치 검색 (입력값이 역 이름에 포함되거나, 역 이름이 입력값에 포함)
        query_partial = """
        SELECT station_cd, name, line
        FROM subway_station
        WHERE TRIM(name) LIKE %(pattern1)s 
           OR %(station_name)s LIKE '%' || TRIM(name) || '%'
        ORDER BY 
            CASE 
                WHEN TRIM(name) LIKE %(pattern1)s THEN 1
                ELSE 2
            END,
            LENGTH(name) ASC
        LIMIT 1
        """

        cursor.execute(
            query_partial,
            {"pattern1": f"%{station_name}%", "station_name": station_name},
        )
        result = cursor.fetchone()

        if result:
            logger.debug(
                f"역 찾음 (부분 일치): {station_name} → {result['name']} ({result['line']}) - {result['station_cd']}"
            )
            return result["station_cd"]
        else:
            logger.warning(f"역을 찾을 수 없음: {station_name}")
            return None


def get_station_name_by_cd(station_cd: str) -> Optional[str]:
    """
    station_cd로 역 이름 조회

    Args:
        station_cd: 역 코드

    Returns:
        역 이름 또는 None
    """
    query = """
    SELECT name
    FROM subway_station
    WHERE station_cd = %(station_cd)s
    LIMIT 1
    """

    with get_db_cursor() as cursor:
        cursor.execute(query, {"station_cd": station_cd})
        result = cursor.fetchone()

        if result:
            return result["name"]
        else:
            logger.warning(f"역 이름을 찾을 수 없음: {station_cd}")
            return station_cd  # 실패 시 코드 그대로 반환


def search_stations_by_name(keyword: str, limit: int = 10) -> List[Dict]:
    """
    역 이름 검색 (자동완성용)

    Args:
        keyword: 검색 키워드
        limit: 최대 결과 수

    Returns:
        검색된 역 정보 리스트

    Example:
        >>> search_stations_by_name("강남")
        [
            {"station_cd": "0222", "name": "강남", "line": "2호선"},
            {"station_cd": "0357", "name": "강남구청", "line": "7호선"},
            ...
        ]
    """
    keyword = keyword.strip()

    query = """
    SELECT DISTINCT station_cd, name, line
    FROM subway_station
    WHERE TRIM(name) LIKE %(pattern)s
    ORDER BY 
        CASE 
            WHEN TRIM(name) = %(keyword)s THEN 1
            WHEN TRIM(name) LIKE %(keyword_prefix)s THEN 2
            ELSE 3
        END,
        LENGTH(name) ASC,
        name ASC
    LIMIT %(limit)s
    """

    with get_db_cursor() as cursor:
        cursor.execute(
            query,
            {
                "pattern": f"%{keyword}%",
                "keyword": keyword,
                "keyword_prefix": f"{keyword}%",
                "limit": limit,
            },
        )
        return cursor.fetchall()
