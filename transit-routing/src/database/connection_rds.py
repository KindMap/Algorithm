"""
rds 연결 관리 모듈
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv

# 환경 변수 로드
load_dotenv()

def create_database_engine():
    """
    database engine 생성
    
    returns:
        SQLAlchemy Engine 객체
    raises:
        ValueError: 환경변수가 설정되지 않은 경우 -> 추후 추가
    """

    db_host = os.getenv('DB_HOST')
    db_port = os.getenv('DB_PORT')
    db_name = os.getenv('DB_NAME')
    db_user = os.getenv('DB_USER')
    db_password = os.getenv('DB_PASSWORD')

    # 추후 환경 변수 검증 추가하기
    # if not all([db_host, ...])

    # PostgreSQL 연결 URL 생성
    connection_url = {
        f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    }
    
    # 엔진 생성(연결 풀 포함)
    engine = create_engine(
        connection_url,
        pool_size=5,
        max_overflow=10, # 최대 추가 연결 수
        pool_recycle=3600,
        pool_pre_ping=True, # 연결 유효성 자동검사
        echo=True # SQL 로그 출력 여부 -> 개발 : True
    )
    
    return engine

# 모듈 수준에서 엔진을 생성 => 애플리케이션 전체에서 공유
engine = create_database_engine()

# 세션 팩토리 생성
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False
)
# 추후 auto flush -> True로 변경하기

def get_db_session() -> Session:
    """
    database 세션 반환

    Returns:
        SQLAlchemy Session 객체
    """
    return SessionLocal()

def close_database_connection():
    """
    database 연결 종료 -> 애플리케이션 종료 시 호출하기
    """
    engine.dispose()