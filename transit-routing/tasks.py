from celery_app import celery
from database import get_db_connection
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


@celery.task(bind=True, max_retries=3)
def save_location_history(self, user_id, lat, lon, accuracy, route_id):
    """
    사용자 위치 이력 저장 (비동기)

    Args:
        user_id: 사용자 ID (WebSocket session ID)
        lat: 위도
        lon: 경도
        accuracy: GPS 정확도 (미터)
        route_id: 경로 ID
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO user_location_history 
            (user_id, latitude, longitude, accuracy, route_id, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s)
        """,
            (user_id, lat, lon, accuracy, route_id, datetime.now()),
        )

        conn.commit()
        cursor.close()
        conn.close()

        logger.info(f"Location saved for user {user_id}: ({lat}, {lon})")

    except Exception as e:
        logger.error(f"Failed to save location for user {user_id}: {e}")
        # 재시도 (최대 3번, 60초 후)
        raise self.retry(exc=e, countdown=60)


@celery.task
def batch_save_locations(location_batch):
    """
    위치 데이터 일괄 저장

    Args:
        location_batch: List of tuples [(user_id, lat, lon, accuracy, route_id, timestamp), ...]
    """
    if not location_batch:
        logger.warning("Empty location batch received")
        return

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.executemany(
            """
            INSERT INTO user_location_history 
            (user_id, latitude, longitude, accuracy, route_id, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s)
        """,
            location_batch,
        )

        conn.commit()
        cursor.close()
        conn.close()

        logger.info(f"Batch saved {len(location_batch)} location records")

    except Exception as e:
        logger.error(f"Batch save failed: {e}")
        raise


@celery.task(bind=True, max_retries=3)
def save_navigation_event(self, user_id, event_type, event_data, route_id):
    """
    내비게이션 이벤트 저장 (환승, 도착, 경로 이탈 등)

    Args:
        user_id: 사용자 ID
        event_type: 이벤트 타입 ('transfer', 'arrival', 'deviation', 'recalculate')
        event_data: 이벤트 상세 데이터 (JSON)
        route_id: 경로 ID
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO navigation_events 
            (user_id, event_type, event_data, route_id, timestamp)
            VALUES (%s, %s, %s, %s, %s)
        """,
            (user_id, event_type, str(event_data), route_id, datetime.now()),
        )

        conn.commit()
        cursor.close()
        conn.close()

        logger.info(f"Navigation event saved: {event_type} for user {user_id}")

    except Exception as e:
        logger.error(f"Failed to save navigation event: {e}")
        raise self.retry(exc=e, countdown=60)


@celery.task
def cleanup_old_sessions():
    """
    오래된 위치 이력 데이터 정리 (주기적 실행)
    30일 이상 된 데이터 삭제
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            DELETE FROM user_location_history 
            WHERE timestamp < NOW() - INTERVAL '30 days'
        """
        )

        deleted_count = cursor.rowcount
        conn.commit()
        cursor.close()
        conn.close()

        logger.info(f"Cleaned up {deleted_count} old location records")
        return deleted_count

    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        raise


@celery.task
def analyze_route_usage(route_id):
    """
    경로 사용 통계 분석 (비동기)

    Args:
        route_id: 경로 ID
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 해당 경로의 완료율, 평균 소요 시간 등 계산
        cursor.execute(
            """
            SELECT 
                COUNT(DISTINCT user_id) as total_users,
                COUNT(*) FILTER (WHERE event_type = 'arrival') as completed,
                COUNT(*) FILTER (WHERE event_type = 'deviation') as deviations
            FROM navigation_events
            WHERE route_id = %s
        """,
            (route_id,),
        )

        stats = cursor.fetchone()
        cursor.close()
        conn.close()

        logger.info(f"Route {route_id} stats: {stats}")
        return stats

    except Exception as e:
        logger.error(f"Route analysis failed: {e}")
        raise
