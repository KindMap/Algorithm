# 디바이스 음성 입력 WebSocket API 기술 문서

## 개요

본 문서는 시각장애인용 경로 안내 시스템에서 라즈베리 파이 디바이스가 음성 입력을 통해 경로 안내를 받기 위한 WebSocket API 사양을 정의합니다.

**대상 디바이스**: Raspberry Pi (라즈베리 파이)  
**통신 방식**: WebSocket (실시간 양방향 통신)  
**인증 방식**: 게스트 모드 (디바이스 UUID 기반)  
**음성 인식**: 서버 측 Faster-Whisper STT  
**지원 언어**: 한국어

---

## 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                    Raspberry Pi Device                       │
│  ┌──────────────┐      ┌──────────────┐                    │
│  │ Audio Input  │─────▶│ Base64       │                    │
│  │ (Microphone) │      │ Encoder      │                    │
│  └──────────────┘      └──────┬───────┘                    │
│                               │                              │
│                               ▼                              │
│                    ┌──────────────────┐                     │
│                    │ WebSocket Client │                     │
│                    └────────┬─────────┘                     │
└─────────────────────────────┼─────────────────────────────┘
                               │
                               │ WebSocket (JSON)
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                      Server (FastAPI)                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ STT Service  │─▶│ Parser       │─▶│ Pathfinding  │     │
│  │ (Whisper)    │  │ (Station)    │  │ (MC-RAPTOR)  │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

---

## 연결 정보

### WebSocket 엔드포인트

```
ws://<server_host>:<server_port>/api/v1/ws/{user_id}
```

**파라미터**:
- `server_host`: 서버 IP 주소 (예: `192.168.1.100` 또는 `api.kindmap.com`)
- `server_port`: 서버 포트 (기본값: `8001`)
- `user_id`: 디바이스 고유 식별자 (게스트 모드: `temp_{device_uuid}`)

**게스트 모드 user_id 생성 규칙**:
```python
import uuid

device_uuid = str(uuid.uuid4())  # 예: "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
user_id = f"temp_{device_uuid}"  # 예: "temp_a1b2c3d4-e5f6-7890-abcd-ef1234567890"
```

**연결 예시**:
```
ws://192.168.1.100:8001/api/v1/ws/temp_a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

---

## 음성 입력 플로우

### 전체 시퀀스

```
Raspberry Pi                           Server
    │                                     │
    ├─────── WebSocket Connect ──────────▶│
    │                                     │
    ├─────── voice_input ────────────────▶│
    │         (Base64 audio)              │
    │                                     │
    │◀────── transcription_started ───────┤
    │         "음성 인식 중..."            │
    │                                     │
    │                                 [STT 처리]
    │                                     │
    │◀────── transcription_complete ──────┤
    │         "사당역에서 강남역까지"      │
    │                                     │
    │                                 [역 파싱]
    │                                     │
    │◀────── stations_recognized ─────────┤
    │         출발: 사당, 도착: 강남       │
    │                                     │
    │                                 [경로 계산]
    │                                     │
    │◀────── route_calculated ────────────┤
    │         경로 3개                     │
    │                                     │
