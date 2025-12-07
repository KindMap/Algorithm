import re
import json
import logging
import difflib
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class StationParseResult:
    origin: Optional[str] = None
    origin_cd: Optional[str] = None
    destination: Optional[str] = None
    destination_cd: Optional[str] = None
    confidence: float = 0.0
    raw_text: str = ""
    parse_method: str = ""

    @property
    def is_valid(self) -> bool:
        return bool(self.origin_cd and self.destination_cd)


class StationParserService:
    """
    JSON 파일 기반 역 이름 파싱 서비스
    지원 데이터 포맷: [{"name": "제물포", "station_cd": "1810", "line": "1호선"}, ...]
    """

    PATTERNS = [
        # "사당역에서 강남역까지"
        re.compile(
            r"(?P<origin>[가-힣0-9]+)\s*역?\s*(?:에서|부터)\s*(?P<destination>[가-힣0-9]+)\s*역?\s*(?:까지|로|으로|갈게요|가줘)?"
        ),
        # "사당 강남"
        re.compile(
            r"(?P<origin>[가-힣0-9]+)\s*역?\s+(?P<destination>[가-힣0-9]+)\s*역?"
        ),
    ]

    def __init__(self):
        """
        초기화 시 JSON 리스트를 읽어 O(1) 검색 가능한 딕셔너리로 변환
        """
        # self.station_db 구조: {"제물포": "1810", "강남": "0222", ...}
        self.station_db: Dict[str, str] = self._load_and_transform_data()
        self.station_names = list(self.station_db.keys())

    def _load_and_transform_data(self) -> Dict[str, str]:
        """
        JSON 리스트를 읽어서 Name->Code 맵으로 변환
        """
        path = Path(settings.STATION_DATA_PATH)
        lookup_table = {}

        try:
            if not path.exists():
                logger.warning(
                    f"Station data file not found at: {path}. Using empty DB."
                )
                return {}

            with open(path, "r", encoding="utf-8") as f:
                raw_list = json.load(f)  # List[Dict] 형태 로드

                if not isinstance(raw_list, list):
                    logger.error("JSON data is not a list format.")
                    return {}

                count = 0
                for item in raw_list:
                    # 데이터 추출 (키 이름이 데이터에 따라 다를 수 있으니 .get 사용)
                    name = item.get("name")
                    code = item.get("station_cd")

                    if name and code:
                        # 이미 존재하는 역 이름이라도 덮어쓰거나 무시 (환승역 처리)
                        # 여기서는 단순화를 위해 마지막 값을 사용하거나
                        # 필요 시 {"name": ["code1", "code2"]} 형태로 확장 가능
                        lookup_table[name] = code
                        count += 1

                logger.info(f"Loaded {count} stations mapped from {path}")
                return lookup_table

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON format in {path}: {e}")
            return {}
        except Exception as e:
            logger.error(f"Failed to load station data: {e}")
            return {}

    def parse(self, text: str) -> StationParseResult:
        clean_text = text.strip()

        # 1. 정규식 패턴 매칭
        for pattern in self.PATTERNS:
            match = pattern.search(clean_text)
            if match:
                origin_name, origin_cd = self._get_station_info(match.group("origin"))
                dest_name, dest_cd = self._get_station_info(match.group("destination"))

                if origin_cd and dest_cd:
                    return StationParseResult(
                        origin=origin_name,
                        origin_cd=origin_cd,
                        destination=dest_name,
                        destination_cd=dest_cd,
                        confidence=0.9,
                        raw_text=text,
                        parse_method="regex_pattern",
                    )

        # 2. Fuzzy Split ("사당강남")
        no_space_text = clean_text.replace(" ", "")
        fuzzy_result = self._fuzzy_split_stations(no_space_text)
        if fuzzy_result.is_valid:
            fuzzy_result.raw_text = text
            return fuzzy_result

        return StationParseResult(raw_text=text, confidence=0.0)

    def _get_station_info(self, name: str) -> Tuple[Optional[str], Optional[str]]:
        """
        입력된 텍스트('제물포역')를 정규화('제물포')하여 코드 조회
        """
        if not name:
            return None, None

        # '역' 접미사 제거
        clean_name = name[:-1] if name.endswith("역") else name

        code = self.station_db.get(clean_name)
        if code:
            return clean_name, code
        return None, None

    def _fuzzy_split_stations(self, text: str) -> StationParseResult:
        # 접미사 제거 (전처리)
        for suffix in ["으로", "까지", "가자", "갈래", "갈게요"]:
            if text.endswith(suffix):
                text = text[: -len(suffix)]
                break

        length = len(text)
        # i를 기준으로 문자열을 좌/우로 나눔
        for i in range(1, length):
            left = text[:i]
            right = text[i:]

            org_name, org_cd = self._get_station_info(left)
            dst_name, dst_cd = self._get_station_info(right)

            if org_cd and dst_cd:
                return StationParseResult(
                    origin=org_name,
                    origin_cd=org_cd,
                    destination=dst_name,
                    destination_cd=dst_cd,
                    confidence=0.7,
                    parse_method="fuzzy_split",
                )
        return StationParseResult(confidence=0.0)

    def suggest_corrections(self, text: str, limit: int = 3) -> List[Dict]:
        """유사 역 이름 제안"""
        clean_input = text.replace("역", "").strip()
        matches = difflib.get_close_matches(
            clean_input, self.station_names, n=limit, cutoff=0.4
        )

        return [
            {
                "name": match,
                "code": self.station_db[match],
                "match_ratio": difflib.SequenceMatcher(
                    None, clean_input, match
                ).ratio(),
            }
            for match in matches
        ]


_station_parser_service: Optional[StationParserService] = None


def get_station_parser_service() -> StationParserService:
    """station parser 서비스 싱글톤 인스턴스 반환"""
    global _station_parser_service
    if _station_parser_service is None:
        _station_parser_service = StationParserService()
    return _station_parser_service
