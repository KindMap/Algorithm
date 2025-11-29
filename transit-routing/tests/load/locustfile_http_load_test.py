from locust import HttpUser, task, between, LoadTestShape
import time
import random

# test scenario
# => login 후 경로 찾기 (4가지 타입 중 랜덤, 출발지-목적지는 경로 유형 4가지 중 랜덤)
# 동시 사용자 수 10 -> 25 -> 50 -> 75 -> 100 점진적으로 증가시키며 모니터링


class Scenario(HttpUser):
    # 테스트를 실행할 서버 명시
    host = "https://kindmap-for-you.cloud"
    # 작업 간 대기 시간 1~3초 랜덤 설정
    wait_time = between(1, 3)

    disability_types = ["PHY", "VIS", "AUD", "ELD"]

    # test용 계정 5개 정의
    test_accounts = [
        {"email": "test123@test.com", "password": "password"},
        {"email": "test789@test.com", "password": "password2"},
        {"email": "test147@test.com", "password": "password3"},
        {"email": "test258@test.com", "password": "password4"},
        {"email": "test369@test.com", "password": "password5"},
    ]

    # 테스트할 경로를 다양화 하기 위해 서울 지하철 기준 일평균 승하차 인원 상위 10개 역을 저장
    # 출발역, 목적지를 랜덤하게 선택
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
    ]

    def on_start(self):
        """
        test 시작 시 최초 1회 실행되는 메서드
        login 수행 -> 세션 획득
        """

        user_account = random.choice(self.test_accounts)

        response = self.client.post(
            "/api/v1/auth/login",
            json={
                "username": user_account["email"],
                "password": user_account["password"],
            },
        )

        if response.status_code != 200:
            print(f"Login failed: {response.status_code} - {response.text}")
            self.stop()
            # runner.quit() 대신 해당 유저 정지로 수정

    @task
    def find_path_scenario(self):
        """
        로그인 이후 경로 찾기 반복적으로 수행
        """

        # disability_types 중 랜덤으로 지정
        selected_type = random.choice(self.disability_types)

        # random.sample -> 중복되지 않게 리스트에서 원소 n개 선택
        # 출발지 == 목적지 => 방지
        origin, destination = random.sample(self.stations, 2)

        payload = {
            "origin": origin,
            "destination": destination,
            "disability_type": selected_type,
        }

        # 경로 찾기 API 호출
        self.client.post("/api/calculate", json=payload, name="/api/calculate")


class StepLoadShape(LoadTestShape):
    """
    시간에 따라 사용자 수를 단계적으로 제어하는 클래스입니다.
    목표: 10 -> 25 -> 50 -> 75 -> 100명
    """

    # 각 단계 설정: (지속시간_초, 목표_유저_수, 초당_생성_수)
    stages = [
        {"duration": 60, "users": 10, "spawn_rate": 5},  # 1분까지 10명 유지
        {
            "duration": 120,
            "users": 25,
            "spawn_rate": 5,
        },  # 2분까지 25명으로 증가 후 유지
        {
            "duration": 180,
            "users": 50,
            "spawn_rate": 10,
        },  # 3분까지 50명으로 증가 후 유지
        {
            "duration": 240,
            "users": 75,
            "spawn_rate": 10,
        },  # 4분까지 75명으로 증가 후 유지
        {
            "duration": 300,
            "users": 100,
            "spawn_rate": 10,
        },  # 5분까지 100명으로 증가 후 유지
    ]

    def tick(self):
        run_time = self.get_run_time()

        for stage in self.stages:
            if run_time < stage["duration"]:
                tick_data = (stage["users"], stage["spawn_rate"])
                return tick_data

        return None  # 모든 단계가 끝나면 테스트 종료
