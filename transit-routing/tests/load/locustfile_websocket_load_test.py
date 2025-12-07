from locust import User, task, between, LoadTestShape, events
from websocket import create_connection, WebSocketTimeoutException
import time
import random
import json
import uuid
import requests
import logging

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class WebSocketClient:
    """
    Locust와 통합된 WebSocket 클라이언트
    WebSocket 연결 관리 및 메트릭 기록
    """

    def __init__(self, host, user_id, token):
        self.host = host
        self.user_id = user_id
        self.token = token
        self.ws = None
        self.connected = False

    def connect(self):
        """WebSocket 연결 및 메트릭 기록"""
        start_time = time.time()
        try:
            # wss:// 프로토콜 사용
            ws_url = f"{self.host}/api/v1/ws/{self.user_id}?token={self.token}"
            self.ws = create_connection(
                ws_url, timeout=10, enable_multithread=True, skip_utf8_validation=True
            )
            self.connected = True
            duration = (time.time() - start_time) * 1000

            # Locust 메트릭 기록
            events.request.fire(
                request_type="WebSocket",
                name="ws_connect",
                response_time=duration,
                response_length=0,
                exception=None,
            )

            logger.debug(f"WebSocket 연결 성공: {self.user_id} ({duration:.2f}ms)")
            return True

        except Exception as e:
            duration = (time.time() - start_time) * 1000
            events.request.fire(
                request_type="WebSocket",
                name="ws_connect",
                response_time=duration,
                response_length=0,
                exception=e,
            )
            logger.error(f"WebSocket 연결 실패: {self.user_id} - {e}")
            return False

    def send_and_receive(self, message, timeout=5):
        """
        메시지 전송 및 응답 대기

        Args:
            message: 전송할 메시지 (dict)
            timeout: 응답 대기 시간 (초)

        Returns:
            응답 메시지 (dict) 또는 None
        """
        if not self.connected or not self.ws:
            logger.warning(f"WebSocket 미연결 상태: {self.user_id}")
            return None

        start_time = time.time()
        message_type = message.get("type", "unknown")

        try:
            # 메시지 전송
            self.ws.send(json.dumps(message))

            # 응답 수신 (타임아웃 설정)
            self.ws.settimeout(timeout)
            response = self.ws.recv()
            duration = (time.time() - start_time) * 1000

            # Locust 메트릭 기록 (성공)
            events.request.fire(
                request_type="WebSocket",
                name=f"ws_{message_type}",
                response_time=duration,
                response_length=len(response),
                exception=None,
            )

            logger.debug(
                f"메시지 성공: {message_type} for {self.user_id} ({duration:.2f}ms)"
            )
            return json.loads(response)

        except WebSocketTimeoutException:
            duration = (time.time() - start_time) * 1000
            exception = Exception(f"WebSocket timeout ({timeout}s)")
            events.request.fire(
                request_type="WebSocket",
                name=f"ws_{message_type}",
                response_time=duration,
                response_length=0,
                exception=exception,
            )
            logger.warning(f"메시지 타임아웃: {message_type} for {self.user_id}")
            return None

        except Exception as e:
            duration = (time.time() - start_time) * 1000
            events.request.fire(
                request_type="WebSocket",
                name=f"ws_{message_type}",
                response_time=duration,
                response_length=0,
                exception=e,
            )
            logger.error(f"메시지 실패: {message_type} for {self.user_id} - {e}")
            return None

    def close(self):
        """WebSocket 연결 종료"""
        if self.ws:
            try:
                self.ws.close()
                self.connected = False
                logger.debug(f"WebSocket 연결 종료: {self.user_id}")
            except Exception as e:
                logger.error(f"WebSocket 종료 실패: {self.user_id} - {e}")


