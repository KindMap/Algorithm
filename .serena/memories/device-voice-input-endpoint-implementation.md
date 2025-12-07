# 디바이스 음성 입력 경로 안내 엔드포인트 구현 계획

## 개요

디바이스에서 음성으로 출발지/목적지를 입력받아 시각장애인용 경로 안내를 제공하는 WebSocket 엔드포인트 구현.

**주요 변경사항 (Cloud STT → Faster-Whisper)**:
- ~~Google/Naver Cloud STT API~~ → **Faster-Whisper 로컬 모델**
- ~~외부 API 의존성~~ → **서버 내 온디바이스 처리**
- ~~API 키 관리~~ → **모델 파일 관리**
- **더 빠른 응답 시간** (네트워크 레이턴시 제거)
- **비용 절감** (API 호출 비용 없음)
- **프라이버시 강화** (음성 데이터가 외부로 전송되지 않음)

**핵심 요구사항**:
- 음성 입력: Faster-Whisper 로컬 STT 처리
- 인증: 디바이스 UUID 기반 게스트 모드 (`temp_{device_uuid}`)
- 장애 유형: VIS (시각장애인) 고정
- 통신: WebSocket 전용
- 경로 안내: 기존 시스템과 동일

## 아키텍처

**전체 플로우**:
```
Device (음성 녹음)
  → WebSocket (voice_input 메시지, Base64 오디오)
  → STT Service (Faster-Whisper 로컬 추론)
  → Station Parser Service (역 이름 추출)
  → PathfindingService (VIS 타입 경로 계산)
  → GuidanceService (실시간 안내)
  → WebSocket (응답 전송)
```

**핵심 설계 결정**:
1. **Faster-Whisper 모델 선택**: `medium` 모델 (한국어 정확도/속도 균형)
2. **비동기 처리**: ThreadPoolExecutor로 Whisper 추론을 별도 스레드에서 실행
3. **오디오 포맷**: WebM/WAV/MP3 지원, 자동 변환 파이프라인
4. **모델 로딩**: 서버 시작 시 싱글톤으로 모델 메모리에 로드 (초기화 시간 단축)
5. **기존 WebSocket 확장**: 신규 메시지 타입 `voice_input` 추가
6. **게스트 인증**: `temp_{device_uuid}` 형식
7. **Base64 인코딩 오디오** (JSON 메시지)

## 파일 구조

### 신규 파일

**1. `transit-routing/app/services/stt_service.py`** (~400 lines)

Faster-Whisper 기반 STT 서비스:

