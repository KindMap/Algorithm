import math
from typing import Dict, Tuple, List
import pickle
import os


class DistanceCalculator:
    EARTH_RADIUS = 6371000  # meters

    def __init__(self, cache_file="distance_cache.pkl"):
        self.cache_file = cache_file
        self.cache = self._load_cache()

    def _load_cache(self) -> Dict:
        """load cache file"""
        if os.path.exists(self.cache_file):
            with open(self.cache_file, "rb") as f:
                return pickle.load(f)
        return {}

    def save_cache(self):
        """save cache"""
        with open(self.cache_file, "wb") as f:
            pickle.dump(self.cache, f)

    def calculate_distance(
        self, lat1: float, lon1: float, lat2: float, lon2: float
    ) -> float:
        """두 좌표 간 거리 계산(meter)"""
        return self.haversine((lat1, lon1), (lat2, lon2))

    def haversine(
        self, coord1: Tuple[float, float], coord2: Tuple[float, float]
    ) -> float:
        """하버사인 공식으로 지구의 곡률 고려하여 두 좌표 간 거리 계산"""
        lat1, lon1 = coord1
        lat2, lon2 = coord2

        # create cache key
        cache_key = (lat1, lon1, lat2, lon2)
        if cache_key in self.cache:
            return self.cache[cache_key]

        # radian convertion
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])

        # haversine formula
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.asin(math.sqrt(a))
        distance = self.EARTH_RADIUS * c

        # save cache
        self.cache[cache_key] = distance

        return distance

    def precompute_station_distances(self, stations: List[Dict]):
        """모든 역 간 거리 사전 계산"""
        for i, station1 in enumerate(stations):
            coord1 = (station1["lat"], station1["lng"])
            for station2 in stations[i + 1 :]:
                coord2 = (station2["lat"], station2["lng"])
                self.haversine(coord1, coord2)

        self.save_cache()
