import asyncio
import httpx
from datetime import datetime
import time
import logging

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

BASE_URL = "http://localhost:8000"

async def test_route_search():
    """경로 탐색 테스트"""
    
    test_cases = [
        ("광화문", "남성"),
        ("충무로", "동묘앞"),
        ("구반포", "서울"),
        ("청구", "숙대입구"),
    ]
    
    disability_types = ["PHY", "VIS", "AUD", "ELD"]
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        logger.info("=" * 80)
        logger.info("경로 탐색 테스트 시작")
        logger.info("=" * 80)
        
        for origin, destination in test_cases:
            logger.info(f"\n{'='*80}")
            logger.info(f"테스트 경로: {origin} → {destination}")
            logger.info(f"{'='*80}")
            
            for disability_type in disability_types:
                logger.info(f"\n[{disability_type}] 장애 유형 테스트")
                logger.info("-" * 60)
                
                # 알고리즘 실행 시간 측정 시작
                start_time = time.time()
                
                request_data = {
                    "origin": origin,
                    "destination": destination,
                    "departure_time": datetime.now().isoformat(),
                    "disability_type": disability_type
                }
                
                try:
                    response = await client.post(
                        f"{BASE_URL}/search",
                        json=request_data
                    )
                    
                    # 알고리즘 실행 시간 측정 종료
                    end_time = time.time()
                    algorithm_time = end_time - start_time
                    
                    if response.status_code == 200:
                        data = response.json()
                        
                        logger.info(f"✓ 응답 성공 (HTTP 200)")
                        logger.info(f"✓ 총 실행 시간: {algorithm_time:.4f}초")
                        logger.info(f"✓ 서버 내부 탐색 시간: {data['search_time']:.4f}초")
                        logger.info(f"✓ 메시지: {data['message']}")
                        logger.info(f"✓ 찾은 경로 수: {len(data['routes'])}개")
                        
                        # 각 경로 상세 정보
                        for idx, route in enumerate(data['routes'], 1):
                            logger.info(f"\n  경로 #{idx}:")
                            logger.info(f"    - 총 소요시간: {route['total_time']:.2f}분")
                            logger.info(f"    - 환승 횟수: {route['transfers']}회")
                            logger.info(f"    - 환승 난이도: {route['transfer_difficulty']:.4f}")
                            logger.info(f"    - 편의도 점수: {route['convenience_score']:.4f}")
                            logger.info(f"    - 혼잡도 점수: {route['congestion_score']:.4f}")
                            logger.info(f"    - ANP 종합 점수: {route['anp_score']:.4f}")
                            
                            # 환승역 정보
                            if route['transfer_stations']:
                                logger.info(f"    - 환승역: {', '.join(route['transfer_stations'])}")
                                
                                for td in route['transfer_details']:
                                    logger.info(f"      * {td['station_name']}:")
                                    logger.info(f"        편의도: {td['convenience_score']:.4f}, "
                                              f"혼잡도: {td['congestion_score']:.4f}, "
                                              f"보행시간: {td['walking_time']:.2f}분")
                            else:
                                logger.info(f"    - 환승 없음 (직통)")
                            
                            # 선호 편의시설
                            facilities = route['preferred_facilities_available']
                            if facilities:
                                available = [k for k, v in facilities.items() if v]
                                logger.info(f"    - 선호 편의시설: {', '.join(available) if available else '없음'}")
                    
                    else:
                        logger.error(f"✗ 응답 실패 (HTTP {response.status_code})")
                        logger.error(f"✗ 오류: {response.text}")
                        logger.info(f"✗ 실행 시간: {algorithm_time:.4f}초")
                
                except httpx.TimeoutException:
                    logger.error(f"✗ 타임아웃 (60초 초과)")
                except httpx.RequestError as e:
                    logger.error(f"✗ 요청 오류: {e}")
                except Exception as e:
                    logger.error(f"✗ 예외 발생: {e}")
                
                # 테스트 간 간격
                await asyncio.sleep(0.5)
        
        logger.info(f"\n{'='*80}")
        logger.info("모든 테스트 완료")
        logger.info(f"{'='*80}")

async def test_health_check():
    """헬스 체크 테스트"""
    logger.info("\n헬스 체크 테스트")
    logger.info("-" * 60)
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{BASE_URL}/")
            if response.status_code == 200:
                logger.info("✓ 서버 정상 작동")
                logger.info(f"  응답: {response.json()}")
            else:
                logger.error(f"✗ 서버 오류 (HTTP {response.status_code})")
        except Exception as e:
            logger.error(f"✗ 서버 연결 실패: {e}")

async def main():
    """메인 테스트 실행"""
    logger.info("\n" + "="*80)
    logger.info("경로 탐색 API 로컬 테스트")
    logger.info("="*80)
    
    # 헬스 체크
    await test_health_check()
    
    # 경로 탐색 테스트
    await test_route_search()

if __name__ == "__main__":
    asyncio.run(main())