#pragma once
#include <string>
#include <vector>
#include <unordered_map>
#include <cstdint>
#include <tuple>
#include <array>

namespace pathfinding
{
    // type alias 정의
    // => uint16_t : stationID 매핑!!!
    using StationID = uint16_t;
    using LabelIndex = int32_t;

    // 방향을 위한 Enum
    enum class Direction : uint8_t
    {
        UP = 0,   // 상행
        DOWN = 1, // 하행
        IN = 2,   // 내선 순환
        OUT = 3,  // 외선 순환
        UNKNOWN = 255
    };

    enum class DisabilityType : uint8_t
    {
        PHY = 0,
        VIS = 1,
        AUD = 2,
        ELD = 3,
        COUNT = 4
    };

    // ANP weights
    struct ANPWeights
    {
        double travel_time;
        double transfers;
        double transfer_difficulty;
        double convenience;
        double congestion;
    };

    // station info => meta data
    struct StationInfo
    {
        StationID id;
        std::string station_cd; // 원본 역 코드 복구용
        std::string name;
        std::string line;
        double latitude;
        double longitude;
    };

    // 편의시설 점수
    // => C++로 성능향상 했으니, DB에서 1시간마다 조회해서 실시간 정보를 사용할 수 있도록 조정
    struct FacilityScores
    {
        double elevators = 0.0;
        double escalators = 0.0;
        double toilets = 0.0; // 장애인 화장실
        double lifts = 0.0;
        double movingWalks = 0.0;
        double chargers = 0.0;      // 휠체어 급속 충전기
        double signPhones = 0.0;    // 수어 영상 전화기
        double safePlatforms = 0.0; // 안전 발판
        double helpers = 0.0;       // 교통약자 도우미
    };

    struct TransferData
    {
        double distance;
        FacilityScores facility_scores; // 환승역의 편의시설 점수 (환승 난이도 계산에 사용)
    };

    // Label class(Memory pool용, 48~64 bytes packed)
    struct Label
    {
        double arrival_time;
        int transfers;
        double convenience_sum; // 경로 상 환승역들의 점수 합
        double congestion_sum;
        double max_transfer_difficulty;

        LabelIndex parent_index;   // pointer => index로 관리
        StationID station_id;      // string => uint16_t
        StationID prev_station_id; // 환승 판단용 이전 역 ID

        Direction direction; // string => Enum 사용

        // line 정보는 문자열로 유지 => 내부 비교 최소화
        // 추후 dataloader에서 관리하는 String Pool의 인덱스 사용으로 수정할 것
        std::string current_line;

        int depth;
        bool is_first_move;
        int created_round;

        double score_cache = -1.0; // 정렬용 점수 캐시

        double avg_convenience() const { return depth > 0 ? convenience_sum / depth : 0.0; }
        double avg_congestion() const
        {
            return depth > 0 ? congestion_sum / depth : 0.0;
        }
    };

} // namespace pathfinding