```python
"""
Faster-Whisper 기반 음성 인식 서비스

주요 기능:
- Faster-Whisper 모델 로딩 및 관리 (싱글톤)
- Base64 오디오 디코딩 및 검증
- 다양한 오디오 포맷 지원 (WebM, WAV, MP3)
- 비동기 STT 처리 (ThreadPoolExecutor)
- 한국어 음성 인식
"""

import os
import base64
import tempfile
import logging
from typing import Optional
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from faster_whisper import WhisperModel
from pydub import AudioSegment
from fastapi.concurrency import run_in_threadpool

from app.core.config import settings

logger = logging.getLogger(__name__)

# 싱글톤 모델 인스턴스
_whisper_model: Optional[WhisperModel] = None
_executor: Optional[ThreadPoolExecutor] = None


@dataclass
class STTResult:
    """STT 인식 결과"""
    text: str                    # 인식된 텍스트
    confidence: float            # 평균 신뢰도 (0.0-1.0)
    language: str                # 인식된 언어 코드
    segments: list               # 세그먼트별 상세 정보
    duration: float              # 오디오 길이 (초)

    @property
    def is_valid(self) -> bool:
        """유효한 결과인지 확인"""
        return bool(self.text.strip())


class STTException(Exception):
    """STT 처리 관련 예외"""
    pass


def get_whisper_model() -> WhisperModel:
    """
    Whisper 모델 싱글톤 인스턴스 반환
    서버 시작 시 한 번만 로드되며, 이후 재사용됩니다.
    """
    global _whisper_model
    if _whisper_model is None:
        logger.info(f"Loading Faster-Whisper model: {settings.WHISPER_MODEL_SIZE}")
        device = "cuda" if settings.WHISPER_USE_GPU else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"
        
        try:
            _whisper_model = WhisperModel(
                settings.WHISPER_MODEL_SIZE,
                device=device,
                compute_type=compute_type,
                download_root=settings.WHISPER_MODEL_DIR,
                num_workers=settings.WHISPER_NUM_THREADS,
            )
            logger.info(f"Whisper model loaded successfully on {device}")
        except Exception as e:
            logger.error(f"Failed to load Whisper model: {e}")
            raise STTException(f"모델 로딩 실패: {e}")
    return _whisper_model


def get_thread_pool() -> ThreadPoolExecutor:
    """ThreadPoolExecutor 싱글톤 인스턴스 반환"""
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=settings.WHISPER_MAX_WORKERS,
            thread_name_prefix="whisper_"
        )
    return _executor


class STTService:
    """Faster-Whisper 기반 음성 인식 서비스"""
    
    def __init__(self):
        self.model = get_whisper_model()
        self.executor = get_thread_pool()
        self.temp_dir = Path(tempfile.gettempdir()) / "kindmap_audio"
        self.temp_dir.mkdir(exist_ok=True)

    async def process_audio(
        self, audio_base64: str, audio_format: str = "webm", sample_rate: int = 16000
    ) -> STTResult:
        """Base64 인코딩된 오디오를 텍스트로 변환"""
        temp_file = None
        wav_file = None
        
        try:
            # 1. Base64 디코딩
            try:
                audio_bytes = base64.b64decode(audio_base64)
            except Exception as e:
                raise STTException(f"Base64 디코딩 실패: {e}")
            
            # 2. 파일 크기 검증
            audio_size_mb = len(audio_bytes) / (1024 * 1024)
            if audio_size_mb > settings.STT_MAX_AUDIO_SIZE_MB:
                raise STTException(f"음성 파일이 너무 큽니다 (최대 {settings.STT_MAX_AUDIO_SIZE_MB}MB)")
            
            # 3. 임시 파일로 저장
            temp_file = self.temp_dir / f"input_{os.getpid()}.{audio_format}"
            temp_file.write_bytes(audio_bytes)
            
            # 4. WAV로 변환
            wav_file = await self._convert_to_wav(temp_file, audio_format, sample_rate)
            
            # 5. Whisper 추론 실행
            result = await run_in_threadpool(self._transcribe_audio, wav_file)
            
            logger.info(f"Transcription complete: '{result.text}' (confidence: {result.confidence:.2f})")
            return result
            
        except STTException:
            raise
        except Exception as e:
            logger.error(f"STT processing error: {e}", exc_info=True)
            raise STTException(f"STT 처리 실패: {e}")
        finally:
            # 임시 파일 정리
            if temp_file and temp_file.exists():
                temp_file.unlink()
            if wav_file and wav_file.exists() and wav_file != temp_file:
                wav_file.unlink()

    async def _convert_to_wav(self, audio_file: Path, audio_format: str, sample_rate: int) -> Path:
        """오디오 파일을 WAV 포맷으로 변환"""
        if audio_format.lower() == "wav":
            return audio_file
        
        wav_file = self.temp_dir / f"converted_{os.getpid()}.wav"
        
        def convert():
            audio = AudioSegment.from_file(str(audio_file), format=audio_format)
            audio = audio.set_frame_rate(16000).set_channels(1)
            audio.export(str(wav_file), format="wav")
        
        await run_in_threadpool(convert)
        return wav_file

    def _transcribe_audio(self, wav_file: Path) -> STTResult:
        """WAV 파일을 Whisper로 텍스트 변환 (동기 함수)"""
        try:
            segments, info = self.model.transcribe(
                str(wav_file),
                language="ko",
                beam_size=5,
                best_of=5,
                temperature=0.0,
                vad_filter=True,
                vad_parameters=dict(
                    threshold=0.5,
                    min_speech_duration_ms=250,
                    min_silence_duration_ms=100
                )
            )
            
            segments_list = list(segments)
            if not segments_list:
                return STTResult(text="", confidence=0.0, language=info.language, segments=[], duration=info.duration)
            
            full_text = " ".join(seg.text.strip() for seg in segments_list)
            avg_confidence = sum(seg.avg_logprob for seg in segments_list) / len(segments_list)
            confidence = min(1.0, max(0.0, (avg_confidence + 1.0) / 1.0))
            
            return STTResult(
                text=full_text.strip(),
                confidence=confidence,
                language=info.language,
                segments=[{"start": seg.start, "end": seg.end, "text": seg.text.strip(), "confidence": seg.avg_logprob} for seg in segments_list],
                duration=info.duration
            )
        except Exception as e:
            raise STTException(f"음성 인식 실패: {e}")


# 서비스 싱글톤
_stt_service: Optional[STTService] = None

def get_stt_service() -> STTService:
    """STT 서비스 싱글톤 인스턴스 반환"""
    global _stt_service
    if _stt_service is None:
        _stt_service = STTService()
    return _stt_service
```

