# SPDX-License-Identifier: GPL-3.0-or-later
# Standalone stage-1 bridge: link IfcOpenShell's C++ parser from the pixi environment.
cmake_minimum_required(VERSION 3.24)
project(ifcdump CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(IFC_ROOT "$ENV{CONDA_PREFIX}")
if(NOT IFC_ROOT)
    message(FATAL_ERROR "CONDA_PREFIX is not set; run this through pixi")
endif()
# conda-forge ships the headers and libraries under Library/ on Windows and under the prefix on Unix.
if(WIN32)
    set(IFC_INCLUDE "${IFC_ROOT}/Library/include")
    set(IFC_LIB "${IFC_ROOT}/Library/lib")
else()
    set(IFC_INCLUDE "${IFC_ROOT}/include")
    set(IFC_LIB "${IFC_ROOT}/lib")
endif()

set(CMAKE_BUILD_RPATH "$ENV{CONDA_PREFIX}/lib")
set(CMAKE_INSTALL_RPATH "$ENV{CONDA_PREFIX}/lib")

add_executable(ifcdump ifcdump.cpp)
target_include_directories(ifcdump PRIVATE "${IFC_INCLUDE}")
target_link_directories(ifcdump PRIVATE "${IFC_LIB}")
target_link_libraries(ifcdump PRIVATE ifcopenshell.parse)
