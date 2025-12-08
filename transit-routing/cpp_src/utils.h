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
        // [Inline 유지] 간단한 수학 연산
        static inline double haversine(double lat1, double lon1, double lat2, double lon2)
        {
            constexpr double R = 6371000.0;
            constexpr double TO_RAD = 3.14159265358979323846 / 180.0;
            double dLat = (lat2 - lat1) * TO_RAD;
            double dLon = (lon2 - lon1) * TO_RAD;
            double a = std::sin(dLat / 2) * std::sin(dLat / 2) +
                       std::cos(lat1 * TO_RAD) * std::cos(lat2 * TO_RAD) *
                           std::sin(dLon / 2) * std::sin(dLon / 2);
            double c = 2 * std::atan2(std::sqrt(a), std::sqrt(1 - a));
            return R * c;
        }

        static inline double normalize_score(double raw_score)
        {
            return 1.0 / (1.0 + std::exp(-0.3 * raw_score));
        }

        // [선언만 남김] 구현부는 utils.cpp로 이동
        static Direction str_to_direction(const std::string &dir);
        static std::string direction_to_str(Direction dir);

        static DisabilityType str_to_disability(const std::string &type);

        struct FacilityWeights
        {
            double charger;
            double elevator;
            double escalator;
            double lift;
            double movingwalk;
            double safe_platform;
            double sign_phone;
            double toilet;
            double helper;
        };

        static const FacilityWeights &get_facility_weights(DisabilityType type);
        static ANPWeights calculate_anp_weights(const std::string &type);
        static double calculate_transfer_difficulty(double distance, double convenience_sum, const std::string &type);

        static double get_epsilon(const std::string &type);
        static double get_walking_speed(const std::string &type);

        static std::string get_day_type(double timestamp);
        static std::string get_time_column(double timestamp);
    };
}