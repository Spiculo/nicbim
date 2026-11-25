# SPDX-License-Identifier: GPL-3.0-or-later
# Standalone E57 reader bridge: link libe57format from the pixi environment.
cmake_minimum_required(VERSION 3.24)
project(e57dump CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT DEFINED ENV{CONDA_PREFIX})
    message(FATAL_ERROR "CONDA_PREFIX is not set; run this through pixi")
endif()
list(APPEND CMAKE_PREFIX_PATH "$ENV{CONDA_PREFIX}")
find_package(E57Format CONFIG REQUIRED)

set(CMAKE_BUILD_RPATH "$ENV{CONDA_PREFIX}/lib")
set(CMAKE_INSTALL_RPATH "$ENV{CONDA_PREFIX}/lib")

add_executable(e57dump e57dump.cpp)
target_link_libraries(e57dump PRIVATE E57Format)
