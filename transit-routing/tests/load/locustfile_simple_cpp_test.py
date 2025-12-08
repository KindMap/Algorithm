"""
C++ 엔진 성능 테스트용 간단한 Locustfile

- 인증 없음 (로그인 제거)
- 경로 계산 성능만 집중 테스트
- 동시 사용자 50명 목표
"""

from locust import HttpUser, task, between, LoadTestShape
import random


class SimpleCppEngineTest(HttpUser):
    # 로컬 테스트 서버
    host = "http://localhost:8001"
    
    # 요청 간 대기 시간 1~2초
    wait_time = between(1, 2)

    # 장애 유형
    disability_types = ["PHY", "VIS", "AUD", "ELD"]

    # 테스트용 역 목록 (서울 지하철 주요 역)
    stations = [
        "강남", "서울역", "홍대입구", "잠실",
        "신도림", "고속터미널", "삼성", "선릉",
        "사당", "광화문", "신림", "구로디지털단지",
    ]

    @task(1)
    def health_check(self):
        """헬스체크 (가벼운 요청)"""
        with self.client.get("/health", catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Health check failed: {response.status_code}")

    @task(10)
    def calculate_route(self):
        """경로 계산 (C++ 엔진 성능 테스트)"""
        # 랜덤으로 출발지, 목적지 선택 (중복 방지)
        origin, destination = random.sample(self.stations, 2)
        
        # 랜덤 장애 유형
        disability_type = random.choice(self.disability_types)
        
        payload = {
            "origin": origin,
            "destination": destination,
            "departure_time": "2024-12-10 09:00:00",
            "disability_type": disability_type,
        }
        
        with self.client.post(
            "/api/v1/navigation/calculate",
            json=payload,
            name="/api/v1/navigation/calculate",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                # 응답 시간 측정
                elapsed_ms = response.elapsed.total_seconds() * 1000
                
                try:
                    result = response.json()
                    
                    # 성공 기준
                    if "routes" in result and len(result["routes"]) > 0:
                        # C++ 엔진 목표: < 500ms
                        if elapsed_ms > 500:
                            response.failure(
                                f"Slow request: {elapsed_ms:.2f}ms "
                                f"({origin} → {destination})"
                            )
                        else:
                            response.success()
                    else:
                        response.failure(f"No routes found ({origin} → {destination})")
                        
                except Exception as e:
                    response.failure(f"Response parse error: {e}")
            else:
                response.failure(
                    f"Request failed: {response.status_code} - {response.text[:100]}"
                )

    @task(2)
    def get_api_info(self):
        """API 정보 조회 (C++ 엔진 확인)"""
        with self.client.get("/api/v1/info", catch_response=True) as response:
            if response.status_code == 200:
                try:
                    info = response.json()
                    engine = info.get("engine", {})
                    
                    # C++ 엔진 사용 확인
                    if engine.get("cpp_enabled") and engine.get("engine_type") == "cpp":
                        response.success()
                    else:
                        response.failure(
                            f"C++ engine not active! Engine: {engine}"
                        )
                except Exception as e:
                    response.failure(f"Parse error: {e}")
            else:
                response.failure(f"Info check failed: {response.status_code}")


class SimpleLoadShape(LoadTestShape):
    """
    간단한 부하 테스트 시나리오
    
    1단계: 10명 (1분)
    2단계: 25명 (2분)
    3단계: 50명 (3분)
    4단계: 50명 유지 (총 5분)
    """
    
    stages = [
        {"duration": 60, "users": 10, "spawn_rate": 2},    # 10명까지 증가
        {"duration": 120, "users": 25, "spawn_rate": 3},   # 25명까지 증가
        {"duration": 180, "users": 50, "spawn_rate": 5},   # 50명까지 증가
        {"duration": 300, "users": 50, "spawn_rate": 5},   # 50명 유지 (2분)
    ]
    
    def tick(self):
        run_time = self.get_run_time()
        
        for stage in self.stages:
            if run_time < stage["duration"]:
                return (stage["users"], stage["spawn_rate"])
        
        return None


# CLI 실행 예시:
# locust -f locustfile_simple_cpp_test.py --host=http://localhost:8001
#
# 또는 헤드리스 모드:
# locust -f locustfile_simple_cpp_test.py \
#   --host=http://localhost:8001 \
#   --users 50 \
#   --spawn-rate 5 \
#   --run-time 5m \
#   --headless \
#   --html report.html
