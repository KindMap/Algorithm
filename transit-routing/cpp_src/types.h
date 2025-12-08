#pragma once
#include <string>
#include <vector>
#include <unordered_map>
#include <cstdint>
#include <tuple>
#include <array>

namespace pathfinding
{
    // 최적화된 타입 정의
    using StationID = uint16_t;
    using LabelIndex = int32_t;

    // 방향 Enum (1 byte)
    enum class Direction : uint8_t
    {
        UP = 0,
        DOWN = 1,
        IN = 2,
        OUT = 3,
        UNKNOWN = 255
    };

    // 장애 유형 Enum
    enum class DisabilityType : uint8_t
    {
        PHY = 0,
        VIS = 1,
        AUD = 2,
        ELD = 3,
        COUNT = 4
    };

    // ANP 가중치
    struct ANPWeights
    {
        double travel_time;
        double transfers;
        double transfer_difficulty;
        double convenience;
        double congestion;
    };

    // 역 정보
    struct StationInfo
    {
        StationID id;
        std::string station_cd;
        std::string name;
        std::string line;
        double latitude;
        double longitude;
    };

    // 편의시설 점수 (로딩용)
    struct FacilityScores
    {
        double charger = 0.0;
        double elevator = 0.0;
        double escalator = 0.0;
        double lift = 0.0;
        double movingwalk = 0.0;
        double safe_platform = 0.0;
        double sign_phone = 0.0;
        double toilet = 0.0;
        double helper = 0.0;
    };

    // 환승 데이터 (거리 정보만 유지, 점수는 역 단위로 통합)
    struct TransferData
    {
        double distance;
    };

    // Label (Memory Pool 최적화)
    struct Label
    {
        double arrival_time;
        int transfers;
        double convenience_sum; // 경로상 환승역들의 점수 합
        double congestion_sum;
        double max_transfer_difficulty;

        LabelIndex parent_index; // 포인터 대신 인덱스
        StationID station_id;    // 문자열 대신 정수 ID

        Direction direction;      // Enum 사용
        std::string current_line; // 노선명

        int depth;
        bool is_first_move;
        int created_round;

        // 정렬용 점수 캐시
        double score_cache = -1.0;

        double avg_convenience() const { return depth > 0 ? convenience_sum / depth : 0.0; }
        double avg_congestion() const { return depth > 0 ? congestion_sum / depth : 0.0; }
    };

} // namespace pathfinding