#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "engine.h"
#include "data_loader.h"
#include "utils.h"

namespace py = pybind11;
using namespace pathfinding;

// [Wrapper] 전체 경로의 역 코드 리스트를 반환하는 헬퍼 함수
// McRaptorEngine::reconstruct_path가 반환한 vector<Label>을 순회하며 역 코드로 변환
std::vector<std::string> reconstruct_route_wrapper(McRaptorEngine &engine, const Label &leaf_label, const DataContainer &data)
{
    // 1. 엔진 내부의 Pool을 통해 경로(중간역 포함)를 복원
    std::vector<Label> full_path = engine.reconstruct_path(leaf_label);

    // 2. Station ID -> Station Code(String) 변환
    std::vector<std::string> route_codes;
    route_codes.reserve(full_path.size());

    for (const auto &label : full_path)
    {
        route_codes.push_back(data.get_code(label.station_id));
    }

    return route_codes;
}

// [Wrapper] 전체 경로의 노선 리스트를 반환하는 헬퍼 함수
std::vector<std::string> reconstruct_lines_wrapper(McRaptorEngine &engine, const Label &leaf_label)
{
    std::vector<Label> full_path = engine.reconstruct_path(leaf_label);

    std::vector<std::string> lines;
    lines.reserve(full_path.size());

    for (const auto &label : full_path)
    {
        lines.push_back(label.current_line);
    }

    return lines;
}

PYBIND11_MODULE(pathfinding_cpp, m)
{
    m.doc() = "High-performance McRaptor Engine (C++)";

    // 1. Label 클래스 바인딩 (Read-only)
    py::class_<Label>(m, "Label")
        .def_readonly("arrival_time", &Label::arrival_time)
        .def_readonly("transfers", &Label::transfers)
        .def_readonly("station_id", &Label::station_id)
        .def_readonly("current_line", &Label::current_line)
        .def_readonly("max_transfer_difficulty", &Label::max_transfer_difficulty)
        .def_property_readonly("avg_convenience", &Label::avg_convenience)
        .def_property_readonly("avg_congestion", &Label::avg_congestion)
        // Python 측 디버깅을 위해 추가 정보 노출 가능
        .def_readonly("depth", &Label::depth);

    // 2. DataContainer 클래스 바인딩
    py::class_<DataContainer>(m, "DataContainer")
        .def(py::init<>())
        // 초기 데이터 로드 (Station Order 포함)
        .def("load_from_python", &DataContainer::load_from_python,
             py::arg("stations"),
             py::arg("line_stations"),
             py::arg("station_order"),
             py::arg("transfers"),
             py::arg("congestion"))
        // 실시간 편의시설 점수 업데이트
        .def("update_facility_scores", &DataContainer::update_facility_scores)
        // 유틸리티: ID -> Code 변환
        .def("get_code", &DataContainer::get_code);

    // 3. McRaptorEngine 클래스 바인딩
    py::class_<McRaptorEngine>(m, "McRaptorEngine")
        .def(py::init<const DataContainer &>())
        // 경로 탐색
        .def("find_routes", &McRaptorEngine::find_routes,
             py::arg("origin_cd"),
             py::arg("dest_cds"),
             py::arg("departure_time"),
             py::arg("disability_type"),
             py::arg("max_rounds") = 5)
        // 경로 정렬 (Python label.py의 calculate_weighted_score 로직 내장)
        .def("rank_routes", &McRaptorEngine::rank_routes,
             py::arg("routes"),
             py::arg("disability_type"))
        // [New] 경로 재구성 (중간역 포함) - Wrapper 함수 연결
        .def("reconstruct_route", [](McRaptorEngine &self, const Label &l, const DataContainer &d)
             { return reconstruct_route_wrapper(self, l, d); }, py::arg("label"), py::arg("data_container"))
        .def("reconstruct_lines", [](McRaptorEngine &self, const Label &l)
             { return reconstruct_lines_wrapper(self, l); }, py::arg("label"));
}