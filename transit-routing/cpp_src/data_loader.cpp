#include "data_loader.h"
#include "utils.h"
#include <algorithm>
#include <mutex>
#include <iostream>

namespace pathfinding
{
    void DataContainer::load_from_python(
        const py::dict &stations_dict, const py::dict &line_stations_dict,
        const py::dict &station_order_dict, const py::dict &transfers_dict,
        const py::dict &congestion_dict)
    {
        // stations
        size_t count = stations_dict.size();
        stations_.reserve(count);
        id_to_code_.reserve(count);
        station_lines_.resize(count);
        station_scores_.assign(count, {0.0, 0.0, 0.0, 0.0}); // convenience score 초기화

        StationID current_id = 0;
        for (auto item : stations_dict)
        {
            std::string cd = py::str(item.first);
            if (code_to_id_.find(cd) == code_to_id_.end())
            {
                code_to_id_[cd] = current_id;
                id_to_code_.push_back(cd);

                py::dict info = item.second.cast<py::dict>();
                StationInfo s;
                s.id = current_id;
                s.station_cd = cd;
                s.name = py::str(info["station_name"]);
                s.line = py::str(info["line"]);
                s.latitude = info["latitude"].cast<double>();
                s.longitude = info["longitude"].cast<double>();

                stations_.push_back(s);
                current_id++;
            }
        }

        for (auto item : station_order_dict)
        {
            py::tuple key = item.first.cast<py::tuple>();
            std::string cd = py::str(key[0]);
            std::string line = py::str(key[1]);
            int order = item.second.cast<int>();

            if (code_to_id_.find(cd) != code_to_id_.end())
            {
                StationID sid = code_to_id_[cd];
                // (StationID, Line) -> Order 저장
                station_orders_[{sid, line}] = order;
                // Line -> List[(Order, StationID)] 저장
                line_ordered_stations_[line].push_back({order, sid});
            }
        }

        // 라인별 역 리스트 정렬 (순서 기반 검색을 위해)
        for (auto &kv : line_ordered_stations_)
        {
            std::sort(kv.second.begin(), kv.second.end());
        }

        // Line Topology
        for (auto item : line_stations_dict)
        {
            py::tuple key = item.first.cast<py::tuple>();
            std::string cd = py::str(key[0]);
            std::string line = py::str(key[1]);

            if (code_to_id_.find(cd) == code_to_id_.end())
                continue;
            StationID sid = code_to_id_[cd];

            py::dict dirs = item.second.cast<py::dict>();
            DirectionLines dl;
            if (dirs.contains("up"))
            {
                for (auto n : dirs["up"].cast<py::list>())
                {
                    std::string n_cd = py::str(n);
                    if (code_to_id_.count(n_cd))
                        dl.up.push_back(code_to_id_[n_cd]);
                }
            }
            if (dirs.contains("down"))
            {
                for (auto n : dirs["down"].cast<py::list>())
                {
                    std::string n_cd = py::str(n);
                    if (code_to_id_.count(n_cd))
                        dl.down.push_back(code_to_id_[n_cd]);
                }
            }
            line_topology_[{sid, line}] = dl;
        }

        // station_lines_ 채우기: 각 역에서 이용 가능한 노선 목록 구축
        for (const auto &pair : line_topology_)
        {
            const LineStationKey &key = pair.first;
            StationID sid = key.sid;
            const std::string &line = key.line;

            // 해당 역의 노선 목록에 추가 (중복 방지)
            auto &lines = station_lines_[sid];
            if (std::find(lines.begin(), lines.end(), line) == lines.end())
            {
                lines.push_back(line);
            }
        }

        // Transfers
        for (auto item : transfers_dict)
        {
            py::tuple key = item.first.cast<py::tuple>();
            std::string cd = py::str(key[0]);
            if (code_to_id_.find(cd) == code_to_id_.end())
                continue;

            StationID sid = code_to_id_[cd];
            std::string f_line = py::str(key[1]);
            std::string t_line = py::str(key[2]);

            py::dict val = item.second.cast<py::dict>();
            TransferData td;
            td.distance = val["transfer_distance"].cast<double>();

            // facility_scores 파싱 (optional)
            if (val.contains("facility_scores"))
            {
                py::dict fac = val["facility_scores"].cast<py::dict>();
                td.facility_scores.elevators = fac.contains("elevators") ? fac["elevators"].cast<double>() : 0.0;
                td.facility_scores.escalators = fac.contains("escalators") ? fac["escalators"].cast<double>() : 0.0;
                td.facility_scores.toilets = fac.contains("toilets") ? fac["toilets"].cast<double>() : 0.0;
                td.facility_scores.lifts = fac.contains("lifts") ? fac["lifts"].cast<double>() : 0.0;
                td.facility_scores.movingWalks = fac.contains("movingWalks") ? fac["movingWalks"].cast<double>() : 0.0;
                td.facility_scores.chargers = fac.contains("chargers") ? fac["chargers"].cast<double>() : 0.0;
                td.facility_scores.signPhones = fac.contains("signPhones") ? fac["signPhones"].cast<double>() : 0.0;
                td.facility_scores.safePlatforms = fac.contains("safePlatforms") ? fac["safePlatforms"].cast<double>() : 0.0;
                td.facility_scores.helpers = fac.contains("helpers") ? fac["helpers"].cast<double>() : 0.0;
            }

            transfers_[{sid, f_line, t_line}] = td;
        }

        // Congestion
        for (auto item : congestion_dict)
        {
            py::tuple key = item.first.cast<py::tuple>();
            std::string cd = py::str(key[0]);
            if (code_to_id_.find(cd) == code_to_id_.end())
                continue;

            StationID sid = code_to_id_[cd];
            std::string line = py::str(key[1]);
            std::string dir_str = py::str(key[2]);
            std::string day = py::str(key[3]);

            Direction dir = PathfindingUtils::str_to_direction(dir_str);

            py::dict slots = item.second.cast<py::dict>();
            std::unordered_map<std::string, double> slot_map;
            for (auto slot : slots)
            {
                slot_map[py::str(slot.first)] = slot.second.cast<double>();
            }
            congestion_[{sid, line, dir, day}] = slot_map;
        }
    }
    std::vector<StationID> DataContainer::get_intermediate_stations(
        StationID from_id, StationID to_id, const std::string &line) const
    {
        std::vector<StationID> result;

        // 1. 두 역의 순서(Order) 조회
        auto it_from = station_orders_.find({from_id, line});
        auto it_to = station_orders_.find({to_id, line});

        if (it_from == station_orders_.end() || it_to == station_orders_.end())
        {
            // 정보가 없으면 도착지만 반환
            result.push_back(to_id);
            return result;
        }

        int from_order = it_from->second;
        int to_order = it_to->second;
        bool ascending = from_order < to_order;

        // 2. 해당 노선의 전체 역 리스트 가져오기
        auto it_list = line_ordered_stations_.find(line);
        if (it_list == line_ordered_stations_.end())
        {
            result.push_back(to_id);
            return result;
        }
        const auto &list = it_list->second;

        // 3. 범위 내 역 추출
        if (ascending)
        {
            // 정방향: from < station <= to
            for (const auto &p : list)
            {
                if (p.first > from_order && p.first <= to_order)
                {
                    result.push_back(p.second);
                }
            }
        }
        else
        {
            // 역방향: to <= station < from (방문 순서는 Order 역순)
            // 리스트 뒤에서부터 탐색하여 순서대로 담음
            for (auto it = list.rbegin(); it != list.rend(); ++it)
            {
                if (it->first < from_order && it->first >= to_order)
                {
                    result.push_back(it->second);
                }
            }
        }

        if (result.empty())
        {
            result.push_back(to_id);
        }

        return result;
    }