```

### 처리 단계

1. **음성 녹음** (디바이스): 마이크로 음성 녹음
2. **Base64 인코딩** (디바이스): 오디오 데이터 인코딩
3. **voice_input 전송** (디바이스): WebSocket으로 전송
4. **STT 처리** (서버): Faster-Whisper로 음성→텍스트 변환
5. **역 이름 파싱** (서버): 출발지/목적지 역 추출
6. **경로 계산** (서버): VIS 타입 경로 탐색
7. **결과 수신** (디바이스): 경로 안내 데이터 수신

---

## 메시지 프로토콜

### 1. Client → Server: 음성 입력 요청

**메시지 타입**: `voice_input`

```json
{
  "type": "voice_input",
  "audio_data": "UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAAB9AAACABAAZGF0YQAAAAA...",
  "audio_format": "webm",
  "sample_rate": 16000
}
```

**필드 설명**:

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|------|------|------|--------|------|
| `type` | string | ✅ | - | 고정값: `"voice_input"` |
| `audio_data` | string | ✅ | - | Base64 인코딩된 오디오 데이터 |
| `audio_format` | string | ❌ | `"webm"` | 오디오 포맷 (`webm`, `wav`, `mp3`) |
| `sample_rate` | integer | ❌ | `16000` | 샘플링 레이트 (Hz) |

**오디오 요구사항**:
- **최대 파일 크기**: 10MB
- **권장 포맷**: WebM (Opus 코덱)
- **권장 샘플레이트**: 16000 Hz (16 kHz)
- **권장 채널**: Mono (1채널)
- **권장 녹음 시간**: 3-10초

---

### 2. Server → Client: 인식 시작 알림

**메시지 타입**: `transcription_started`

```json
{
  "type": "transcription_started",
  "message": "음성 인식 중..."
}
```

**필드 설명**:

| 필드 | 타입 | 설명 |
|------|------|------|
| `type` | string | 고정값: `"transcription_started"` |
| `message` | string | 사용자 안내 메시지 |

**용도**: 
- 사용자에게 음성 인식이 시작되었음을 알림
- UI/음성 피드백 제공

---

### 3. Server → Client: 인식 완료 알림

**메시지 타입**: `transcription_complete`

```json
{
  "type": "transcription_complete",
  "transcribed_text": "사당역에서 강남역까지",
  "confidence": 0.87
}
```

**필드 설명**:

| 필드 | 타입 | 설명 |
|------|------|------|
| `type` | string | 고정값: `"transcription_complete"` |
| `transcribed_text` | string | 인식된 텍스트 (한국어) |
| `confidence` | float | 인식 신뢰도 (0.0 ~ 1.0) |

**신뢰도 해석**:
- `0.8 ~ 1.0`: 높은 신뢰도
- `0.5 ~ 0.8`: 중간 신뢰도
- `0.0 ~ 0.5`: 낮은 신뢰도 (재시도 권장)

---

### 4. Server → Client: 역 인식 완료

**메시지 타입**: `stations_recognized`

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

**필드 설명**:

| 필드 | 타입 | 설명 |
|------|------|------|
| `type` | string | 고정값: `"stations_recognized"` |
| `origin` | string | 출발지 역 이름 |
| `origin_cd` | string | 출발지 역 코드 (4자리) |
| `destination` | string | 도착지 역 이름 |
| `destination_cd` | string | 도착지 역 코드 (4자리) |
| `message` | string | 사용자 안내 메시지 |

---

### 5. Server → Client: 경로 계산 완료

**메시지 타입**: `route_calculated`

```json
{
  "type": "route_calculated",
  "route_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "origin": "사당",
  "origin_cd": "0219",
  "destination": "강남",
  "destination_cd": "0222",
  "routes": [
    {
      "rank": 1,
      "total_time": 15,
      "transfer_count": 1,
      "total_distance": 12.5,
      "path": [
        {
          "station_name": "사당",
          "station_cd": "0219",
          "line_name": "2호선",
          "action": "승차"
        },
        {
          "station_name": "교대",
          "station_cd": "0220",
          "line_name": "2호선",
          "action": "환승",
          "transfer_info": {
            "from_line": "2호선",
            "to_line": "3호선",
            "transfer_time": 3
          }
        },
        {
          "station_name": "강남",
          "station_cd": "0222",
          "line_name": "2호선",
          "action": "하차"
        }
      ],
      "score": 0.95
    }
  ],
  "total_routes_found": 5,
  "routes_returned": 3,
  "selected_route_rank": 1,
  "disability_type": "VIS",
  "input_method": "voice"
}
```

**필드 설명**:

| 필드 | 타입 | 설명 |
|------|------|------|
| `type` | string | 고정값: `"route_calculated"` |
| `route_id` | string | 경로 세션 고유 ID (UUID) |
| `origin` | string | 출발지 역 이름 |
| `origin_cd` | string | 출발지 역 코드 |
| `destination` | string | 도착지 역 이름 |
| `destination_cd` | string | 도착지 역 코드 |
| `routes` | array | 경로 목록 (최대 3개, 우선순위순) |
| `total_routes_found` | integer | 발견된 전체 경로 수 |
| `routes_returned` | integer | 반환된 경로 수 |
| `selected_route_rank` | integer | 기본 선택된 경로 순위 (1-3) |
| `disability_type` | string | 장애 유형 (고정값: `"VIS"` - 시각장애인) |
| `input_method` | string | 입력 방식 (고정값: `"voice"`) |

**경로 객체 (`routes[i]`) 필드**:

| 필드 | 타입 | 설명 |
|------|------|------|
| `rank` | integer | 경로 우선순위 (1-3) |
| `total_time` | integer | 총 소요 시간 (분) |
| `transfer_count` | integer | 환승 횟수 |
| `total_distance` | float | 총 이동 거리 (km) |
| `path` | array | 경로 상세 정보 (역별) |
| `score` | float | 경로 점수 (0.0 ~ 1.0) |

**경로 상세 (`path[i]`) 필드**:

| 필드 | 타입 | 설명 |
|------|------|------|
| `station_name` | string | 역 이름 |
| `station_cd` | string | 역 코드 |
| `line_name` | string | 호선명 (예: "2호선") |
| `action` | string | 동작 (`"승차"`, `"환승"`, `"하차"`) |
| `transfer_info` | object | 환승 정보 (action이 "환승"일 때만) |

---

### 6. Server → Client: 에러 응답

**메시지 타입**: `error`

```json
{
  "type": "error",
  "code": "NO_STATIONS_FOUND",
  "message": "역 이름을 찾을 수 없습니다.\n추천: 사당, 상왕십리, 상도"
}
```

**필드 설명**:

| 필드 | 타입 | 설명 |
|------|------|------|
| `type` | string | 고정값: `"error"` |
| `code` | string | 에러 코드 (아래 표 참조) |
| `message` | string | 사용자 친화적 에러 메시지 |

**에러 코드 목록**:

| 코드 | 의미 | 설명 | 권장 조치 |
|------|------|------|----------|
| `MISSING_AUDIO_DATA` | 필수 필드 누락 | `audio_data` 필드가 없음 | 오디오 데이터 포함하여 재전송 |
| `AUDIO_TOO_LARGE` | 파일 크기 초과 | 오디오 파일 > 10MB | 녹음 시간 단축 또는 압축 |
| `STT_FAILED` | STT 처리 실패 | Whisper 처리 중 오류 | 재시도 또는 관리자 문의 |
| `STT_NO_RESULT` | 인식 결과 없음 | 음성을 인식하지 못함 | 녹음 환경 개선 후 재시도 |
| `NO_STATIONS_FOUND` | 역 이름 파싱 실패 | 텍스트에서 역 이름 추출 실패 | 명확한 발음으로 재녹음 |
| `PARSING_ERROR` | 파싱 오류 | 역 이름 파싱 중 예외 | 재시도 |
| `ROUTE_CALCULATION_ERROR` | 경로 계산 실패 | 경로를 찾을 수 없음 | 다른 역으로 재시도 |
| `INTERNAL_ERROR` | 내부 서버 오류 | 서버 내부 오류 | 관리자 문의 |

---

## 라즈베리 파이 구현 가이드

### 하드웨어 요구사항

**최소 사양**:
- Raspberry Pi 3 Model B 이상
- RAM: 1GB 이상
- USB 마이크 또는 GPIO 마이크 모듈

**권장 사양**:
- Raspberry Pi 4 Model B (2GB RAM 이상)
- 고품질 USB 마이크 (노이즈 캔슬링 지원)
- 스피커 또는 이어폰 (음성 피드백용)

---

### 소프트웨어 요구사항

**운영체제**: Raspberry Pi OS (Debian 기반)

**필수 패키지**:
```bash
# 시스템 업데이트
sudo apt-get update
sudo apt-get upgrade -y

