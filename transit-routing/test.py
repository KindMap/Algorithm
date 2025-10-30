import requests
import json
from typing import Dict, Any


class APITester:
    def __init__(self, base_url: str = "http://localhost:8001"):
        self.base_url = base_url

    def test_health_check(self):
        """헬스 체크 테스트"""
        print("\n=== 헬스 체크 테스트 ===")
        response = requests.get(f"{self.base_url}/health")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
        return response.status_code == 200

    def test_get_disability_types(self):
        """장애 유형 목록 조회 테스트"""
        print("\n=== 장애 유형 목록 조회 테스트 ===")
        response = requests.get(f"{self.base_url}/api/v1/disability-types")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
        return response.status_code == 200

    def test_get_stations(self, line: str = None):
        """역 목록 조회 테스트"""
        print(f"\n=== 역 목록 조회 테스트 (line={line}) ===")
        url = f"{self.base_url}/api/v1/stations"
        if line:
            url += f"?line={line}"

        response = requests.get(url)
        print(f"Status Code: {response.status_code}")
        data = response.json()
        print(f"Count: {data.get('count', 0)}")

        # 처음 3개만 출력
        if data.get("stations"):
            print(
                f"First 3 stations: {json.dumps(data['stations'][:3], indent=2, ensure_ascii=False)}"
            )

        return response.status_code == 200

    def test_get_station_by_code(self, station_cd: str):
        """특정 역 정보 조회 테스트"""
        print(f"\n=== 역 정보 조회 테스트 (station_cd={station_cd}) ===")
        response = requests.get(f"{self.base_url}/api/v1/stations/{station_cd}")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
        return response.status_code == 200

    def test_find_routes(
        self,
        origin: str,
        destination: str,
        disability_type: str = "PHY",
        departure_time: float = 540.0,
        max_rounds: int = 4,
    ):
        """경로 탐색 테스트"""
        print(f"\n=== 경로 탐색 테스트 ===")
        print(f"출발: {origin}, 도착: {destination}, 유형: {disability_type}")

        data = {
            "origin": origin,
            "destination": destination,
            "departure_time": departure_time,
            "disability_type": disability_type,
            "max_rounds": max_rounds,
        }

        response = requests.post(
            f"{self.base_url}/api/v1/routes",
            json=data,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )

        print(f"Status Code: {response.status_code}")
        result = response.json()

        if result.get("success"):
            print(f"찾은 경로 수: {len(result.get('routes', []))}")

            # 상위 3개 경로만 출력
            for route in result.get("routes", [])[:3]:
                print(f"\n--- Rank {route['rank']} ---")
                print(f"Score: {route['score']}")
                print(f"도착 시간: {route['arrival_time']:.2f}분")
                print(f"환승 횟수: {route['transfers']}회")
                print(f"보행 거리: {route['walking_distance']:.2f}m")
                print(f"편의도: {route['convenience_score']:.2f}")
                print(f"경로: {' -> '.join(route['route'][:5])}...")  # 처음 5개 역만
        else:
            print(f"Error: {result.get('error', 'Unknown error')}")

        return response.status_code == 200

    def test_invalid_request(self):
        """잘못된 요청 테스트"""
        print("\n=== 잘못된 요청 테스트 ===")

        # 필수 파라미터 누락
        data = {
            "origin": "서울역",
            # destination 누락
            "disability_type": "PHY",
        }

        response = requests.post(f"{self.base_url}/api/v1/routes", json=data)

        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
        return response.status_code == 400


def main():
    """메인 테스트 함수"""
    tester = APITester()

    results = {}

    # 1. 헬스 체크
    results["health"] = tester.test_health_check()

    # 2. 장애 유형 조회
    results["disability_types"] = tester.test_get_disability_types()

    # 3. 역 목록 조회
    results["stations_all"] = tester.test_get_stations()
    results["stations_line"] = tester.test_get_stations(line="2호선")

    # 4. 특정 역 조회 (실제 존재하는 station_cd로 변경 필요)
    # results['station_detail'] = tester.test_get_station_by_code("ST001")

    # 5. 경로 탐색 테스트
    # 광화문 => 남성 : 환승 횟수 확인하기
    results["route_phy"] = tester.test_find_routes(
        origin="광화문", destination="남성", disability_type="PHY"
    )

    results["route_vis"] = tester.test_find_routes(
        origin="광화문", destination="남성", disability_type="VIS"
    )

    # 6. 잘못된 요청 테스트
    results["invalid"] = tester.test_invalid_request()

    # 결과 요약
    print("\n" + "=" * 50)
    print("테스트 결과 요약")
    print("=" * 50)
    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{test_name}: {status}")

    total = len(results)
    passed = sum(results.values())
    print(f"\n총 {total}개 테스트 중 {passed}개 통과")


if __name__ == "__main__":
    main()
