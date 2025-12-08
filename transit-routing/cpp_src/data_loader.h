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

        // 경로 복원용 중간역 반환
        std::vector<StationID> get_intermediate_stations(
            StationID from_id, StationID to_id, const std::string &line) const;

        // 역별 편의시설 점수 조회
        double get_station_convenience(StationID sid, DisabilityType type) const
        {
            if (sid >= station_scores_.size())
                return 0.0;
            return station_scores_[sid][static_cast<int>(type)];
        }

        // Getters
        StationID get_id(const std::string &cd) const;
        std::string get_code(StationID id) const;
        const StationInfo &get_station(StationID id) const;
        const std::vector<std::string> &get_lines(StationID id) const;

        struct DirectionLines
        {
            std::vector<StationID> up;
            std::vector<StationID> down;
        };
        const DirectionLines &get_next_stations(StationID id, const std::string &line) const;

        const TransferData *get_transfer(StationID from, const std::string &f_line, const std::string &t_line) const;

        double get_congestion(StationID id, const std::string &line, Direction dir,
                              const std::string &day, const std::string &time_col) const;

        mutable std::shared_mutex update_mutex;

    private:
        std::unordered_map<std::string, StationID> code_to_id_;
        std::vector<std::string> id_to_code_;

        std::vector<StationInfo> stations_;
        std::vector<std::vector<std::string>> station_lines_;

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
        std::unordered_map<LineStationKey, DirectionLines, LineStationHash> line_topology_;

        // 중간역 복원을 위한 순서 데이터
        std::unordered_map<LineStationKey, int, LineStationHash> station_orders_;
        std::unordered_map<std::string, std::vector<std::pair<int, StationID>>> line_ordered_stations_;

        struct TransferKey
        {
            StationID sid;
            std::string f_line;
            std::string t_line;
            bool operator==(const TransferKey &o) const { return sid == o.sid && f_line == o.f_line && t_line == o.t_line; }
        };
        struct TransferHash
        {
            size_t operator()(const TransferKey &k) const { return std::hash<StationID>{}(k.sid); }
        };
        std::unordered_map<TransferKey, TransferData, TransferHash> transfers_;

        struct CongestionKey
        {
            StationID sid;
            std::string line;
            Direction dir;
            std::string day;
            bool operator==(const CongestionKey &o) const { return sid == o.sid && line == o.line && dir == o.dir && day == o.day; }
        };
        struct CongestionHash
        {
            size_t operator()(const CongestionKey &k) const { return std::hash<StationID>{}(k.sid) ^ (static_cast<size_t>(k.dir) << 8); }
        };
        std::unordered_map<CongestionKey, std::unordered_map<std::string, double>, CongestionHash> congestion_;

        std::vector<std::array<double, 4>> station_scores_;
    };
}