#pragma once

#define _USE_MATH_DEFINES
#include <cmath>
#include <ctime>
#include <string>
#include <unordered_map>
#include "types.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

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

        // Disablility Type 변환
        static inline DisabilityType str_to_disability(const std::string &type)
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

        // 편의시설 별 가중치 구조체
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

        // 교통약자별 가중치 반환 (코드 내 정의)
        // 0.0 : 없어도 됨(상관 없음) <-> 3.0 : 있으면 좋음 <-> 5.0 : 있어야 함
        // 교통약자 도우미의 경우, 어떤 유형이든 선호함
        static const FacilityWeights &get_facility_weights(DisabilityType type)
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

        // 편의시설 점수 정규화 Sigmoid
        static inline double normalize_score(double raw_score){
            return 1.0 / (1.0 + std::exp(-3.0 * raw_score));
        }

        static double
        get_epsilon(const std::string &type)
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

        static double calculate_transfer_difficulty(
            double distance,
            const FacilityScores &scores,
            const std::string &type,
            const std::unordered_map<std::string, double> &prefs);

        // congestion 조회 시 사용되는 시간
        static inline std::string get_day_type(double timestamp)
        {
            std::time_t t = static_cast<std::time_t>(timestamp);
            std::tm *tm = std::localtime(&t);
            int weekday = tm->tm_wday; // 0=일요일, 1=월요일, ..., 6=토요일

            if (weekday >= 1 && weekday <= 5)
                return "weekday";
            else if (weekday == 6)
                return "sat";
            else
                return "sun";
        }

        static inline std::string get_time_column(double timestamp)
        {
            std::time_t t = static_cast<std::time_t>(timestamp);
            std::tm *tm = std::localtime(&t);

            int minutes_from_midnight = tm->tm_hour * 60 + tm->tm_min;
            int slot_minutes = (minutes_from_midnight / 30) * 30; // 30분 단위 내림

            return "t_" + std::to_string(slot_minutes);
        }

        // 방향 변환 유틸리티 inline
        static inline Direction str_to_direction(const std::string &dir)
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

        static inline std::string direction_to_str(Direction dir)
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
    };
} // namespace pathfinding