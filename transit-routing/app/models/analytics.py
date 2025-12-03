from pydantic import BaseModel
from typing import List, Dict


# 단일 통계 항목
class StatItem(BaseModel):
    label: str
    count: int  # => UI 표시용 int 변환


# 시간대별 트래픽 항목
class HourlyItem(BaseModel):
    hour: int
    count: int


# 전체 대시보드 응답 구조
class DashboardResponse(BaseModel):
    top_origins: List[StatItem]
    top_destinations: List[StatItem]
    top_od_pairs: List[StatItem]
    top_transfer_stations: List[StatItem]
    hourly_traffic: List[HourlyItem]