**에러 처리**:
- `STTException("Base64 디코딩 실패")` - Base64 디코딩 오류
- `STTException("음성 파일이 너무 큽니다")` - 크기 초과 (>10MB)
- `STTException("모델 로딩 실패")` - Whisper 모델 로딩 실패
- `STTException("음성 인식 실패")` - Whisper 추론 실패
- `STTException("오디오 변환 실패")` - 포맷 변환 실패

---

**2. `transit-routing/app/services/station_parser_service.py`** (~200 lines)

한국어 자연어에서 역 이름 추출:

```python
class StationParseResult:
    origin: Optional[str]              # 출발지 역 이름
    origin_cd: Optional[str]           # 출발지 역 코드
    destination: Optional[str]         # 목적지 역 이름
    destination_cd: Optional[str]      # 목적지 역 코드
    confidence: float                  # 파싱 신뢰도
    raw_text: str                      # 원본 텍스트
    
    @property
    def is_valid(self) -> bool:
        return bool(self.origin_cd and self.destination_cd)

class StationParserService:
    """역 이름 파싱 서비스"""
    
    # 정규식 패턴
    PATTERNS = [
        # "사당역에서 강남역까지" / "사당에서 강남으로"
        r"(?P<origin>[가-힣]+)\s*역?\s*에서\s*(?P<destination>[가-힣]+)\s*역?\s*(까지|로|갈게요)?",
        
        # "사당부터 강남까지"
        r"(?P<origin>[가-힣]+)\s*역?\s*부터\s*(?P<destination>[가-힣]+)\s*역?\s*까지?",
        
        # "사당 강남" (공백 구분)
        r"(?P<origin>[가-힣]+)\s+(?P<destination>[가-힣]+)",
    ]
    
    def parse(self, text: str) -> StationParseResult:
        """
        1. 텍스트 정제 (불필요한 단어 제거: "가자", "갈게요" 등)
        2. 각 패턴으로 매칭 시도
        3. get_station_cd_by_name()으로 역 존재 검증
        4. 패턴 매칭 실패시 _fuzzy_split_stations() 시도
        5. StationParseResult 반환
        """
    
    def _fuzzy_split_stations(self, text: str) -> StationParseResult:
        """
        "사당강남" 같은 연결된 텍스트를 분리
        - 모든 가능한 분리점 시도 (i=1 to len-1)
        - 양쪽이 모두 유효한 역 이름인지 확인
        - 첫 번째 유효한 분리 반환
        """
    
    def suggest_corrections(self, text: str, limit: int) -> List[Dict]:
        """
        퍼지 매칭으로 유사 역 이름 제안
        - search_stations_by_name() 활용
        - 상위 N개 제안 반환
        """
```

**파싱 신뢰도:**
- 패턴 매칭 성공: 0.9
- Fuzzy split 성공: 0.7
- 실패: 제안 목록 반환

---

### 수정 파일

**3. `transit-routing/app/api/v1/endpoints/websocket.py`**

**변경 1: 서비스 임포트 추가 (파일 상단)**