class WebSocketNavigationUser(User):
    """
    WebSocket 네비게이션 사용자 시뮬레이션

    실제 사용자의 행동을 모방:
    1. JWT 토큰 획득 (HTTP 로그인)
    2. WebSocket 연결
    3. 경로 계산 (start_navigation)
    4. 주기적 위치 업데이트 (location_update)
    """

    # GPS 업데이트 간격 시뮬레이션 (3-5초)
    wait_time = between(3, 5)

    # 기존 HTTP 테스트와 동일한 계정 사용
    test_accounts = [
        {"email": "test123@test.com", "password": "password"},
        {"email": "test789@test.com", "password": "password2"},
        {"email": "test147@test.com", "password": "password3"},
        {"email": "test258@test.com", "password": "password4"},
        {"email": "test369@test.com", "password": "password5"},
    ]

    # 서울 지하철 주요 역 (기존 HTTP 테스트와 동일)
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
    ]

    disability_types = ["PHY", "VIS", "AUD", "ELD"]

    # 역 좌표 매핑 (실제 GPS 좌표)
    station_coords = {
        "강남": {"lat": 37.4979, "lon": 127.0276},
        "홍대입구": {"lat": 37.5579, "lon": 126.9227},
        "잠실": {"lat": 37.5133, "lon": 127.1000},
        "구로디지털단지": {"lat": 37.4850, "lon": 126.9010},
        "서울": {"lat": 37.5547, "lon": 126.9707},
        "신림": {"lat": 37.4843, "lon": 126.9297},
        "삼성": {"lat": 37.5088, "lon": 127.0633},
        "고속터미널": {"lat": 37.5046, "lon": 127.0047},
        "신도림": {"lat": 37.5088, "lon": 126.8913},
        "선릉": {"lat": 37.5045, "lon": 127.0489},
        "사당": {"lat": 37.4765, "lon": 126.9815},
        "가산디지털단지": {"lat": 37.4816, "lon": 126.8826},
    }

    def on_start(self):
        """
        사용자 초기화 (최초 1회 실행)

        1. HTTP로 JWT 토큰 획득
        2. WebSocket 연결
        3. 변수 초기화
        """

        # 1. JWT 토큰 획득 (HTTP POST)
        account = random.choice(self.test_accounts)
        http_host = self.host.replace("wss://", "https://").replace("ws://", "http://")

        try:
            response = requests.post(
                f"{http_host}/api/v1/auth/login",
                data={"username": account["email"], "password": account["password"]},
                timeout=10,
            )

            if response.status_code != 200:
                logger.error(
                    f"로그인 실패: {account['email']} - {response.status_code}"
                )
                self.environment.runner.quit()
                return

            token_data = response.json()
            self.access_token = token_data.get("access_token")

            if not self.access_token:
                logger.error(f"토큰 없음: {account['email']}")
                self.environment.runner.quit()
                return

            logger.info(f"로그인 성공: {account['email']}")

        except Exception as e:
            logger.error(f"로그인 예외: {account['email']} - {e}")
            self.environment.runner.quit()
            return

        # 2. WebSocket 연결
        self.user_id = f"loadtest_{uuid.uuid4()}"
        self.ws_client = WebSocketClient(self.host, self.user_id, self.access_token)

        if not self.ws_client.connect():
            logger.error(f"WebSocket 연결 실패: {self.user_id}")
            self.environment.runner.quit()
            return

        # 3. 변수 초기화
        self.current_route_id = None
        self.origin = None
        self.destination = None
        self.gps_position = None
        self.navigation_active = False

        logger.info(f"사용자 초기화 완료: {self.user_id}")

    @task(1)
    def start_navigation_task(self):
        """
        경로 계산 요청 (무거운 작업)

        - ANP 알고리즘 기반 경로 계산
        - Redis 세션 생성
        - Top 3 경로 반환

        Weight=1: 경로 계산 1회 당 위치 업데이트 10회 (1:10 비율)
        """

        # 출발지와 목적지를 랜덤으로 선택 (중복 방지)
        self.origin, self.destination = random.sample(self.stations, 2)
        disability_type = random.choice(self.disability_types)

        message = {
            "type": "start_navigation",
            "origin": self.origin,
            "destination": self.destination,
            "disability_type": disability_type,
        }

        logger.info(
            f"경로 계산 요청: {self.origin} -> {self.destination} ({disability_type})"
        )

        # 메시지 전송 및 응답 대기 (최대 10초)
        response = self.ws_client.send_and_receive(message, timeout=10)

        if response and response.get("type") == "route_calculated":
            self.current_route_id = response.get("route_id")
            self.navigation_active = True

            # 초기 GPS 위치 설정 (출발지 근처)
            self.gps_position = self._get_station_coords(self.origin)

            routes_count = response.get("routes_returned", 0)
            logger.info(
                f"경로 계산 완료: route_id={self.current_route_id}, {routes_count}개 경로"
            )
        else:
            logger.warning(f"경로 계산 실패 또는 타임아웃: {self.origin} -> {self.destination}")
            self.navigation_active = False

    @task(10)
    def location_update_task(self):
        """
        위치 업데이트 (빈번한 작업)

        - 실시간 GPS 좌표 전송
        - 경로 안내 수신
        - 경로 이탈/도착 감지

        Weight=10: 경로 계산 1회 당 위치 업데이트 10회
        """

        # 경로 계산 전에는 스킵
        if not self.navigation_active or not self.current_route_id or not self.gps_position:
            return

        # GPS 좌표 시뮬레이션 (10-50m 랜덤 이동)
        self.gps_position = self._simulate_movement(self.gps_position)

        message = {
            "type": "location_update",
            "latitude": self.gps_position["lat"],
            "longitude": self.gps_position["lon"],
            "accuracy": random.uniform(10, 50),  # GPS 정확도 (미터)
            "route_id": self.current_route_id,
        }

        # 메시지 전송 및 응답 대기 (최대 3초)
        response = self.ws_client.send_and_receive(message, timeout=3)

        if response:
            response_type = response.get("type")

            # 도착 감지
            if response_type == "arrival":
                logger.info(f"도착 완료: {self.destination} (route_id={self.current_route_id})")
                self.navigation_active = False
                self.current_route_id = None

            # 경로 이탈 감지
            elif response_type == "route_deviation":
                logger.warning(f"경로 이탈 감지: route_id={self.current_route_id}")

            # 정상 안내
            elif response_type == "navigation_update":
                logger.debug(f"위치 업데이트 성공: route_id={self.current_route_id}")

    def _get_station_coords(self, station_name):
        """
        역 이름으로 GPS 좌표 반환

        Args:
            station_name: 역 이름

        Returns:
            {"lat": float, "lon": float}
        """
        # 매핑에 없는 역은 서울역 좌표 반환 (기본값)
        return self.station_coords.get(
            station_name, {"lat": 37.5665, "lon": 126.9780}
        )

    def _simulate_movement(self, current_pos):
        """
        GPS 이동 시뮬레이션

        10-50m 랜덤 이동 (현실적인 보행 속도)
        위도/경도 약 0.0001도 = 약 11m

        Args:
            current_pos: 현재 위치 {"lat": float, "lon": float}

        Returns:
            새 위치 {"lat": float, "lon": float}
        """
        # 0.00009 ~ 0.00045도 이동 (약 10-50m)
        offset = random.uniform(0.00009, 0.00045)

        return {
            "lat": current_pos["lat"] + offset * random.choice([-1, 1]),
            "lon": current_pos["lon"] + offset * random.choice([-1, 1]),
        }

    def on_stop(self):
        """
        사용자 종료 (테스트 종료 시)
        WebSocket 연결 해제
        """
        if hasattr(self, "ws_client") and self.ws_client:
            self.ws_client.close()
        logger.info(f"사용자 종료: {self.user_id}")


