#include "utils.h"
#include <algorithm>
#include <ctime>
#include <vector>

namespace pathfinding
{
    // Direction 변환
    Direction PathfindingUtils::str_to_direction(const std::string &dir)
    {
        if (dir == "up")
            return Direction::UP;
        if (dir == "down")
            return Direction::DOWN;
        if (dir == "in")
            return Direction::IN;
        if (dir == "out")
            return Direction::OUT;
        return Direction::UNKNOWN;
    }

    std::string PathfindingUtils::direction_to_str(Direction dir)
    {
        switch (dir)
        {
        case Direction::UP:
            return "up";
        case Direction::DOWN:
            return "down";
        case Direction::IN:
            return "in";
        case Direction::OUT:
            return "out";
        default:
            return "";
        }
    }

    // Disability Type 변환
    DisabilityType PathfindingUtils::str_to_disability(const std::string &type)
    {
        if (type == "PHY")
            return DisabilityType::PHY;
        if (type == "VIS")
            return DisabilityType::VIS;
        if (type == "AUD")
            return DisabilityType::AUD;
        if (type == "ELD")
            return DisabilityType::ELD;
        return DisabilityType::PHY;
    }

    // 교통약자별 가중치 반환 (코드 내 정의)

    // 0.0 : 없어도 됨(상관 없음) <-> 3.0 : 있으면 좋음 <-> 5.0 : 있어야 함

    // 교통약자 도우미의 경우, 어떤 유형이든 선호함

    const PathfindingUtils::FacilityWeights &PathfindingUtils::get_facility_weights(DisabilityType type)
    {
        static const FacilityWeights W_PHY = {3.0, 5.0, 3.0, 2.0, 2.0, 5.0, 0.0, 3.0, 4.0};
        static const FacilityWeights W_VIS = {0.0, 3.0, 3.0, 0.0, 2.0, 5.0, 0.0, 0.0, 4.0};
        static const FacilityWeights W_AUD = {0.0, 3.0, 3.0, 0.0, 2.0, 3.0, 4.5, 0.0, 4.0};
        static const FacilityWeights W_ELD = {0.0, 4.0, 4.0, 0.0, 4.0, 4.0, 0.0, 1.0, 4.0};

        switch (type)

        {
        case DisabilityType::PHY:
            return W_PHY;
        case DisabilityType::VIS:
            return W_VIS;
        case DisabilityType::AUD:
            return W_AUD;
        case DisabilityType::ELD:
            return W_ELD;
        default:
            return W_PHY;
        }
    }

    // ANP 가중치 계산
    ANPWeights PathfindingUtils::calculate_anp_weights(const std::string &type)
    {
        // {travel_time, transfers, transfer_difficulty, convenience, congestion}
        if (type == "PHY")
            return {0.0543, 0.4826, 0.2391, 0.1196, 0.1044};
        if (type == "VIS")
            return {0.0623, 0.1198, 0.2043, 0.4938, 0.1198};
        if (type == "AUD")
            return {0.1519, 0.2938, 0.0823, 0.3897, 0.0823};
        if (type == "ELD")
            return {0.0739, 0.1304, 0.2174, 0.0609, 0.5174};
        return {0.2, 0.2, 0.2, 0.2, 0.2}; // Default
    }

    // 환승 난이도 계산
    double PathfindingUtils::calculate_transfer_difficulty(double distance, double convenience_sum, const std::string &type)
    {
        double dist_score = std::min(distance / 300.0, 1.0);

        // 편의도 역수 (편의도가 높을수록 난이도 하락)
        double conv_factor = 1.0;
        if (convenience_sum > 0.01)
        {
            conv_factor = 1.0 / (1.0 + convenience_sum);
        }

        // 6:4 비율 적용 (기존 로직 유지)
        return 0.6 * dist_score + 0.4 * conv_factor;
    }

    double PathfindingUtils::get_epsilon(const std::string &type)
    {
        if (type == "PHY")
            return 0.06;
        if (type == "VIS")
            return 0.08;
        if (type == "AUD")
            return 0.10;
        if (type == "ELD")
            return 0.08;
        return 0.05;
    }

    double PathfindingUtils::get_walking_speed(const std::string &type)
    {
        if (type == "PHY")
            return 0.50;
        if (type == "VIS")
            return 0.80;
        if (type == "AUD")
            return 0.98;
        if (type == "ELD")
            return 0.70;
        return 0.98;
    }

    std::string PathfindingUtils::get_day_type(double timestamp)
    {
        std::time_t t = static_cast<std::time_t>(timestamp);
        std::tm *tm_ptr = std::localtime(&t);

        // Windows/Linux 호환성을 위해 localtime_r 또는 localtime_s 권장되나
        // 표준 C++에서는 localtime 후 즉시 사용하면 됨 (Thread-safe issue 주의)
        if (tm_ptr->tm_wday == 0)
            return "sun";
        if (tm_ptr->tm_wday == 6)
            return "sat";
        return "weekday";
    }

    std::string PathfindingUtils::get_time_column(double timestamp)
    {
        std::time_t t = static_cast<std::time_t>(timestamp);
        std::tm *tm_ptr = std::localtime(&t);

        // 30분 단위 슬롯 (0~1410)
        int slot = (tm_ptr->tm_hour * 60 + tm_ptr->tm_min) / 30 * 30;
        return "t_" + std::to_string(slot);
    }
}