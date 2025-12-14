from locust import HttpUser, task, between, LoadTestShape
import time
import random

# [t3.medium 최적화 버전]
# 목표: 최대 60명의 동시 사용자 (약 15~20 RPS 유발)
# 하드웨어 스펙(2 vCPU, 4GB RAM)을 고려하여 안정적인 성능 지표를 얻는 것이 목적


class Scenario(HttpUser):
    host = "https://kindmap-for-you.cloud"

    # [수정 1] 대기 시간을 현실적으로 늘림 (2초 ~ 5초)
    # 사용자가 경로 결과를 보고 생각하는 시간을 시뮬레이션
    wait_time = between(2, 5)

    disability_types = ["PHY", "VIS", "AUD", "ELD"]

    test_accounts = [
        {"email": "test123@test.com", "password": "password"},
        {"email": "test789@test.com", "password": "password2"},
        {"email": "test147@test.com", "password": "password3"},
        {"email": "test258@test.com", "password": "password4"},
        {"email": "test369@test.com", "password": "password5"},
    ]

    stations = [
        "잠실",
        "홍대입구",
        "강남",
        "구로디지털단지",
        "서울",
        "신림",
        "삼성",
        "고속터미널",
        "신도림",
        "선릉",
        "사당",
        "가산디지털단지",
        "구반포",
        "청구",
        "숙대입구",
        "충무로",
        "광화문",
        "남성",
    ]

    def on_start(self):
        user_account = random.choice(self.test_accounts)

        # 타임아웃을 명시적으로 설정하여 오랫동안 매달려있는 연결 방지
        try:
            response = self.client.post(
                "/api/v1/auth/login",
                data={
                    "username": user_account["email"],
                    "password": user_account["password"],
                },
                name="/api/v1/auth/login",
                timeout=10,  # 10초 타임아웃
            )

            if response.status_code != 200:
                # 로그인 실패는 치명적이므로 로그 출력
                print(f"Login Error: {response.status_code}")
                self.stop()
        except Exception as e:
            print(f"Login Timeout/Error: {e}")
            self.stop()

    @task
    def find_path_scenario(self):
        selected_type = random.choice(self.disability_types)
        origin, destination = random.sample(self.stations, 2)

        payload = {
            "origin": origin,
            "destination": destination,
            "disability_type": selected_type,
        }

        # 경로 탐색 요청
        # C++ 엔진 연산 시간을 고려하여 타임아웃을 60초로 넉넉하게 설정
        # (실제 서비스에서는 60초 넘으면 사용자 이탈로 간주)
        with self.client.post(
            "/api/v1/navigation/calculate",
            json=payload,
            name="/api/v1/navigation/calculate",
            catch_response=True,
            timeout=60,
        ) as response:
            if response.status_code != 200:
                response.failure(f"Status code: {response.status_code}")
            else:
                try:
                    result = response.json()
                    if "routes" not in result:
                        response.failure("Missing 'routes' in response")
                except Exception as e:
                    response.failure(f"JSON Parse Error: {e}")


class StepLoadShape(LoadTestShape):
    """
    t3.medium 인스턴스 부하 테스트 시나리오
    목표: 점진적으로 부하를 높여 '안정 구간'과 '임계점(Latency 급증 구간)'을 찾는다.
    """

    stages = [
        # 1단계: 웜업 (Warm-up)
        # 10명까지 1분 동안 천천히 진입. 시스템 캐시(Redis, C++ 메모리) 예열
        {"duration": 60, "users": 10, "spawn_rate": 0.5},
        # 2단계: 정상 부하 (Normal Load)
        # 30명 도달. (약 8~10 RPS).
        # t3.medium에서 CPU 40~60% 구간 예상
        {"duration": 180, "users": 30, "spawn_rate": 1},
        # 3단계: 고부하 (Heavy Load)
        # 50명 도달. (약 15~17 RPS).
        # CPU 80% 이상, Latency가 튀기 시작하는지 관찰
        {"duration": 300, "users": 50, "spawn_rate": 1},
        # 4단계: 스트레스 (Stress) - 최대치 도전
        # 60명 도달. 시스템이 버티는지 확인 (짧게 유지)
        {"duration": 420, "users": 60, "spawn_rate": 1},
        # 5단계: 유지 (Sustain)
        # 60명 상태로 3분간 유지하며 메모리 누수나 에러율 확인
        {"duration": 600, "users": 60, "spawn_rate": 1},
    ]

    def tick(self):
        run_time = self.get_run_time()

        for stage in self.stages:
            if run_time < stage["duration"]:
                tick_data = (stage["users"], stage["spawn_rate"])
                return tick_data

        return None
