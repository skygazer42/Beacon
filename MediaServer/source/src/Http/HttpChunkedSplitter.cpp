/*
 * Copyright (c) 2016-present The ZLMediaKit project authors. All Rights Reserved.
 *
 * This file is part of ZLMediaKit(https://github.com/ZLMediaKit/ZLMediaKit).
 *
 * Use of this source code is governed by MIT-like license that can be found in the
 * LICENSE file in the root of the source tree. All contributing project authors
 * may be found in the AUTHORS file in the root of the source tree.
 */

#include <string.h>
#include <limits>
#include <stdexcept>
#include "Common/macros.h"
#include "HttpChunkedSplitter.h"

using namespace std;

//[chunk size][\r\n][chunk data][\r\n][chunk size][\r\n][chunk data][\r\n][chunk size = 0][\r\n][\r\n]

namespace mediakit{

static int hexDigit(char c) {
    if (c >= '0' && c <= '9') {
        return c - '0';
    }
    if (c >= 'a' && c <= 'f') {
        return c - 'a' + 10;
    }
    if (c >= 'A' && c <= 'F') {
        return c - 'A' + 10;
    }
    return -1;
}

const char *HttpChunkedSplitter::onSearchPacketTail(const char *data, size_t len) {
    auto pos = strstr(data, "\r\n");
    if (!pos) {
        return nullptr;
    }
    return pos + 2;
}

void HttpChunkedSplitter::onRecvContent(const char *data, size_t len) {
    onRecvChunk(data, len - 2);
}

ssize_t HttpChunkedSplitter::onRecvHeader(const char *data, size_t len) {
    if (len < 3 || data[len - 2] != '\r' || data[len - 1] != '\n') {
        throw std::invalid_argument("invalid HTTP chunk size");
    }

    const auto max_size = static_cast<size_t>(std::numeric_limits<ssize_t>::max()) - 2;
    size_t size = 0;
    size_t i = 0;
    for (; i < len - 2; ++i) {
        auto digit = hexDigit(data[i]);
        if (digit < 0) {
            break;
        }
        if (size > (max_size - static_cast<size_t>(digit)) / 16) {
            throw std::out_of_range("HTTP chunk size is too large");
        }
        size = size * 16 + static_cast<size_t>(digit);
    }
    if (i == 0 || (data[i] != ';' && data[i] != '\r')) {
        throw std::invalid_argument("invalid HTTP chunk size");
    }
    // 包括后面\r\n两个字节  [AUTO-TRANSLATED:f5567007]
    // Including the following two bytes \r\n
    return static_cast<ssize_t>(size + 2);
}

}//namespace mediakit
