#include "engine.h"
#include "utils.h"
#include <algorithm>
#include <shared_mutex>

namespace pathfinding
{

    McRaptorEngine::McRaptorEngine(const DataContainer &data) : data_(data)
    {
        label_pool_.reserve(200000); // Pool Reservation
    }

    std::vector<Label> McRaptorEngine::find_routes(
        const std::string &origin_cd,
        const std::unordered_set<std::string> &dest_cds,
        double departure_time,
        const std::string &disability_type_str,
        int max_rounds)
    {
        // 1. Read Lock (데이터 보호)
        std::shared_lock<std::shared_mutex> lock(data_.update_mutex);

        // 2. 초기화
        label_pool_.clear();
        StationID origin_id = data_.get_id(origin_cd);
        std::unordered_set<StationID> dest_ids;
        for (const auto &d : dest_cds)
            dest_ids.insert(data_.get_id(d));

        ANPWeights weights = PathfindingUtils::calculate_anp_weights(disability_type_str);
        DisabilityType dtype = PathfindingUtils::str_to_disability(disability_type_str);
        double walk_speed = PathfindingUtils::get_walking_speed(disability_type_str);

        std::string day_type = PathfindingUtils::get_day_type(departure_time);

        // Bags: [StationID] -> Indices
        std::unordered_map<StationID, std::vector<LabelIndex>> bags;
        std::unordered_set<StationID> marked_stations;

        // 3. 출발 라벨 생성 (편의시설 점수 0.0)
        auto start_lines = data_.get_lines(origin_id);
        for (const auto &line : start_lines)
        {
            LabelIndex idx = create_label(-1, origin_id, line, Direction::UNKNOWN, 0, 0.0,
                                          0.0, 0.0, 0.0, 1, true, 0);
            bags[origin_id].push_back(idx);
        }
        marked_stations.insert(origin_id);

        // 4. RAPTOR Rounds
        for (int round = 1; round <= max_rounds; ++round)
        {
            if (marked_stations.empty())
                break;
            std::unordered_set<StationID> next_marked;

            std::vector<StationID> queue(marked_stations.begin(), marked_stations.end());
            marked_stations.clear();

            for (StationID u : queue)
            {
                const auto &labels = bags[u];
                for (LabelIndex l_idx : labels)
                {
                    const Label &L = label_pool_[l_idx];
                    if (L.created_round >= round)
                        continue;
                    if (dest_ids.count(u))
                        continue;

                    // A. Scanning (Traversal)
                    auto next_stops = data_.get_next_stations(u, L.current_line);
                    auto process_dir = [&](const std::vector<StationID> &targets, Direction dir)
                    {
                        double cum_time = 0;
                        StationID prev = u;

                        for (StationID v : targets)
                        {
                            if (check_visited(l_idx, v))
                                continue;

                            const auto &s1 = data_.get_station(prev);
                            const auto &s2 = data_.get_station(v);
                            double dist = PathfindingUtils::haversine(s1.latitude, s1.longitude, s2.latitude, s2.longitude);
                            double seg_time = dist / 550.0; // m/s, 33km/h
                            cum_time += std::max(seg_time, 1.0);

                            double current_time = departure_time + (L.arrival_time + cum_time) * 60;
                            std::string time_col = PathfindingUtils::get_time_column(current_time);
                            double seg_cong = data_.get_congestion(prev, L.current_line, dir, day_type, time_col);
                            double new_cong_sum = L.congestion_sum + seg_cong;

                            // 직진 로직 시 편의시설 점수 누적 X
                            LabelIndex new_idx = create_label(l_idx, v, L.current_line, dir, L.transfers,
                                                              L.arrival_time + cum_time,
                                                              L.convenience_sum, // 유지
                                                              new_cong_sum, L.max_transfer_difficulty,
                                                              L.depth + 1, false, round);

                            bool dominated = false;
                            for (LabelIndex ex : bags[v])
                            {
                                if (dominates(label_pool_[ex], label_pool_[new_idx], weights))
                                {
                                    dominated = true;
                                    break;
                                }
                            }
                            if (!dominated)
                            {
                                bags[v].push_back(new_idx);
                                next_marked.insert(v);
                            }
                            prev = v;
                        }
                    };
                    process_dir(next_stops.up, Direction::UP);
                    process_dir(next_stops.down, Direction::DOWN);

                    // B. Transfer
                    auto lines = data_.get_lines(u);
                    for (const auto &next_line : lines)
                    {
                        if (next_line == L.current_line)
                            continue;

                        const TransferData *td = data_.get_transfer(u, L.current_line, next_line);
                        if (!td)
                            continue;

                        double dist = td->distance;
                        double t_time = dist / (walk_speed * 60.0);

                        // 환승 시 환승역의 편의시설 점수 추가
                        double station_score = data_.get_station_convenience(u, dtype);
                        double new_conv_sum = L.convenience_sum + station_score;

                        // 환승 난이도 계산 (TransferData의 facility_scores 사용)
                        static const std::unordered_map<std::string, double> empty_prefs;
                        double diff = PathfindingUtils::calculate_transfer_difficulty(
                            dist, td->facility_scores, disability_type_str, empty_prefs);

                        LabelIndex new_idx = create_label(l_idx, u, next_line, Direction::UNKNOWN, L.transfers + 1,
                                                          L.arrival_time + t_time,
                                                          new_conv_sum, // 추가됨
                                                          L.congestion_sum,
                                                          std::max(L.max_transfer_difficulty, diff),
                                                          L.depth + 1, true, round);

                        bool dominated = false;
                        for (LabelIndex ex : bags[u])
                        {
                            if (label_pool_[ex].current_line == next_line &&
                                dominates(label_pool_[ex], label_pool_[new_idx], weights))
                            {
                                dominated = true;
                                break;
                            }
                        }
                        if (!dominated)
                        {
                            bags[u].push_back(new_idx);
                            next_marked.insert(u);
                        }
                    }
                }
            }
            marked_stations = next_marked;
        }

        std::vector<Label> results;
        for (StationID d : dest_ids)
        {
            for (LabelIndex idx : bags[d])
                results.push_back(label_pool_[idx]);
        }
        return results;
    }