# 오디오 관련 패키지
sudo apt-get install -y \
    alsa-utils \
    portaudio19-dev \
    python3-pyaudio

# Python 패키지
pip3 install websockets pyaudio
```

---

### Python 클라이언트 구현 예제

#### 1. 기본 WebSocket 연결

```python
import asyncio
import websockets
import json
import uuid

async def connect_websocket():
    # 디바이스 UUID 생성 (첫 실행 시)
    device_uuid = str(uuid.uuid4())
    user_id = f"temp_{device_uuid}"
    
    # WebSocket 연결
    uri = f"ws://192.168.1.100:8001/api/v1/ws/{user_id}"
    
    async with websockets.connect(uri) as websocket:
        print(f"Connected to {uri}")
        
        # 메시지 수신 대기
        async for message in websocket:
            data = json.loads(message)
            print(f"Received: {data['type']}")
            
            if data['type'] == 'route_calculated':
                print(f"Routes found: {len(data['routes'])}")
                break

# 실행
asyncio.run(connect_websocket())
```

#### 2. 오디오 녹음 및 전송

```python
import pyaudio
import wave
import base64
import io

# 오디오 녹음 설정
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
RECORD_SECONDS = 5

def record_audio():
    """마이크로 오디오 녹음"""
    audio = pyaudio.PyAudio()
    
    # 스트림 열기
    stream = audio.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        frames_per_buffer=CHUNK
    )
    
    print("녹음 시작...")
    frames = []
    
    for i in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
        data = stream.read(CHUNK)
        frames.append(data)
    
    print("녹음 완료")
    
    # 스트림 종료
    stream.stop_stream()
    stream.close()
    audio.terminate()
    
    return frames

