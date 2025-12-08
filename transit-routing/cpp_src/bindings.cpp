#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "engine.h"
#include "data_loader.h"
#include "utils.h"

namespace py = pybind11;
using namespace pathfinding;

// Wrappers
std::vector<std::string> reconstruct_route_wrapper(McRaptorEngine &engine, const Label &leaf_label, const DataContainer &data)
{
    std::vector<Label> full_path = engine.reconstruct_path(leaf_label);
    std::vector<std::string> route_codes;
    route_codes.reserve(full_path.size());
    for (const auto &label : full_path)
    {
        route_codes.push_back(data.get_code(label.station_id));
    }
    return route_codes;
}

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
    m.doc() = "C++ McRaptor Engine";

    py::class_<Label>(m, "Label")
        .def_readonly("arrival_time", &Label::arrival_time)
        .def_readonly("transfers", &Label::transfers)
        .def_readonly("station_id", &Label::station_id)
        .def_readonly("current_line", &Label::current_line)
        .def_readonly("max_transfer_difficulty", &Label::max_transfer_difficulty)
        .def_property_readonly("avg_convenience", &Label::avg_convenience)
        .def_property_readonly("avg_congestion", &Label::avg_congestion);

    py::class_<DataContainer>(m, "DataContainer")
        .def(py::init<>())
        .def("load_from_python", &DataContainer::load_from_python)
        .def("update_facility_scores", &DataContainer::update_facility_scores)
        .def("get_code", &DataContainer::get_code);

    py::class_<McRaptorEngine>(m, "McRaptorEngine")
        .def(py::init<const DataContainer &>())
        .def("find_routes", &McRaptorEngine::find_routes)
        .def("rank_routes", &McRaptorEngine::rank_routes)
        .def("reconstruct_route", [](McRaptorEngine &self, const Label &l, const DataContainer &d)
             { return reconstruct_route_wrapper(self, l, d); })
        .def("reconstruct_lines", [](McRaptorEngine &self, const Label &l)
             { return reconstruct_lines_wrapper(self, l); });
}