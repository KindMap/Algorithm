import psycopg2
from psycopg2.extras import RealDictCursor
from typing import List, Dict, Any
from config import DB_CONFIG
import time


class DatabaseConnection:
    def __init__(self):
        self.connection = None
        self.cursor = None

    def connect(self, max_retries=3):
        for attempt in range(max_retries):
            try:
                self.connection = psycopg2.connect(**DB_CONFIG)
                self.cursor = self.connection.cursor(cursor_factory=RealDictCursor)
                print(f"RDS connected")
                return
            except psycopg2.OperationalError as e:
                if attempt < max_retries - 1:
                    time.sleep(10)  # 개발 환경: 10초 정도 넉넉하게 설정
                    continue
                raise e

    def close(self):
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()

    def get_all_stations(self) -> List[Dict]:
        """모든 역 정보 조회"""
        query = """
        SELECT station_id, line, name, lat, lng, station_cd
        FROM subway_station
        """
        self.cursor.execute(query)
        return self.cursor.fetchall()

    def get_all_sections(self) -> List[Dict]:
        """모든 구간 정보 조회"""
        query = """
        SELECT section_id, line, up_stream_name, down_station_name,
                section_order, via_coordinamtes
        FROM subway_section
        """
        self.cursor.execute(query)
        return self.cursor.fetchall()

    def get_all_transfer_station_conveniences(self) -> List[Dict]:
        """모든 환승역 편의성 점수 조회"""
        query = """
        SELECT * FROM transfer_station_convenience
        """
        self.cursor.execute(query)