def frames_to_wav_base64(frames):
    """오디오 프레임을 WAV Base64로 변환"""
    # 메모리에 WAV 파일 생성
    wav_buffer = io.BytesIO()
    
    with wave.open(wav_buffer, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(pyaudio.PyAudio().get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b''.join(frames))
    
    # Base64 인코딩
    wav_buffer.seek(0)
    wav_bytes = wav_buffer.read()
    base64_audio = base64.b64encode(wav_bytes).decode('utf-8')
    
    return base64_audio

async def send_voice_input(websocket):
    """음성 입력 녹음 및 전송"""
    # 오디오 녹음
    frames = record_audio()
    
    # Base64 변환
    audio_base64 = frames_to_wav_base64(frames)
    
    # voice_input 메시지 생성
    message = {
        "type": "voice_input",
        "audio_data": audio_base64,
        "audio_format": "wav",
        "sample_rate": RATE
    }
    
    # 전송
    await websocket.send(json.dumps(message))
    print("음성 데이터 전송 완료")
```

#### 3. 전체 통합 예제

```python
import asyncio
import websockets
import json
import uuid
import pyaudio
import wave
import base64
import io

# === 설정 ===
SERVER_HOST = "192.168.1.100"
SERVER_PORT = 8001
RECORD_SECONDS = 5
RATE = 16000

# === 오디오 녹음 함수 ===
def record_audio():
    """마이크로 오디오 녹음 (5초)"""
    CHUNK = 1024
    FORMAT = pyaudio.paInt16
    CHANNELS = 1
    
    audio = pyaudio.PyAudio()
    stream = audio.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        frames_per_buffer=CHUNK
    )
    
    print("🎤 녹음 시작... (5초)")
    frames = []
    
    for i in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
        data = stream.read(CHUNK)
        frames.append(data)
    
    print("✅ 녹음 완료")
    
    stream.stop_stream()
    stream.close()
    audio.terminate()
    
    # WAV 변환
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(audio.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b''.join(frames))
    
    wav_buffer.seek(0)
    return base64.b64encode(wav_buffer.read()).decode('utf-8')