```python
# 음성 입력 관련 서비스
from app.services.stt_service import get_stt_service, STTException
from app.services.station_parser_service import get_station_parser_service
```

**변경 2: 메시지 라우팅 추가 (라인 301 이후)**

```python
elif message_type == "voice_input":
    await handle_voice_input(
        user_id, data,
        get_stt_service(),
        get_station_parser_service(),
        get_pathfinding_service()
    )
```

**변경 3: 핸들러 함수 추가 (라인 709 이후, ~150 lines)**

```python
async def handle_voice_input(
    user_id: str,
    data: dict,
    stt_service,
    parser_service,
    pathfinding_service: PathfindingService,
):
    """
    음성 입력 처리 핸들러
    
    플로우:
    1. audio_data 검증
    2. transcription_started 전송
    3. STT 처리 (비동기)
    4. transcription_complete 전송  
    5. 역 이름 파싱
    6. stations_recognized 전송
    7. 경로 계산 (disability_type=VIS)
    8. route_calculated 전송
    """
    # 구현 세부사항은 계획 파일 참조
```

---

**4. `transit-routing/app/core/config.py`**

라인 135 이후 추가:

```python
# ==================== STT Service Configuration ====================

# Faster-Whisper 모델 설정
WHISPER_MODEL_SIZE: str = os.getenv("WHISPER_MODEL_SIZE", "medium")  # tiny, base, small, medium, large
WHISPER_MODEL_DIR: str = os.getenv("WHISPER_MODEL_DIR", "./models/whisper")
WHISPER_USE_GPU: bool = os.getenv("WHISPER_USE_GPU", "false").lower() == "true"
WHISPER_NUM_THREADS: int = int(os.getenv("WHISPER_NUM_THREADS", "4"))
WHISPER_MAX_WORKERS: int = int(os.getenv("WHISPER_MAX_WORKERS", "2"))

# STT 처리 제한
STT_TIMEOUT_SECONDS: int = int(os.getenv("STT_TIMEOUT_SECONDS", "30"))
STT_MAX_AUDIO_SIZE_MB: int = int(os.getenv("STT_MAX_AUDIO_SIZE_MB", "10"))

# 음성 입력 기본값
VOICE_AUDIO_FORMAT: str = os.getenv("VOICE_AUDIO_FORMAT", "webm")
VOICE_SAMPLE_RATE: int = int(os.getenv("VOICE_SAMPLE_RATE", "16000"))
```

---

**5. `requirements.txt`**

다음 라이브러리를 추가합니다:

```txt
# 오디오 처리
pydub>=0.25.1
ffmpeg-python>=0.2.0

# NOTE: faster-whisper>=0.10.0은 이미 존재함 (라인 70)
```

---

**6. `Dockerfile.fastapi`**

**변경 위치**: Builder stage의 apt-get install 부분 (라인 5-8)

**기존 코드**:
```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*
```

**수정 후**:
```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*
```

**변경 이유**:
- pydub은 오디오 포맷 변환을 위해 ffmpeg가 필요
- Faster-Whisper도 일부 오디오 처리에 ffmpeg 사용
- 런타임 이미지에서도 ffmpeg가 필요하므로 builder stage에 설치
- ffmpeg는 약 50-60MB 추가 용량을 차지하지만, 오디오 처리에 필수적

## 메시지 프로토콜

### Client → Server

```json
{
  "type": "voice_input",
  "audio_data": "UklGRiQAAABXQVZFZm10IBAAAAABAAEA...",  // Base64 인코딩된 오디오
  "audio_format": "webm",  // optional, default: webm
  "sample_rate": 16000     // optional, default: 16000
}
```

### Server → Client

**1. 인식 시작**
```json
{
  "type": "transcription_started",
  "message": "음성 인식 중..."
}
```

**2. 인식 완료**
```json
{
  "type": "transcription_complete",
  "transcribed_text": "사당역에서 강남역까지",
  "confidence": 0.95
}
```

**3. 역 인식**
```json
{
  "type": "stations_recognized",
  "origin": "사당",
  "origin_cd": "0219",
  "destination": "강남",
  "destination_cd": "0222",
  "message": "출발: 사당, 도착: 강남"
}
```

