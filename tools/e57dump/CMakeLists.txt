# SPDX-License-Identifier: GPL-3.0-or-later
# Standalone E57 reader bridge: link libe57format from the pixi environment.
cmake_minimum_required(VERSION 3.24)
project(e57dump CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(E57_ROOT "$ENV{CONDA_PREFIX}")
if(NOT E57_ROOT)
    message(FATAL_ERROR "CONDA_PREFIX is not set; run this through pixi")
endif()

add_executable(e57dump e57dump.cpp)
target_include_directories(e57dump PRIVATE "${E57_ROOT}/Library/include")
target_link_directories(e57dump PRIVATE "${E57_ROOT}/Library/lib")
target_link_libraries(e57dump PRIVATE E57Format)