# === WebSocket 클라이언트 ===
async def voice_navigation_client():
    # 디바이스 UUID (파일로 저장하여 재사용 권장)
    device_uuid = str(uuid.uuid4())
    user_id = f"temp_{device_uuid}"
    
    uri = f"ws://{SERVER_HOST}:{SERVER_PORT}/api/v1/ws/{user_id}"
    
    print(f"🔗 서버 연결 중: {uri}")
    
    async with websockets.connect(uri) as ws:
        print("✅ 연결 성공\n")
        
        # 1. 음성 녹음
        audio_base64 = record_audio()
        
        # 2. voice_input 전송
        message = {
            "type": "voice_input",
            "audio_data": audio_base64,
            "audio_format": "wav",
            "sample_rate": RATE
        }
        
        await ws.send(json.dumps(message))
        print("📤 음성 데이터 전송 완료\n")
        
        # 3. 응답 수신
        while True:
            response = await ws.recv()
            data = json.loads(response)
            
            msg_type = data['type']
            
            if msg_type == 'transcription_started':
                print("🔄 음성 인식 중...")
            
            elif msg_type == 'transcription_complete':
                text = data['transcribed_text']
                conf = data['confidence']
                print(f"✅ 인식 완료: '{text}' (신뢰도: {conf:.2f})")
            
            elif msg_type == 'stations_recognized':
                origin = data['origin']
                dest = data['destination']
                print(f"🚇 출발: {origin} → 도착: {dest}")
            
            elif msg_type == 'route_calculated':
                routes = data['routes']
                print(f"\n📍 경로 {len(routes)}개 발견:")
                
                for route in routes:
                    rank = route['rank']
                    time = route['total_time']
                    transfer = route['transfer_count']
                    print(f"  {rank}. 소요시간 {time}분, 환승 {transfer}회")
                
                # 경로 안내 시작 가능
                print("\n✅ 경로 안내 준비 완료")
                break
            
            elif msg_type == 'error':
                code = data['code']
                message = data['message']
                print(f"❌ 에러 [{code}]: {message}")
                break

# === 실행 ===
if __name__ == "__main__":
    try:
        asyncio.run(voice_navigation_client())
    except KeyboardInterrupt:
        print("\n프로그램 종료")
    except Exception as e:
        print(f"오류 발생: {e}")
```

---

### 실행 방법

```bash
# 1. 스크립트 저장
nano voice_client.py
# (위 코드 붙여넣기)

# 2. 실행 권한 부여
chmod +x voice_client.py

# 3. 실행
python3 voice_client.py
```

**실행 화면 예시**:
```
🔗 서버 연결 중: ws://192.168.1.100:8001/api/v1/ws/temp_a1b2c3d4...
✅ 연결 성공

🎤 녹음 시작... (5초)
✅ 녹음 완료
📤 음성 데이터 전송 완료

🔄 음성 인식 중...
✅ 인식 완료: '사당역에서 강남역까지' (신뢰도: 0.87)
🚇 출발: 사당 → 도착: 강남

📍 경로 3개 발견:
  1. 소요시간 15분, 환승 1회
  2. 소요시간 18분, 환승 0회
  3. 소요시간 20분, 환승 2회

✅ 경로 안내 준비 완료
```

---

## 디바이스 UUID 영구 저장

**첫 실행 시 UUID 생성 및 저장**:

```python
import uuid
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".kindmap"
UUID_FILE = CONFIG_DIR / "device_uuid.txt"

