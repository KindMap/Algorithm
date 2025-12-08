#pragma once
#include <cmath>
#include <string>
#include <unordered_map>
#include "types.h"

namespace pathfinding
{

    class PathfindingUtils
    {
    public:
        static inline double haversine(double lat1, double lon1, double lat2, double lon2)
        {
            constexpr double R = 6371000.0;
            constexpr double TO_RAD = M_PI / 180.0;
            double dLat = (lat2 - lat1) * TO_RAD;
            double dLon = (lon2 - lon1) * TO_RAD;
            double a = std::sin(dLat / 2) * std::sin(dLat / 2) +
                       std::cos(lat1 * TO_RAD) * std::cos(lat2 * TO_RAD) *
                           std::sin(dLon / 2) * std::sin(dLon / 2);
            double c = 2 * std::atan2(std::sqrt(a), std::sqrt(1 - a));
            return R * c;
        }

        // ANP 가중치 및 설정(보행 속도, epsilon)값 조회
        static ANPWeights calculate_anp_weights(const std::string &type);

        static double get_epsilon(const std::string &type)
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

        static double get_walking_speed(const std::string &type)
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

        static double calculate_convenience_score(
            const std::string &type,
            const FacilityScores &scores,
            const std::unordered_map<std::string, double> &prefs);

        static double calculate_transfer_difficulty(
            double distance,
            const FacilityScores &scores,
            const std::string &type,
            const std::unordered_map<std::string, double> &prefs);

        // congestion 조회 시 사용되는 시간
        static std::string get_day_type(double timestamp);
        static std::string get_time_column(double timestamp);
    };
} // namespace pathfinding