from typing import List, Optional
from dataclasses import dataclass

# domain 정의

@dataclass
class Station:
    station_cd: str # 내부 연산은 station_cd로 통일
    name: str # station_name아님!!!
    line: str # line_num아님!!!
    lat: float
    lng: float
    station_id: Optional[str] = None


@dataclass
class RouteInfo:
    route_id: str
    origin_cd: str
    destination_cd: str
    route_sequence: List[str]
    route_lines: List[str]
    total_time: float
    transfers: int
    transfer_stations: List[str]