    void DataContainer::update_facility_scores(const py::list &facility_rows)
    {
        std::unique_lock<std::shared_mutex> lock(update_mutex);

        // station_scores_ <- station의 count만큼 할당되어 있음

        for (auto &row_obj : facility_rows)
        {
            py::dict row = row_obj.cast<py::dict>();
            py::list cd_list = row["station_cd_list"].cast<py::list>();

            // 각 편의시설의 실시간 수 -> 가동 중인 것만 반영
            double charger = row["charger_count"].cast<double>();
            double elevator = row["elevator_count"].cast<double>();
            double escalator = row["escalator_count"].cast<double>();
            double lift = row["lift_count"].cast<double>();
            double movingwalk = row["movingwalk_count"].cast<double>();
            double safe_platform = row["safe_platform_count"].cast<double>();
            double sign_phone = row["sign_phone_count"].cast<double>();
            double toilet = row["toilet_count"].cast<double>();
            double helper = row["helper_count"].cast<double>();

            // 편의성 점수 계산
            // 유형별 가중치 * 편의시설의 개수 => 정규화
            std::array<double, 4> calc_scores;
            for (int i = 0; i < 4; ++i)
            {
                DisabilityType type = static_cast<DisabilityType>(i);
                const auto &w = PathfindingUtils::get_facility_weights(type);

                double raw = (charger * w.charger) + (elevator * w.elevator) +
                             (escalator * w.escalator) + (lift * w.lift) +
                             (movingwalk * w.movingwalk) + (safe_platform * w.safe_platform) +
                             (sign_phone * w.sign_phone) + (toilet * w.toilet) +
                             (helper * w.helper);

                calc_scores[i] = PathfindingUtils::normalize_score(raw);
            }

            for (auto &cd_obj : cd_list)
            {
                std::string cd = py::str(cd_obj);
                auto it = code_to_id_.find(cd);
                if (it != code_to_id_.end())
                {
                    station_scores_[it->second] = calc_scores;
                }
            }
        }
    }

    StationID DataContainer::get_id(const std::string &cd) const
    {
        auto it = code_to_id_.find(cd);
        if (it != code_to_id_.end())
            return it->second;
        throw std::runtime_error("Unknown station code: " + cd);
    }

    std::string DataContainer::get_code(StationID id) const
    {
        if (id < id_to_code_.size())
            return id_to_code_[id];
        return "";
    }

    const StationInfo &DataContainer::get_station(StationID id) const
    {
        return stations_[id];
    }

    const std::vector<std::string> &DataContainer::get_lines(StationID id) const
    {
        return station_lines_[id];
    }

    const DataContainer::DirectionLines &DataContainer::get_next_stations(StationID id, const std::string &line) const
    {
        static const DirectionLines empty;
        auto it = line_topology_.find({id, line});
        if (it != line_topology_.end())
            return it->second;
        return empty;
    }

    const TransferData *DataContainer::get_transfer(StationID from, const std::string &f_line, const std::string &t_line) const
    {
        auto it = transfers_.find({from, f_line, t_line});
        if (it != transfers_.end())
            return &it->second;
        return nullptr;
    }

    double DataContainer::get_congestion(StationID id, const std::string &line, Direction dir,
                                         const std::string &day, const std::string &time_col) const
    {
        auto it = congestion_.find({id, line, dir, day});
        if (it != congestion_.end())
        {
            auto sit = it->second.find(time_col);
            if (sit != it->second.end())
                return sit->second;
        }
        return 1.3; // default congestion
    }
}