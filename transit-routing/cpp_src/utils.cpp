#include "utils.h"
#include <algorithm>

namespace pathfinding
{

    ANPWeights PathfindingUtils::calculate_anp_weights(const std::string &type)
    {
        // Python에서 미리 계산한 ANP 가중치 (사전 계산된 값)
        // 각 장애 유형별로 5가지 기준에 대한 정규화된 가중치
        // 순서: travel_time, transfers, transfer_difficulty, convenience, congestion

        static const std::unordered_map<std::string, ANPWeights> WEIGHTS = {
            {"PHY", {0.0543, 0.4826, 0.2391, 0.1196, 0.1044}}, // 휠체어: 환승 > 난이도 > 편의성 > 혼잡도 > 시간
            {"VIS", {0.0623, 0.1198, 0.2043, 0.4938, 0.1198}}, // 저시력: 편의성 > 난이도 > 환승 > 혼잡도 > 시간
            {"AUD", {0.1519, 0.2938, 0.0823, 0.3897, 0.0823}}, // 청각장애: 편의성 > 환승 > 시간 > 난이도 > 혼잡도
            {"ELD", {0.0739, 0.1304, 0.2174, 0.0609, 0.5174}}  // 고령자: 혼잡도 > 난이도 > 환승 > 편의성 > 시간
        };

        auto it = WEIGHTS.find(type);
        if (it != WEIGHTS.end())
        {
            return it->second;
        }

        // 기본값: PHY (휠체어)
        return WEIGHTS.at("PHY");
    }

    double PathfindingUtils::calculate_transfer_difficulty(
        double distance,
        const FacilityScores &scores,
        const std::string &type,
        const std::unordered_map<std::string, double> &prefs)
    {
        // 거리 점수 계산 (0.0 ~ 1.0)
        // 300m 이상이면 1.0 (최대 난이도)
        double distance_score = std::min(distance / 300.0, 1.0);

        // 편의 점수 계산 (0.0 ~ 5.0 범위)
        DisabilityType dtype = str_to_disability(type);
        const auto &weights = get_facility_weights(dtype);

        double convenience_raw =
            scores.chargers * weights.charger +
            scores.elevators * weights.elevator +
            scores.escalators * weights.escalator +
            scores.lifts * weights.lift +
            scores.movingWalks * weights.movingwalk +
            scores.safePlatforms * weights.safe_platform +
            scores.signPhones * weights.sign_phone +
            scores.toilets * weights.toilet +
            scores.helpers * weights.helper;

        // Sigmoid 정규화 후 0-5 범위로 변환
        double convenience_score = normalize_score(convenience_raw);

        // 불편함 점수 (편의성의 역수, 0.0 ~ 1.0)
        double inconvenience_score = 1.0 - (convenience_score / 5.0);

        // 환승 난이도 = 60% 거리 + 40% 불편함
        // Python 로직과 동일 (anp_weights.py:279)
        double difficulty = 0.6 * distance_score + 0.4 * inconvenience_score;

        return difficulty;
    }

} // namespace pathfinding
