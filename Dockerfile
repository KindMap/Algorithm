# Stage 1: Builder - 의존성 설치
FROM python:3.11-slim as builder

WORKDIR /app

# 빌드에 필요한 도구 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Python 의존성 설치
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Stage 2: Runtime - 최종 실행 이미지
FROM python:3.11-slim

WORKDIR /app

# Builder stage에서 설치된 Python 패키지 복사
COPY --from=builder /root/.local /root/.local

# 애플리케이션 코드만 복사 (transit-routing/app -> /app/app)
COPY transit-routing/app/ ./app/

# Python 패키지 경로 설정
ENV PATH=/root/.local/bin:$PATH

# 포트 노출
EXPOSE 8001

# 헬스체크 추가
HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health').read()" || exit 1

# FastAPI 애플리케이션 실행
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