def get_or_create_device_uuid():
    """디바이스 UUID 로드 또는 생성"""
    # 디렉토리 생성
    CONFIG_DIR.mkdir(exist_ok=True)
    
    # UUID 파일 확인
    if UUID_FILE.exists():
        with open(UUID_FILE, 'r') as f:
            device_uuid = f.read().strip()
            print(f"기존 UUID 로드: {device_uuid}")
            return device_uuid
    else:
        # 새로운 UUID 생성
        device_uuid = str(uuid.uuid4())
        with open(UUID_FILE, 'w') as f:
            f.write(device_uuid)
        print(f"새 UUID 생성: {device_uuid}")
        return device_uuid

# 사용
device_uuid = get_or_create_device_uuid()
user_id = f"temp_{device_uuid}"
```

---

## 오디오 최적화 팁 (라즈베리 파이)

### 1. 마이크 설정 확인

```bash
# 오디오 장치 목록 확인
arecord -l

# 마이크 테스트 녹음 (5초)
arecord -d 5 -f cd test.wav

# 재생 테스트
aplay test.wav
```

### 2. 노이즈 제거

```bash
# PulseAudio 설치 (노이즈 캔슬링)
sudo apt-get install pulseaudio

# 노이즈 억제 모듈 활성화
pactl load-module module-echo-cancel
```

### 3. 녹음 품질 설정

```python
# 고품질 녹음 설정
RATE = 16000          # 16kHz (음성 인식 최적)
FORMAT = paInt16      # 16-bit
CHANNELS = 1          # Mono (음성 인식용)
CHUNK = 1024          # 버퍼 크기
```

### 4. WebM 포맷 사용 (용량 절감)

```bash
# FFmpeg 설치
sudo apt-get install ffmpeg

# Python에서 WebM 변환
pip3 install pydub
```

```python
from pydub import AudioSegment

# WAV → WebM 변환
audio = AudioSegment.from_wav("recording.wav")
audio.export("recording.webm", format="webm", codec="libopus")
```

---

## 에러 처리 가이드

### 1. 연결 실패

**증상**: `ConnectionRefusedError`

**원인**:
- 서버가 실행되지 않음
- 방화벽 차단
- 잘못된 IP/포트

**해결**:
```python
import asyncio
import websockets

async def test_connection():
    try:
        uri = "ws://192.168.1.100:8001/api/v1/ws/test"
        async with websockets.connect(uri, timeout=5) as ws:
            print("✅ 연결 성공")
    except asyncio.TimeoutError:
        print("❌ 연결 타임아웃: 서버 응답 없음")
    except ConnectionRefusedError:
        print("❌ 연결 거부: 서버 미실행 또는 방화벽 차단")
    except Exception as e:
        print(f"❌ 오류: {e}")

asyncio.run(test_connection())
```

### 2. 오디오 녹음 실패

**증상**: `IOError: [Errno -9996] Invalid input device`

**원인**: 마이크 인식 실패

**해결**:
```python
import pyaudio

# 사용 가능한 오디오 장치 확인
audio = pyaudio.PyAudio()
for i in range(audio.get_device_count()):
    info = audio.get_device_info_by_index(i)
    print(f"{i}: {info['name']} (입력 채널: {info['maxInputChannels']})")

