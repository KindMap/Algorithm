#pragma once
#include "types.h"
#include <vector>
#include <string>
#include <unordered_map>
#include <shared_mutex>
#include <array>
#include <pybind11/pybind11.h>

namespace py = pybind11;

namespace pathfinding
{

    class DataContainer
    {
    public:
        void load_from_python(
            const py::dict &stations,
            const py::dict &line_stations,
            const py::dict &station_order,
            const py::dict &transfers,
            const py::dict &congestion);

        // 실시간 업데이트 (List of dicts)
        void update_facility_scores(const py::list &facility_rows);

        // 역별 편의시설 점수 조회 (O(1))
        double get_station_convenience(StationID sid, DisabilityType type) const
        {
            if (sid >= station_scores_.size())
                return 0.0;
            return station_scores_[sid][static_cast<int>(type)];
        }

        // ID 매핑
        StationID get_id(const std::string &cd) const;
        std::string get_code(StationID id) const;

        // 데이터 조회
        const StationInfo &get_station(StationID id) const;
        const std::vector<std::string> &get_lines(StationID id) const;

        struct DirectionLines
        {
            std::vector<StationID> up;   // 해당 역에서 상행 방향으로 이동했을 때, 도달 가능한 역들의 배열
            std::vector<StationID> down; // '' 하행
        };
        const DirectionLines &get_next_stations(StationID id, const std::string &line) const;

        const TransferData *get_transfer(StationID from, const std::string &f_line, const std::string &t_line) const;

        double get_congestion(StationID id, const std::string &line, Direction dir,
                              const std::string &day, const std::string &time_col) const;

        // Read-Write Lock => concurrency 제어
        mutable std::shared_mutex update_mutex;

    private:
        std::unordered_map<std::string, StationID> code_to_id;
        std::vector<std::string> id_to_code;

        std::vector<StationInfo> stations_;
        std::vector<std::vector<std::string>> station_lines_; // 해당 역에서 갈 수 있는 모든 노선

        struct LineStationKey
        {
            StationID sid;
            std::string line;
            bool operator==(const LineStationKey &o) const { return sid == o.sid && line == o.line; }
        };
        struct LineStationHash
        {
            size_t operator()(const LineStationKey &k) const { return std::hash<StationID>{}(k.sid) ^ std::hash<std::string>{}(k.line); }
        };
        std::unordered_map<LineStationKey, DirectionLines, LineStationHash> line_topology_; // 사전 계산된 그래프

        // Transfer Key
        struct TransferKey
        {
            StationID sid;
            std::string f_line; // from line
            std::string t_line; // to line
            bool operator==(const TransferKey &o) const
            {
                return sid == o.sid && f_line == o.f_line && t_line == o.t_line;
            }
        };

        struct TransferHash
        {
            size_t operator()(const TransferKey &k) const
            {
                return std::hash<StationID>{}(k.sid);
            }
        };

        struct CongestionKey
        {
            StationID sid;
            std::string line;
            Direction dir;
            std::string day;
            bool operator==(const CongestionKey &o) const
            {
                return sid == o.sid && line == o.line && dir == o.dir && day == o.day;
            }
        };

        struct CongestionHash
        {
            size_t operator()(const CongestionKey &k) const
            {
                // StationID와 Direction을 비트 연산으로 합쳐서 고유 해시 생성 가능
                // 예: (sid << 8) | (uint8_t)dir
                return std::hash<StationID>{}(k.sid) ^ (std::hash<uint8_t>{}(static_cast<uint8_t>(k.dir)) << 1);
            }
        };

        std::unordered_map<CongestionKey, std::unordered_map<std::string, double>, CongestionHash> congestion_;

        // 역 별 편의시설 점수
        std::vector<std::array<double, 4>> station_scores_;
    };
} // namespace pathfinding