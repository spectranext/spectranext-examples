cmake_minimum_required(VERSION 3.16)

# Import Spectranext SDK - MUST be before project()
include($ENV{SPECTRANEXT_SDK_PATH}/cmake/spectranext_sdk_import.cmake)
spectranext_sdk_init()

project(ssh_client C)

add_executable(ssh_client main.c)

target_compile_options(ssh_client PUBLIC -debug)
target_link_libraries(ssh_client PUBLIC
    -lndos
    -llibspectranet
    -llibsocket
)
target_link_options(ssh_client PUBLIC -debug -create-app)

spectranext_set_boot("
10 %tapein \"ssh_client.tap\"
20 LOAD \"\"
")

spectranext_add_extra_outputs(ssh_client)
