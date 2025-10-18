cmake_minimum_required(VERSION 3.10)
project(OCPPProtoTest CXX)
set(CMAKE_CXX_STANDARD 17)

option(TEST_V201 "Build OCPP V2.0.1 test" OFF)
option(TEST_V21  "Build OCPP V2.1 test"   OFF)

find_package(Protobuf REQUIRED)

# ---- paths ----
# this file is at test/cpp/, so go up two levels to reach output/
set(GEN_CPP_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../output/gen/cpp_out")

set(V201_DIR "${GEN_CPP_ROOT}/ocpp/v201")
set(V21_DIR  "${GEN_CPP_ROOT}/ocpp/v21")

# ---- sources (.pb.cc) come from gen/, not proto/ ----
file(GLOB_RECURSE PROTO_SRCS_V201 "${V201_DIR}/*.pb.cc")
file(GLOB_RECURSE PROTO_SRCS_V21  "${V21_DIR}/*.pb.cc")

# ---- helpers: include dirs where .pb.h live ----
set(V201_INCLUDE_DIRS
    "${V201_DIR}"
    "${V201_DIR}/types"
    "${V201_DIR}/types/enums"
)
set(V21_INCLUDE_DIRS
    "${V21_DIR}"
    "${V21_DIR}/types"
    "${V21_DIR}/types/enums"
)

if(TEST_V201)
    add_executable(test_v201
        ${CMAKE_CURRENT_LIST_DIR}/test_v201.cpp
        ${PROTO_SRCS_V201}
    )
    target_include_directories(test_v201 PRIVATE
        ${Protobuf_INCLUDE_DIRS}
        ${V201_INCLUDE_DIRS}
    )
    target_link_libraries(test_v201 PRIVATE protobuf::libprotobuf)
endif()

if(TEST_V21)
    add_executable(test_v21
        ${CMAKE_CURRENT_LIST_DIR}/test_v21.cpp
        ${PROTO_SRCS_V21}
    )
    target_include_directories(test_v21 PRIVATE
        ${Protobuf_INCLUDE_DIRS}
        ${V21_INCLUDE_DIRS}
    )
    target_link_libraries(test_v21 PRIVATE protobuf::libprotobuf)
endif()