    LabelIndex McRaptorEngine::create_label(
        LabelIndex parent, StationID sid, const std::string &line, Direction dir,
        int tr, double arr, double cv, double cg, double diff,
        int dep, bool fm, int rd)
    {
        Label l;
        l.parent_index = parent;
        l.station_id = sid;
        l.current_line = line;
        l.direction = dir;
        l.transfers = tr;
        l.arrival_time = arr;
        l.convenience_sum = cv;
        l.congestion_sum = cg;
        l.max_transfer_difficulty = diff;
        l.depth = dep;
        l.is_first_move = fm;
        l.created_round = rd;

        label_pool_.push_back(l);
        return (LabelIndex)label_pool_.size() - 1;
    }

    bool McRaptorEngine::check_visited(LabelIndex curr, StationID target)
    {
        while (curr != -1)
        {
            if (label_pool_[curr].station_id == target)
                return true;
            curr = label_pool_[curr].parent_index;
        }
        return false;
    }

    bool McRaptorEngine::dominates(const Label &a, const Label &b, const ANPWeights &w)
    {
        // 1. 필수 조건 (작을수록 좋음)
        if (a.transfers > b.transfers)
            return false;
        if (a.arrival_time > b.arrival_time)
            return false;

        // 2. 가중치가 있는 조건들
        if (w.transfer_difficulty > 0.0 && a.max_transfer_difficulty > b.max_transfer_difficulty)
            return false;
        if (w.congestion > 0.0 && a.avg_congestion() > b.avg_congestion())
            return false;

        // 3. 편의도 (클수록 좋음 -> 작으면 지배 당함)
        if (w.convenience > 0.0 && a.avg_convenience() < b.avg_convenience())
            return false;

        // 4. 하나라도 더 좋은지 확인 (Strict Dominance)
        bool better = false;
        if (a.transfers < b.transfers)
            better = true;
        else if (a.arrival_time < b.arrival_time)
            better = true;
        else if (w.transfer_difficulty > 0.0 && a.max_transfer_difficulty < b.max_transfer_difficulty)
            better = true;
        else if (w.congestion > 0.0 && a.avg_congestion() < b.avg_congestion())
            better = true;
        else if (w.convenience > 0.0 && a.avg_convenience() > b.avg_convenience())
            better = true;

        return better;
    }

    std::vector<Label> McRaptorEngine::reconstruct_path(const Label &leaf_label)
    {
        std::vector<Label> path;

        // Label이 label_pool_에 있는지 확인하고 인덱스 찾기
        LabelIndex current_idx = -1;
        for (size_t i = 0; i < label_pool_.size(); ++i)
        {
            const Label &l = label_pool_[i];
            if (l.station_id == leaf_label.station_id &&
                l.current_line == leaf_label.current_line &&
                l.arrival_time == leaf_label.arrival_time &&
                l.transfers == leaf_label.transfers)
            {
                current_idx = i;
                break;
            }
        }

        if (current_idx == -1)
        {
            // leaf_label이 pool에 없으면 빈 경로 반환
            return path;
        }

        // 역순으로 부모를 따라가며 경로 수집
        while (current_idx != -1)
        {
            path.push_back(label_pool_[current_idx]);
            current_idx = label_pool_[current_idx].parent_index;
        }

        // 정방향으로 뒤집기
        std::reverse(path.begin(), path.end());
        return path;
    }

    std::vector<Label> McRaptorEngine::rank_routes(
        const std::vector<Label> &routes,
        const std::string &disability_type)
    {
        if (routes.empty())
            return routes;

        // ANP 가중치 계산
        ANPWeights weights = PathfindingUtils::calculate_anp_weights(disability_type);

        // 복사본 생성 및 점수 계산
        std::vector<Label> ranked = routes;

        for (auto &label : ranked)
        {
            // 가중 점수 계산 (낮을수록 좋음)
            double score = 0.0;
            score += weights.travel_time * label.arrival_time;
            score += weights.transfers * label.transfers * 10.0; // 환승에 페널티 가중
            score += weights.transfer_difficulty * label.max_transfer_difficulty * 100.0;
            score += weights.congestion * label.avg_congestion() * 50.0;
            score -= weights.convenience * label.avg_convenience() * 20.0; // 편의성은 높을수록 좋음

            label.score_cache = score;
        }

        // 점수 기준 오름차순 정렬
        std::sort(ranked.begin(), ranked.end(),
                  [](const Label &a, const Label &b)
                  {
                      return a.score_cache < b.score_cache;
                  });

        return ranked;
    }

} // namespace pathfinding