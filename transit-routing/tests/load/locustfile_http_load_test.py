from locust import HttpUser, task, between, LoadTestShape
import time
import random

# test scenario
# => login 후 경로 찾기 (4가지 타입 중 랜덤, 출발지-목적지는 경로 유형 4가지 중 랜덤)
# 동시 사용자 수 50 -> 100 -> 150 -> 200 -> 250 -> 300 (유지) 점진적으로 증가시키며 모니터링


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
        "잠실",
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
        """
        test 시작 시 최초 1회 실행되는 메서드
        login 수행 -> 세션 획득
        """

        user_account = random.choice(self.test_accounts)

        # OAuth2PasswordRequestForm 형식 (application/x-www-form-urlencoded) 사용
        response = self.client.post(
            "/api/v1/auth/login",
            data={  # json이 아닌 data 사용
                "username": user_account["email"],
                "password": user_account["password"],
            },
            name="/api/v1/auth/login",
        )

        if response.status_code != 200:
            print(
                f"Login failed for {user_account['email']}: "
                f"{response.status_code} - {response.text}"
            )
            self.stop()
            return

        # 로그인 성공 시 토큰 저장 (필요시 사용)
        try:
            token_data = response.json()
            self.access_token = token_data.get("access_token")
        except Exception as e:
            print(f"Failed to parse login response: {e}")
            self.stop()

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

        # 경로 찾기 API 호출 - 올바른 엔드포인트: /api/v1/navigation/calculate
        response = self.client.post(
            "/api/v1/navigation/calculate",
            json=payload,
            name="/api/v1/navigation/calculate",
        )

        # 응답 검증
        if response.status_code != 200:
            print(
                f"Path calculation failed ({origin} -> {destination}): "
                f"{response.status_code} - {response.text}"
            )
        else:
            # 성공 시 응답 데이터 확인 (디버깅용)
            try:
                result = response.json()
                # 경로가 제대로 계산되었는지 간단히 확인
                if "routes" not in result:
                    print(
                        f"Warning: Unexpected response format for "
                        f"{origin} -> {destination}"
                    )
            except Exception as e:
                print(f"Failed to parse response: {e}")


class StepLoadShape(LoadTestShape):
    """
    300명까지 점진적 부하 증가 (Step Load)
    패턴: 50 -> 100 -> 150 -> 200 -> 250 -> 300 (유지)
    """

    stages = [
        # 1단계: 1분 동안 50명까지 증가 (초당 2명씩 투입)
        {"duration": 60, "users": 50, "spawn_rate": 2},
        # 2단계: 2분 시점까지 100명으로 증가
        {"duration": 120, "users": 100, "spawn_rate": 5},
        # 3단계: 3분 시점까지 150명으로 증가
        {"duration": 180, "users": 150, "spawn_rate": 5},
        # 4단계: 4분 시점까지 200명으로 증가
        {"duration": 240, "users": 200, "spawn_rate": 10},
        # 5단계: 5분 시점까지 250명으로 증가 (가속 구간)
        {"duration": 300, "users": 250, "spawn_rate": 10},
        # 6단계: 6분 시점까지 300명 도달
        {"duration": 360, "users": 300, "spawn_rate": 10},
        # 7단계: [중요] 300명 상태로 4분간 유지 (총 10분 테스트)
        # 이 구간에서 시스템이 300명을 버티는지 확인합니다.
        {"duration": 600, "users": 300, "spawn_rate": 10},
    ]

    def tick(self):
        run_time = self.get_run_time()

        for stage in self.stages:
            if run_time < stage["duration"]:
                tick_data = (stage["users"], stage["spawn_rate"])
                return tick_data

        return None