**4. 경로 계산 완료** (기존 route_calculated 재사용)
```json
{
  "type": "route_calculated",
  "route_id": "uuid-here",
  "origin": "사당",
  "destination": "강남",
  "routes": [...],  // 상위 3개 경로
  "disability_type": "VIS",
  "input_method": "voice"
}
```

**5. 에러**
```json
{
  "type": "error",
  "code": "STT_FAILED",
  "message": "음성 인식에 실패했습니다. 다시 시도해주세요."
}
```

**에러 코드:**
- `MISSING_AUDIO_DATA`: audio_data 필드 누락
- `AUDIO_TOO_LARGE`: 파일 크기 > 10MB
- `INVALID_AUDIO_FORMAT`: 지원하지 않는 포맷
- `STT_FAILED`: STT API 호출 실패
- `STT_TIMEOUT`: 타임아웃
- `STT_NO_RESULT`: 빈 텍스트 반환
- `NO_STATIONS_FOUND`: 역 이름 파싱 실패
- `PARSING_ERROR`: 파싱 중 예외
- `ROUTE_CALCULATION_ERROR`: 경로 계산 실패

## 환경 변수 (.env)

```bash
# ==================== Faster-Whisper 설정 ====================

# 모델 크기 선택 (tiny < base < small < medium < large)
# - tiny: 가장 빠름, 정확도 낮음 (~1GB RAM)
# - base: 빠름, 적당한 정확도 (~1GB RAM)
# - small: 균형잡힘 (~2GB RAM)
# - medium: 권장 - 한국어 높은 정확도 (~5GB RAM)
# - large: 최고 정확도, 느림 (~10GB RAM)
WHISPER_MODEL_SIZE=medium

# 모델 저장 디렉토리
WHISPER_MODEL_DIR=./models/whisper

# GPU 사용 여부 (CUDA 사용 가능 시 true)
WHISPER_USE_GPU=false

# CPU 스레드 수
WHISPER_NUM_THREADS=4

# 동시 처리 워커 수
WHISPER_MAX_WORKERS=2

# STT 타임아웃 (초)
STT_TIMEOUT_SECONDS=30

# 최대 오디오 파일 크기 (MB)
STT_MAX_AUDIO_SIZE_MB=10

# 기본 오디오 포맷
VOICE_AUDIO_FORMAT=webm

# 기본 샘플링 레이트 (Hz)
VOICE_SAMPLE_RATE=16000
```

## 성능 목표

| 단계 | 목표 | 허용 범위 |
|------|------|-----------|
| 오디오 업로드 (5초) | <500ms | <1s |
| STT 처리 | <2s | <5s |
| 역 이름 파싱 | <50ms | <200ms |
| 경로 계산 | <100ms | <500ms |
| **전체 E2E** | **<3s** | **<7s** |

## 테스트

### 단위 테스트

**`tests/test_stt_service.py`**
- Google STT 정상 처리
- Naver STT 정상 처리
- 파일 크기 제한 검증
- Base64 디코딩 에러
- 타임아웃 처리

**`tests/test_station_parser.py`**
- 명확한 패턴 파싱: "사당역에서 강남역까지"
- 짧은 패턴: "사당 강남"
- 연결된 텍스트: "사당강남"
- 파싱 실패 케이스
- 유사 역 제안

### 통합 테스트

**`tests/test_voice_websocket.py`**
```python
@pytest.mark.asyncio
async def test_voice_input_flow(test_client):
    with test_client.websocket_connect("/api/v1/ws/temp_test_device_123") as ws:
        ws.send_json({
            "type": "voice_input",
            "audio_data": get_test_audio_base64(),
            "audio_format": "webm",
            "sample_rate": 16000
        })
        
        # 응답 순서 검증
        assert ws.receive_json()["type"] == "transcription_started"
        assert ws.receive_json()["type"] == "transcription_complete"
        assert ws.receive_json()["type"] == "stations_recognized"
        route_msg = ws.receive_json()
        assert route_msg["type"] == "route_calculated"
        assert route_msg["disability_type"] == "VIS"
```

## 구현 순서

