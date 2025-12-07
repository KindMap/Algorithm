import base64
import logging
import io
import math
import asyncio
from typing import Optional
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

from faster_whisper import WhisperModel
from pydub import AudioSegment

from app.core.config import settings

logger = logging.getLogger(__name__)

# 싱글톤 인스턴스
_whisper_model: Optional[WhisperModel] = None
_executor: Optional[ThreadPoolExecutor] = None


@dataclass
class STTResult:
    text: str
    confidence: float
    language: str
    duration: float

    @property
    def is_valid(self) -> bool:
        return bool(self.text.strip())


class STTException(Exception):
    pass


def get_whisper_model() -> WhisperModel:
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
    global _executor
    if _executor is None:
        # CPU 과부하 방지를 위해 워커 수 제한 (config에서 설정)
        _executor = ThreadPoolExecutor(
            max_workers=settings.WHISPER_MAX_WORKERS,
            thread_name_prefix="whisper_worker_",
        )
    return _executor


class STTService:
    def __init__(self):
        self.model = get_whisper_model()
        self.executor = get_thread_pool()

    async def process_audio(
        self, audio_base64: str, audio_format: str = "webm", sample_rate: int = 16000
    ) -> STTResult:
        try:
            # 1. Base64 디코딩
            try:
                audio_bytes = base64.b64decode(audio_base64)
            except Exception as e:
                raise STTException(f"Base64 디코딩 실패: {e}")

            # 2. 크기 검증
            if len(audio_bytes) > settings.STT_MAX_AUDIO_SIZE_MB * 1024 * 1024:
                raise STTException("음성 파일 크기 초과")

            # 3. 비동기 실행 (커스텀 스레드 풀 사용) => 제한된 스레드 풀에서 동작하도록 조정
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                self.executor, self._process_in_memory, audio_bytes, audio_format
            )

            logger.info(f"Transcription: '{result.text}' ({result.confidence:.2f})")
            return result

        except STTException:
            raise
        except Exception as e:
            logger.error(f"STT Error: {e}", exc_info=True)
            raise STTException("STT 처리 중 내부 오류")

    def _process_in_memory(self, audio_data: bytes, input_format: str) -> STTResult:
        """
        [CPU Bound] 오디오 변환 -> Whisper 추론
        """
        # A. 오디오 포맷 변환
        try:
            input_stream = io.BytesIO(audio_data)
            audio = AudioSegment.from_file(input_stream, format=input_format)
            audio = audio.set_frame_rate(16000).set_channels(1)

            wav_stream = io.BytesIO()
            audio.export(wav_stream, format="wav")
            wav_stream.seek(0)
        except Exception as e:
            raise STTException(f"오디오 변환 실패 (ffmpeg 확인 필요): {e}")

        # B. Whisper 추론
        try:
            segments, info = self.model.transcribe(
                wav_stream,
                language="ko",
                beam_size=5,
                temperature=0.0,
                condition_on_previous_text=False,
                initial_prompt="지하철 역 이름입니다. 사당역, 강남역, 서울역.",
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500),
            )

            segments_list = list(segments)

            if not segments_list:
                return STTResult(
                    text="",
                    confidence=0.0,
                    language=info.language,
                    duration=info.duration,
                )

            full_text = " ".join(seg.text.strip() for seg in segments_list)

            # LogProb -> Probability 변환 (math.exp 사용)
            avg_logprob = sum(seg.avg_logprob for seg in segments_list) / len(
                segments_list
            )
            confidence = math.exp(avg_logprob)

            return STTResult(
                text=full_text,
                confidence=confidence,
                language=info.language,
                duration=info.duration,
            )
        except Exception as e:
            raise STTException(f"Whisper 추론 실패: {e}")


# 서비스 싱글톤
_stt_service: Optional[STTService] = None


def get_stt_service() -> STTService:
    """STT 서비스 싱글톤 인스턴스 반환"""
    global _stt_service
    if _stt_service is None:
        _stt_service = STTService()
    return _stt_service
