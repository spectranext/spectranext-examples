cmake_minimum_required(VERSION 3.16)

include($ENV{SPECTRANEXT_SDK_PATH}/cmake/spectranext_sdk_import.cmake)
spectranext_sdk_init()

project(p2p_chat C)

add_executable(p2p-chat main.c)
target_compile_options(p2p-chat PUBLIC -debug)
target_link_libraries(p2p-chat PUBLIC -lndos -llibspectranet -llibsocket)
target_link_options(p2p-chat PUBLIC -debug -create-app)

spectranext_set_boot("
10 %tapein \"p2p-chat.tap\"
20 LOAD \"\"
")
spectranext_add_extra_outputs(p2p-chat)
