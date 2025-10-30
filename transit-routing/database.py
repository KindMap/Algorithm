import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from typing import List, Dict, Optional
from distance_calculator import DistanceCalculator
from contextlib import contextmanager
import logging
from config import DB_CONFIG
import time

logger = logging.getLogger(__name__)

# 모듈 레벨에서 한 번만 생성 -> 싱글톤 패턴 사용 안함
_connection_pool = None

# 거리 계산용 distace_calculator 인스턴스
_distance_calculator = None


def get_distance_calculator() -> DistanceCalculator:
    """(lazy initialization) DistanceCalculator 인스턴스 return"""
    global _distance_calculator
    if _distance_calculator is None:
        _distance_calculator = DistanceCalculator(cache_file="distance_cache.pkl")
    return _distance_calculator


def initialize_pool():
    """application 시작 시 한 번만 호출"""
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = pool.ThreadedConnectionPool(
            minconn=10, maxconn=50, **DB_CONFIG  # RDS db.t3.micro: 최대 연결 87개
        )
        logger.info("RDS Database connection pool 초기화")


def close_pool():
    """application 종료 시 호출"""
    global _connection_pool
    if _connection_pool:
        _connection_pool.closeall()
        logger.info("RDS Database connection pool 종료")


@contextmanager
def get_db_connection():
    """connection 가져오기"""
    if _connection_pool is None:
        raise RuntimeError(
            "Connection pool이 초기화되지 않았습니다. 초기화 함수를 먼저 호출하시오."
        )

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
    """Cursor 가져오기"""
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


# 정보 조회 쿼리 함수들


def get_all_stations(line: Optional[str] = None) -> List[Dict]:
    """해당 호선의 모든 역 정보 조회 order by station_id"""
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
    """station_cd로 단일 역 정보 조회"""
    query = """
    SELECT station_id, line, name, lat,lng, station_cd
    FROM subway_station
    WHERE station_cd = %(station_cd)s
    """

    with get_db_cursor() as cursor:
        cursor.execute(query, {"station_cd": station_cd})
        return cursor.fetchone()


def get_stations_by_codes(station_cds: List[str]) -> List[Dict]:
    """station_cd 사용하여 여러 역 배치 조회 => 경로 표시용"""
    query = """
    SELECT station_id, line, name, lat, lng, station_cd
    FROM subway_station
    WHERE station_cd = ANY(%(station_cd)s)
    ORDER BY array_position(%(station_cd)s, station_cd)
    """

    with get_db_cursor() as cursor:
        cursor.execute(query, {"station_cds": station_cds})
        return cursor.fetchall()


def get_all_sections(line: Optional[str] = None) -> List[Dict]:
    """모든 구간 정보 조회"""
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
    """모든 환승역 편의성 점수 조회"""
    query = """
    SELECT * FROM transfer_station_convenience
    ORDER BY station_cd
    """

    with get_db_cursor() as cursor:
        cursor.execute(query)
        return cursor.fetchall()


def get_transfer_conv_score_by_code(station_cd: str) -> Optional[Dict]:
    """station_cd로 특정 역의 환승 편의도 조회"""
    query = """
    SELECT * FORM transfer_station_convenience
    WHERE station_cd = %(station_cd)s
    """

    with get_db_cursor() as cursor:
        cursor.execute(query, {"station_cd": station_cd})
        return cursor.fetchone()


# 경로 거리 계산
def calculate_route_distance(route_station_cds: List[str]) -> Dict:
    """
    경로의 총 이동 거리 계산 (Python haversine 사용)

    Args:
        route_station_cds: 경로 상의 역 코드 리스트 (순서대로)

    Returns:
        총 거리, 구간별 거리, 계산 방법 등

    Example:
        >>> calculate_route_distance(['ST001', 'ST002', 'ST003'])
        {
            'total_distance_m': 2450.5,
            'total_distance_km': 2.45,
            'segment_distances': [
                {'from': 'ST001', 'to': 'ST002', 'distance_m': 1200.3},
                {'from': 'ST002', 'to': 'ST003', 'distance_m': 1250.2}
            ],
            'station_count': 3,
            'segment_count': 2,
            'calculation_method': 'haversine'
        }
    """
    if not route_station_cds or len(route_station_cds) < 2:
        return {  # 지하철 전용 경로
            "total_distance_m": 0.0,
            "total_distance_km": 0.0,
            "segment_distances": [],
            "station_count": len(route_station_cds),
            "segment_count": 0,
            "error": "At least 2 stations required",
        }

    # 1. DB에서 역 좌표 조회
    query = """
        SELECT 
            station_cd,
            name as station_name,
            lat,
            lng,
            array_position(%(station_cds)s, station_cd) as route_order
        FROM subway_station
        WHERE station_cd = ANY(%(station_cds)s)
        ORDER BY route_order
    """

    with get_db_cursor() as cursor:
        cursor.execute(query, {"station_cds": route_station_cds})
        stations = cursor.fetchall()

    # 2. 조회된 역이 요청한 수와 일치하는지 확인
    if len(stations) != len(route_station_cds):
        missing = set(route_station_cds) - {s["station_cd"] for s in stations}
        logger.warning(f"Missing stations: {missing}")
        return {
            "total_distance_m": 0.0,
            "total_distance_km": 0.0,
            "segment_distances": [],
            "station_count": len(stations),
            "segment_count": 0,
            "error": f"Stations not found: {missing}",
        }

    # 3. DistanceCalculator로 구간별 거리 계산
    calculator = get_distance_calculator()
    segment_distances = []
    total_distance = 0.0

    for i in range(len(stations) - 1):
        station1 = stations[i]
        station2 = stations[i + 1]

        coord1 = (station1["lat"], station1["lng"])
        coord2 = (station2["lat"], station2["lng"])

        distance = calculator.haversine(coord1, coord2)

        segment_distances.append(
            {
                "from_cd": station1["station_cd"],
                "from_name": station1["station_name"],
                "to_cd": station2["station_cd"],
                "to_name": station2["station_name"],
                "distance_m": round(distance, 2),
                "distance_km": round(distance / 1000, 2),
            }
        )

        total_distance += distance

    # 4. 캐시 저장 -> 성능 최적화
    calculator.save_cache()

    return {
        "total_distance_m": round(total_distance, 2),
        "total_distance_km": round(total_distance / 1000, 2),
        "segment_distances": segment_distances,
        "station_count": len(stations),
        "segment_count": len(segment_distances),
        "calculation_method": "haversine",
        "cache_used": True,
    }


# PostGIS 지원 필요 함수
# 주변 역 검사
def get_nearby_stations(lat: float, lon: float, radius_km: float = 1.0) -> List[Dict]:
    """주변 역 반경 rasius_km: 1.0, limit: 20"""
    query = """
        SELECT 
            station_cd,
            name as station_name,
            line,
            lat,
            lng,
            ST_Distance(
                ST_SetSRID(ST_MakePoint(lng, lat), 4326)::geography,
                ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography
            ) / 1000 as distance_km
        FROM subway_station
        WHERE ST_DWithin(
            ST_SetSRID(ST_MakePoint(lng, lat), 4326)::geography,
            ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography,
            %(radius_m)s
        )
        ORDER BY distance_km
        LIMIT 20
    """

    with get_db_cursor() as cursor:
        cursor.execute(query, {"lat": lat, "lon": lon, "radius_m": radius_km * 1000})
        return cursor.fetchall()
