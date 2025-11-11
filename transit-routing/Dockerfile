FROM python:3.11-slim

WORKDIR /app

# requirements 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 파일 복사
COPY . .

# 포트 노출
EXPOSE 8001

# FastAPI 애플리케이션 실행 (uvicorn)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]