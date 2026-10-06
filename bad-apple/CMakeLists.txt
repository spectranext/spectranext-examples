cmake_minimum_required(VERSION 3.16)

# Import Spectranext SDK - MUST be before project()
include($ENV{SPECTRANEXT_SDK_PATH}/cmake/spectranext_sdk_import.cmake)
spectranext_sdk_init()

project(badapple C ASM)

find_package(Python3 REQUIRED COMPONENTS Interpreter)
execute_process(COMMAND ${Python3_EXECUTABLE} -c "import PIL"
    RESULT_VARIABLE PIL_RESULT)
if(NOT PIL_RESULT EQUAL 0)
    message(FATAL_ERROR "Install Pillow for ${Python3_EXECUTABLE}: python3 -m pip install Pillow")
endif()

# The SDK compiler targets Z80; the image converter runs on the build host.
find_program(BADAPPLE_HOST_CXX NAMES c++ clang++ g++)
if(NOT BADAPPLE_HOST_CXX)
    message(FATAL_ERROR "A host C++ compiler is required for the artwork converter")
endif()
set(MEDIA_DIR "${CMAKE_CURRENT_BINARY_DIR}/media")
set(CONVERTER "${CMAKE_CURRENT_BINARY_DIR}/img2spec")
add_custom_command(OUTPUT "${CONVERTER}"
    COMMAND ${BADAPPLE_HOST_CXX} -std=c++17 -O2
        "${CMAKE_CURRENT_SOURCE_DIR}/tools/img2spec.cpp" -o "${CONVERTER}"
    DEPENDS tools/img2spec.cpp
    VERBATIM)

set(MEDIA_INCLUDES connection.inc media.inc row_addresses.inc
    copy_row.inc copy16.inc copy8.inc intro_data.inc music_data.inc)
set(GENERATED_INCLUDES)
foreach(NAME IN LISTS MEDIA_INCLUDES)
    list(APPEND GENERATED_INCLUDES "${MEDIA_DIR}/${NAME}")
endforeach()
# Track every generated chunk, including for a clean/rebuild or changed GIF.
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS assets/bad-apple.gif)
execute_process(COMMAND ${Python3_EXECUTABLE} -c
    "from PIL import Image; n=Image.open(r'${CMAKE_CURRENT_SOURCE_DIR}/assets/bad-apple.gif').n_frames; print(((n+8)//9+32)//33)"
    OUTPUT_VARIABLE CHUNK_COUNT OUTPUT_STRIP_TRAILING_WHITESPACE
    RESULT_VARIABLE GIF_RESULT)
if(NOT GIF_RESULT EQUAL 0)
    message(FATAL_ERROR "Cannot read assets/bad-apple.gif")
endif()
set(MOVIE_CHUNKS)
foreach(INDEX RANGE 1 ${CHUNK_COUNT})
    list(APPEND MOVIE_CHUNKS "${MEDIA_DIR}/badapple${INDEX}.bin")
endforeach()
add_custom_command(OUTPUT "${MEDIA_DIR}/media.stamp" ${GENERATED_INCLUDES} ${MOVIE_CHUNKS}
    "${MEDIA_DIR}/intro_credits.bin" "${MEDIA_DIR}/intro_specifications.bin"
    COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tools/encode_media.py"
        --assets "${CMAKE_CURRENT_SOURCE_DIR}/assets"
        --output "${MEDIA_DIR}" --converter "${CONVERTER}"
    DEPENDS "${CONVERTER}" tools/encode_media.py assets/bad-apple.gif
        assets/music.pt3 assets/credits.png assets/specifications.png
    COMMENT "Encoding 192x144 GIF into frame-aligned 1 MiB movie chunks"
    VERBATIM)
add_custom_target(badapple_media DEPENDS "${MEDIA_DIR}/media.stamp" ${GENERATED_INCLUDES}
    ${MOVIE_CHUNKS} "${MEDIA_DIR}/intro_credits.bin" "${MEDIA_DIR}/intro_specifications.bin")

add_executable(badapple main.c player.asm)
add_dependencies(badapple badapple_media)
target_include_directories(badapple PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}" "${MEDIA_DIR}")
set_property(SOURCE player.asm APPEND PROPERTY OBJECT_DEPENDS
    "${GENERATED_INCLUDES};${CMAKE_CURRENT_SOURCE_DIR}/controller.asm;${CMAKE_CURRENT_SOURCE_DIR}/intro.asm;${CMAKE_CURRENT_SOURCE_DIR}/music/pt3_player.asm")
target_compile_options(badapple PUBLIC -debug
    "$<$<COMPILE_LANGUAGE:ASM>:-Ca-I${MEDIA_DIR}>")
target_link_libraries(badapple PUBLIC -llibspdos -llibspectranet)
# Leave $C000-$C2C4 for IM2 and the top of RAM for the stack. The SDK CRT and
# player occupy ordinary 48K RAM starting at $6000.
target_link_options(badapple PUBLIC -debug -m -create-app
    -pragma-define:CRT_ORG_CODE=24576 -pragma-define:REGISTER_SP=65280)
add_custom_command(TARGET badapple POST_BUILD
    COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tools/check_layout.py"
        "${CMAKE_CURRENT_BINARY_DIR}/badapple.bin" "${CMAKE_CURRENT_BINARY_DIR}/badapple.map"
    VERBATIM)

spectranext_set_boot("
10 %tapein \"badapple.tap\"
20 LOAD \"\"
")
spectranext_add_extra_outputs(badapple)

# Serve/install one directory; normal builds never write into a user's XFS.
add_custom_target(badapple_resource ALL
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_BINARY_DIR}/badapple.tap" "${MEDIA_DIR}/badapple.tap"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_BINARY_DIR}/boot.zx" "${MEDIA_DIR}/boot.zx"
    DEPENDS badapple badapple_media boot_file
    VERBATIM)
install(DIRECTORY "${MEDIA_DIR}/" DESTINATION .
    FILES_MATCHING PATTERN "badapple*.bin" PATTERN "badapple.tap" PATTERN "boot.zx")

# Set FUSEX_LIB to a headless libfusex build when running this on the host.
# The test ROM may retain an older build identity despite implementing 1.1's
# controller channels. Override only its version data for the playback test.
add_custom_target(badapple_verify
    COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/playback.py"
        --build-dir "${CMAKE_CURRENT_BINARY_DIR}" --startup autoboot --ticks 12500
        --expect-chunk ${CHUNK_COUNT} --check-music --system-version 1.1
    DEPENDS badapple_resource
    USES_TERMINAL
    VERBATIM)
