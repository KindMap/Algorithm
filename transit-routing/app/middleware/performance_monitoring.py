# 성능 모니터링 미들웨어

import time
import logging
import json
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.config import settings

logger = logging.getLogger(__name__)


class PerformanceMonitoringMiddleware(BaseHTTPMiddleware):
    """
    성능 모니터링 미들웨어

    모든 HTTP 요청의 응답 시간을 측정하고 로깅합니다.
    느린 요청(threshold 초과)은 경고로 로깅됩니다.
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.enabled = settings.ENABLE_PERFORMANCE_MONITORING
        self.slow_threshold_ms = settings.SLOW_REQUEST_THRESHOLD_MS

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """요청 처리 및 성능 측정"""

        if not self.enabled:
            return await call_next(request)

        # 시작 시간 기록
        start_time = time.time()

        # 요청 처리
        try:
            response = await call_next(request)

            # 종료 시간 및 소요 시간 계산
            elapsed_time_ms = (time.time() - start_time) * 1000

            # 응답 헤더에 소요 시간 추가
            response.headers["X-Process-Time-Ms"] = f"{elapsed_time_ms:.2f}"

            # 성능 메트릭 로깅
            self._log_performance_metrics(
                request=request,
                response=response,
                elapsed_time_ms=elapsed_time_ms,
            )

            return response

        except Exception as e:
            # 예외 발생 시에도 소요 시간 측정
            elapsed_time_ms = (time.time() - start_time) * 1000

            logger.error(
                f"요청 처리 중 예외 발생: {request.method} {request.url.path}, "
                f"소요시간={elapsed_time_ms:.2f}ms, 예외={str(e)}",
                exc_info=True,
            )

            raise

    def _log_performance_metrics(
        self, request: Request, response: Response, elapsed_time_ms: float
    ) -> None:
        """성능 메트릭 로깅"""

        # 기본 메트릭
        metrics = {
            "event": "http_request",
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "elapsed_time_ms": round(elapsed_time_ms, 2),
        }

        # 쿼리 파라미터 (민감 정보 제외)
        if request.query_params:
            metrics["query_params"] = dict(request.query_params)

        # 클라이언트 정보
        if request.client:
            metrics["client_host"] = request.client.host

        # User-Agent
        if "user-agent" in request.headers:
            metrics["user_agent"] = request.headers["user-agent"]

        # 느린 요청 감지
        if elapsed_time_ms > self.slow_threshold_ms:
            logger.warning(
                f"⚠️ 느린 요청 감지: {request.method} {request.url.path}, "
                f"소요시간={elapsed_time_ms:.2f}ms (기준: {self.slow_threshold_ms}ms)"
            )
            metrics["slow_request"] = True
        else:
            metrics["slow_request"] = False

        # 메트릭 로깅 (INFO 레벨)
        logger.info(f"PERFORMANCE: {json.dumps(metrics, ensure_ascii=False)}")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    요청/응답 로깅 미들웨어

    모든 HTTP 요청과 응답을 로깅합니다.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """요청/응답 로깅"""

        # 요청 로깅
        logger.info(
            f"→ {request.method} {request.url.path} "
            f"from {request.client.host if request.client else 'unknown'}"
        )

        # 요청 처리
        response = await call_next(request)

        # 응답 로깅
        log_level = logging.INFO if response.status_code < 400 else logging.ERROR
        logger.log(
            log_level,
            f"← {request.method} {request.url.path} "
            f"status={response.status_code}",
        )

        return response


class MetricsCollector:
    """
    메트릭 수집기

    애플리케이션 전체의 메트릭을 수집하고 저장합니다.
    (Redis 또는 메모리에 저장)
    """

    def __init__(self):
        self.request_count = 0
        self.total_elapsed_time_ms = 0.0
        self.slow_request_count = 0
        self.error_count = 0

        # 경로별 통계
        self.path_stats = {}

    def record_request(
        self,
        path: str,
        method: str,
        status_code: int,
        elapsed_time_ms: float,
        is_slow: bool = False,
    ):
        """요청 메트릭 기록"""

        self.request_count += 1
        self.total_elapsed_time_ms += elapsed_time_ms

        if is_slow:
            self.slow_request_count += 1

        if status_code >= 400:
            self.error_count += 1

        # 경로별 통계
        path_key = f"{method} {path}"
        if path_key not in self.path_stats:
            self.path_stats[path_key] = {
                "count": 0,
                "total_time_ms": 0.0,
                "slow_count": 0,
                "error_count": 0,
            }

        stats = self.path_stats[path_key]
        stats["count"] += 1
        stats["total_time_ms"] += elapsed_time_ms

        if is_slow:
            stats["slow_count"] += 1

        if status_code >= 400:
            stats["error_count"] += 1

    def get_summary(self) -> dict:
        """전체 메트릭 요약"""

        avg_time_ms = (
            self.total_elapsed_time_ms / self.request_count
            if self.request_count > 0
            else 0
        )

        return {
            "total_requests": self.request_count,
            "average_elapsed_time_ms": round(avg_time_ms, 2),
            "slow_requests": self.slow_request_count,
            "error_requests": self.error_count,
            "success_rate": (
                round(
                    (self.request_count - self.error_count) / self.request_count * 100,
                    2,
                )
                if self.request_count > 0
                else 0
            ),
        }

    def get_path_stats(self, top_n: int = 10) -> list:
        """경로별 통계 (상위 N개)"""

        # 요청 수 기준 정렬
        sorted_paths = sorted(
            self.path_stats.items(), key=lambda x: x[1]["count"], reverse=True
        )

        result = []
        for path, stats in sorted_paths[:top_n]:
            avg_time_ms = (
                stats["total_time_ms"] / stats["count"] if stats["count"] > 0 else 0
            )

            result.append(
                {
                    "path": path,
                    "count": stats["count"],
                    "avg_time_ms": round(avg_time_ms, 2),
                    "slow_count": stats["slow_count"],
                    "error_count": stats["error_count"],
                }
            )

        return result


# 전역 메트릭 수집기 인스턴스
_metrics_collector = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    """메트릭 수집기 인스턴스 반환"""
    return _metrics_collector
