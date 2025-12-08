cmake_minimum_required(VERSION 3.15)
project(pathfinding_cpp VERSION 1.0.0)

# C++17 표준 설정
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Python 및 pybind11 찾기
find_package(Python 3.11 COMPONENTS Interpreter Development REQUIRED)
find_package(pybind11 CONFIG REQUIRED)

# 소스 파일 (utils.cpp 추가!)
set(SOURCES
    utils.cpp
    data_loader.cpp
    engine.cpp
    bindings.cpp
)

# 헤더 파일 (문서화 목적)
set(HEADERS
    types.h
    utils.h
    data_loader.h
    engine.h
)

# Python 확장 모듈 생성
pybind11_add_module(pathfinding_cpp ${SOURCES} ${HEADERS})

# 인클루드 디렉토리
target_include_directories(pathfinding_cpp PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
)

# 컴파일 정의 (M_PI 사용을 위해)
target_compile_definitions(pathfinding_cpp PRIVATE
    _USE_MATH_DEFINES
)

# Linux 환경 최적화 플래그
if(CMAKE_BUILD_TYPE STREQUAL "Release")
    target_compile_options(pathfinding_cpp PRIVATE
        -O3                 # 최대 최적화
        -march=native       # CPU 아키텍처에 맞춤 최적화
        -ffast-math         # 빠른 수학 연산
        -DNDEBUG            # assert 비활성화
    )
elseif(CMAKE_BUILD_TYPE STREQUAL "Debug")
    target_compile_options(pathfinding_cpp PRIVATE
        -g                  # 디버그 정보
        -O0                 # 최적화 없음
        -Wall               # 모든 경고
        -Wextra             # 추가 경고
    )
endif()

# 설치 설정 (선택사항)
install(TARGETS pathfinding_cpp
    LIBRARY DESTINATION ${Python_SITEARCH}
)