# 특정 장치 지정
stream = audio.open(
    format=FORMAT,
    channels=CHANNELS,
    rate=RATE,
    input=True,
    input_device_index=1,  # 위에서 확인한 인덱스
    frames_per_buffer=CHUNK
)
```

### 3. STT 인식 실패

**증상**: `STT_NO_RESULT` 에러

**원인**:
- 주변 소음 과다
- 마이크 음량 낮음
- 불명확한 발음

**해결**:
1. 조용한 환경에서 녹음
2. 마이크 음량 확인
   ```bash
   alsamixer  # F4: 캡처 장치 선택, 화살표로 음량 조절
   ```
3. 명확한 발음으로 재녹음
4. 녹음 시간 연장 (3-7초 권장)

### 4. 역 이름 파싱 실패

**증상**: `NO_STATIONS_FOUND` 에러

**원인**:
- 잘못된 역 이름
- 지원하지 않는 역
- 불분명한 발음

**해결**:
- 올바른 발음 예시:
  - ✅ "사당역에서 강남역까지"
  - ✅ "사당에서 강남으로"
  - ✅ "사당 강남"
  - ❌ "사땅역에서 강남역" (오타)

---

## 성능 벤치마크

### 처리 시간 (5초 오디오 기준)

| 단계 | 예상 시간 | 설명 |
|------|----------|------|
| 오디오 녹음 | ~5초 | 사용자 음성 입력 |
| Base64 인코딩 | <100ms | 라즈베리 파이에서 처리 |
| 네트워크 전송 | 100-500ms | WiFi 환경 기준 |
| STT 처리 (서버) | 3-5초 | Whisper medium 모델 (CPU) |
| 역 파싱 | <50ms | 정규식 매칭 |
| 경로 계산 | <200ms | MC-RAPTOR 알고리즘 |
| **전체 E2E** | **10-15초** | 녹음부터 경로 수신까지 |

**최적화 팁**:
- GPU 서버 사용 시: 7-10초
- 녹음 시간 단축 (3초): 8-12초

---

## 보안 및 주의사항

### 1. 네트워크 보안

**현재**: WebSocket 비암호화 (`ws://`)

**프로덕션 권장**: WSS (WebSocket Secure) 사용
```python
# HTTPS/WSS 연결
uri = "wss://api.kindmap.com:8001/api/v1/ws/temp_uuid"
```

### 2. 데이터 프라이버시

- ✅ 음성 데이터는 서버에 저장되지 않음
- ✅ STT 처리 후 즉시 삭제
- ✅ 게스트 모드: 사용자 정보 불필요

### 3. Rate Limiting

**현재**: 제한 없음

**주의**: 과도한 요청 시 서버 부하 발생 가능

**권장**: 클라이언트 측에서 요청 간격 제한
```python
import time

MIN_REQUEST_INTERVAL = 5  # 5초

last_request_time = 0

def can_make_request():
    global last_request_time
    now = time.time()
    if now - last_request_time >= MIN_REQUEST_INTERVAL:
        last_request_time = now
        return True
    return False
```

---

## 트러블슈팅

### 문제: WebSocket 연결이 자주 끊김

**해결**:
```python
# Ping/Pong으로 연결 유지
async def keep_alive(websocket):
    while True:
        await asyncio.sleep(30)  # 30초마다
        await websocket.send(json.dumps({"type": "ping"}))

# 재연결 로직
async def connect_with_retry(uri, max_retries=3):
    for attempt in range(max_retries):
        try:
            async with websockets.connect(uri) as ws:
                return ws
        except Exception as e:
            print(f"연결 실패 (시도 {attempt+1}/{max_retries}): {e}")
            await asyncio.sleep(2 ** attempt)  # 지수 백오프
    raise Exception("최대 재시도 횟수 초과")
```

### 문제: 오디오 품질 저하

**해결**:
1. 샘플레이트 확인 (16kHz 권장)
2. 마이크 거리 조절 (15-30cm)
3. 노이즈 캔슬링 활성화
4. 고품질 USB 마이크 사용

---

## 부록

### A. 지원 역 목록 확인

서버에 등록된 역 목록은 `stations.json` 파일에 정의되어 있습니다.

### B. 테스트 오디오 파일

테스트용 WAV 파일:
```bash
# 시스템 사운드로 테스트 음성 생성 (Linux)
espeak -v ko "사당역에서 강남역까지" -w test_ko.wav
```

### C. 로깅 설정

```python
import logging

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('/var/log/kindmap_device.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# 사용
logger.info("WebSocket 연결 시작")
logger.error(f"에러 발생: {error}")
```

---

## 문의

**기술 지원**: 
- 이슈 발생 시 로그 파일 첨부
- 재현 방법 상세 기술
- 라즈베리 파이 모델 및 OS 버전 명시

**문서 버전**: 1.0  
**마지막 업데이트**: 2024-12-07