class WebSocketStepLoadShape(LoadTestShape):
    """
    점진적 부하 증가 패턴 (Step Load)

    목표: 1000명의 동시 WebSocket 연결
    전략: 점진적 증가 후 피크 유지

    단계:
    - 0-2분: 0 -> 100명 (warm-up)
    - 2-5분: 100 -> 300명 (normal load)
    - 5-8분: 300 -> 500명 (medium load)
    - 8-12분: 500 -> 750명 (high load)
    - 12-15분: 750 -> 1000명 (peak load)
    - 15-25분: 1000명 유지 (sustained stress)

    총 테스트 시간: 25분
    """

    stages = [
        # Stage 1: Warm-up (0-2분)
        {"duration": 120, "users": 100, "spawn_rate": 1},
        # Stage 2: Normal load (2-5분)
        {"duration": 300, "users": 300, "spawn_rate": 2},
        # Stage 3: Medium load (5-8분)
        {"duration": 480, "users": 500, "spawn_rate": 3},
        # Stage 4: High load (8-12분)
        {"duration": 720, "users": 750, "spawn_rate": 5},
        # Stage 5: Peak load (12-15분)
        {"duration": 900, "users": 1000, "spawn_rate": 5},
        # Stage 6: Sustained stress (15-25분) - 중요!
        {"duration": 1500, "users": 1000, "spawn_rate": 5},
    ]

    def tick(self):
        """
        Locust가 매 초마다 호출
        현재 시점의 (users, spawn_rate) 반환
        """
        run_time = self.get_run_time()

        for stage in self.stages:
            if run_time < stage["duration"]:
                return (stage["users"], stage["spawn_rate"])

        # 모든 stage 완료 시 테스트 종료
        return None
