#pragma once
#include "types.h"
#include "data_loader.h"
#include <vector>
#include <unordered_set>
#include <string>

namespace pathfinding
{

    class McRaptorEngine
    {
    public:
        explicit McRaptorEngine(const DataContainer &data);

        std::vector<Label> find_routes(
            const std::string &origin_cd,
            const std::unordered_set<std::string> &dest_cds,
            double departure_time,
            const std::string &disability_type,
            int max_rounds);

    private:
        const DataContainer &data_;

        // Memory pool
        std::vector<Label> label_pool_;

        // helper method
        LabelIndex create_label(
            LabelIndex parent_idx,
            StationID station_id,
            const std::string &line,
            Direction dir,
            int transfers,
            double arrival_time,
            double conv_sum,
            double cong_sum,
            double max_diff,
            int depth,
            bool first_move,
            int round);

        bool check_visited(LabelIndex curr_idx, StationID target_id);
        bool dominates(const Label &a, const Label &b, const ANPWeights &w);
    };

} // namespace pathfinding