import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from typing import List, Dict, Optional
from contextlib import contextmanager
import logging
from config import DB_CONFIG
import time

logger = logging.getLogger(__name__)

# 모듈 레벨에서 한 번만 생성 -> 싱글톤 패턴 사용 안함
_connection_pool = None


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
    with get_db_connection as connection:
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