1. **STT Service 구현** (1일)
   - 추상 클래스 및 Google/Naver provider
   - 단위 테스트

2. **Station Parser Service 구현** (1일)
   - 정규식 패턴 매칭
   - Fuzzy split 로직
   - 단위 테스트

3. **WebSocket 통합** (1일)
   - websocket.py 수정
   - config.py 수정
   - 통합 테스트

4. **테스트 및 최적화** (1일)
   - 성능 테스트
   - 에러 케이스 검증
   - 문서화

## 클라이언트 예제

```javascript
const deviceId = `temp_${crypto.randomUUID()}`;
const ws = new WebSocket(`ws://localhost:8001/api/v1/ws/${deviceId}`);

// 오디오 녹음
const mediaRecorder = new MediaRecorder(stream, {
  mimeType: 'audio/webm;codecs=opus'
});

mediaRecorder.onstop = async () => {
  const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
  const base64Audio = await blobToBase64(audioBlob);
  
  ws.send(JSON.stringify({
    type: 'voice_input',
    audio_data: base64Audio.split(',')[1],
    audio_format: 'webm',
    sample_rate: 48000
  }));
};

// 응답 처리
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  switch(data.type) {
    case 'transcription_complete':
      showTranscription(data.transcribed_text);
      break;
    case 'route_calculated':
      displayRoute(data.routes);
      break;
  }
};
```

## 주요 고려사항

### 1. Faster-Whisper vs Cloud STT 비교

| 항목 | Faster-Whisper | Google STT | Naver Clova |
|------|---------------|------------|-------------|
| **정확도 (한국어)** | ⭐⭐⭐⭐ (medium) | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **응답 시간** | 3-5초 (CPU) | 2-3초 | 2-3초 |
| **비용** | 무료 | $0.006/15초 | 유료 |
| **프라이버시** | ⭐⭐⭐⭐⭐ (로컬) | ⭐⭐ (클라우드) | ⭐⭐ (클라우드) |
| **확장성** | 서버 리소스 제한 | 무제한 (API) | 무제한 (API) |
| **인터넷 의존성** | 없음 | 필수 | 필수 |

**결론**:
- 프라이버시 우선, 비용 절감 → **Faster-Whisper 권장**
- 최고 정확도, 높은 트래픽 → Google/Naver STT 고려

### 2. Whisper 모델 크기 선택

| 모델 | 파라미터 | 메모리 | 속도 (CPU) | 정확도 | 권장 용도 |
|------|---------|--------|-----------|--------|----------|
| tiny | 39M | ~1GB | 매우 빠름 | ⭐⭐ | 테스트용 |
| base | 74M | ~1GB | 빠름 | ⭐⭐⭐ | 저사양 서버 |
| small | 244M | ~2GB | 적당 | ⭐⭐⭐⭐ | 균형잡힌 선택 |
| **medium** | 769M | ~5GB | 보통 | ⭐⭐⭐⭐⭐ | **프로덕션 권장** |
| large | 1550M | ~10GB | 느림 | ⭐⭐⭐⭐⭐ | 최고 정확도 필요 시 |

**권장**: `medium` 모델 (한국어 정확도/속도 최적)

### 3. 서버 리소스 요구사항

**CPU 모드 (권장 개발/저트래픽)**:
- CPU: 4 cores 이상
- RAM: 8GB 이상 (medium 모델)
- 동시 처리: 2-4 요청

**GPU 모드 (권장 프로덕션/고트래픽)**:
- GPU: NVIDIA GPU (CUDA 11.x 이상)
- VRAM: 6GB 이상
- RAM: 16GB 이상
- 동시 처리: 10+ 요청

### 4. 오디오 포맷
   - WebM (Opus): 최신 브라우저, 압축률 우수
   - WAV: 무손실, 파일 크기 큼
   - MP3: 호환성 높음

3. **보안**
   - 게스트 모드: 인증 불필요
   - Rate limiting 필요 (향후)
   - API 키: 환경변수 관리

4. **확장성**
   - Redis Pub/Sub: 다중 인스턴스 지원
   - Provider 추상화: 쉬운 제공자 교체
