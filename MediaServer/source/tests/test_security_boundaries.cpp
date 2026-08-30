/*
 * Copyright (c) 2016-present The ZLMediaKit project authors. All Rights Reserved.
 *
 * This file is part of ZLMediaKit(https://github.com/ZLMediaKit/ZLMediaKit).
 *
 * Use of this source code is governed by MIT-like license that can be found in the
 * LICENSE file in the root of the source tree. All contributing project authors
 * may be found in the AUTHORS file in the root of the source tree.
 */

#include "Http/HttpChunkedSplitter.h"
#include "flv-parser.h"
#include <cerrno>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

extern "C" {
#include "../3rdpart/media-server/libmov/source/mov-internal.h"
}

using namespace mediakit;

static void require(bool condition, const char *message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

static void feed(HttpChunkedSplitter &splitter, const std::string &payload) {
    std::vector<char> buffer(payload.begin(), payload.end());
    buffer.push_back('\0');
    splitter.input(buffer.data(), payload.size());
}

static void testHttpChunkBoundaries() {
    std::vector<std::string> chunks;
    HttpChunkedSplitter splitter([&chunks](const char *data, size_t len) {
        chunks.emplace_back(data, len);
    });
    feed(splitter, "4;name=value\r\nWiki\r\n0\r\n\r\n");
    require(chunks.size() == 2, "chunk callback count mismatch");
    require(chunks[0] == "Wiki", "chunk payload mismatch");
    require(chunks[1].empty(), "terminal chunk was not empty");

    HttpChunkedSplitter invalid([](const char *, size_t) {});
    bool rejected = false;
    try {
        feed(invalid, "-1\r\n");
    } catch (const std::invalid_argument &) {
        rejected = true;
    }
    require(rejected, "negative chunk size was accepted");

    HttpChunkedSplitter oversized([](const char *, size_t) {});
    rejected = false;
    try {
        feed(oversized, "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF\r\n");
    } catch (const std::out_of_range &) {
        rejected = true;
    }
    require(rejected, "oversized chunk size was accepted");
}

static int ignoreFlvPacket(void *, int, const void *, size_t, uint32_t, uint32_t, int) {
    return 0;
}

static void testFlvTagUnderflow() {
    const uint8_t malformed[] = {
        'F', 'L', 'V', 1, 5, 0, 0, 0, 9,
        0, 0, 0, 0,
        9, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0x12, 0,
    };
    flv_parser_t parser;
    std::memset(&parser, 0, sizeof(parser));
    require(flv_parser_input(&parser, malformed, sizeof(malformed), ignoreFlvPacket, nullptr) < 0,
            "malformed FLV tag size was accepted");
    require(parser.body == nullptr, "FLV body allocated before size validation");
}

static void testMovExtraDataBoundaries() {
    mov_track_t track = {};
    mov_mvhd_t movie = {};
    uint8_t extra_data = 0;
    const size_t oversized = 1024U * 1024U + 1U;

    require(mov_add_audio(&track, &movie, 1000, MOV_OBJECT_AAC, 2, 16, 48000,
                          &extra_data, oversized) == -E2BIG,
            "oversized MOV audio metadata was accepted");
    require(mov_add_video(&track, &movie, 1000, MOV_OBJECT_H264, 1920, 1080,
                          &extra_data, oversized) == -E2BIG,
            "oversized MOV video metadata was accepted");
    require(mov_add_subtitle(&track, &movie, 1000, MOV_OBJECT_TEXT, nullptr, 1) == -EINVAL,
            "null MOV subtitle metadata was accepted");
}

int main() {
    testHttpChunkBoundaries();
    testFlvTagUnderflow();
    testMovExtraDataBoundaries();
    return 0;
}
