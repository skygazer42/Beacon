/*
   Base64 encode/decode routines derived from code by René Nyffenegger.

   Copyright (C) 2004-2008 René Nyffenegger

   This source code is provided 'as-is', without any express or implied
   warranty. In no event will the author be held liable for any damages
   arising from the use of this software.

   Permission is granted to anyone to use this software for any purpose,
   including commercial applications, and to alter it and redistribute it
   freely, subject to the following restrictions:

   1. The origin of this source code must not be misrepresented; you must not
      claim that you wrote the original source code. If you use this source
      code in a product, an acknowledgment in the product documentation would
      be appreciated but is not required.
   2. Altered source versions must be plainly marked as such, and must not be
      misrepresented as being the original source code.
   3. This notice may not be removed or altered from any source distribution.

   Altered for Beacon: wrapped in a class and updated to use std::byte,
   std::array, and std::string_view.
*/

#ifndef ANALYZER_BASE64_H
#define ANALYZER_BASE64_H
#include <array>
#include <cctype>
#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>

namespace AVSAnalyzer {

    inline constexpr std::string_view kBase64Chars =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "abcdefghijklmnopqrstuvwxyz"
        "0123456789+/";
    class Base64 {
    private:
        static inline bool is_base64(unsigned char c) {
            return (std::isalnum(c) || (c == '+') || (c == '/'));
        }

        static inline std::byte base64_index(std::byte c) {
            // base64_chars.find() returns size_t, but the alphabet length is 64.
            // We explicitly handle "not found" to avoid narrowing -1 (npos) into byte.
            const auto pos = kBase64Chars.find(static_cast<char>(std::to_integer<unsigned char>(c)));
            if (pos == std::string_view::npos) {
                return static_cast<std::byte>(0);
            }
            return static_cast<std::byte>(pos);
        }
    public:
        void encode(const unsigned char* in_data, std::size_t in_size, std::string& out_encoded) const {

            std::size_t i = 0;
            std::size_t j = 0;
            std::array<std::byte, 3> char_array_3{};
            std::array<std::byte, 4> char_array_4{};

	            for (std::size_t n = 0; n < in_size; ++n) {
	                char_array_3[i] = static_cast<std::byte>(*in_data);
	                ++i;
	                ++in_data;
	                if (i == 3) {
	                    char_array_4[0] = (char_array_3[0] & static_cast<std::byte>(0xfc)) >> 2;
	                    char_array_4[1] = ((char_array_3[0] & static_cast<std::byte>(0x03)) << 4)
	                                      | ((char_array_3[1] & static_cast<std::byte>(0xf0)) >> 4);
	                    char_array_4[2] = ((char_array_3[1] & static_cast<std::byte>(0x0f)) << 2)
	                                      | ((char_array_3[2] & static_cast<std::byte>(0xc0)) >> 6);
	                    char_array_4[3] = (char_array_3[2] & static_cast<std::byte>(0x3f));

                    for (i = 0; i < 4; ++i) {
                        out_encoded += kBase64Chars[static_cast<std::size_t>(
                            std::to_integer<unsigned char>(char_array_4[i])
                        )];
                    }
                    i = 0;
                }
            }

	            if (i) {
	                for (j = i; j < 3; ++j) {
	                    char_array_3[j] = static_cast<std::byte>(0);
	                }

	                char_array_4[0] = (char_array_3[0] & static_cast<std::byte>(0xfc)) >> 2;
	                char_array_4[1] = ((char_array_3[0] & static_cast<std::byte>(0x03)) << 4)
	                                  | ((char_array_3[1] & static_cast<std::byte>(0xf0)) >> 4);
	                char_array_4[2] = ((char_array_3[1] & static_cast<std::byte>(0x0f)) << 2)
	                                  | ((char_array_3[2] & static_cast<std::byte>(0xc0)) >> 6);
	                char_array_4[3] = (char_array_3[2] & static_cast<std::byte>(0x3f));

                for (j = 0; j < i + 1; ++j) {
                    out_encoded += kBase64Chars[static_cast<std::size_t>(
                        std::to_integer<unsigned char>(char_array_4[j])
                    )];
                }

                while (i < 3) {
                    out_encoded += '=';
                    ++i;
                }
            }
        }

        void encode(const unsigned char* in_data, int in_size, std::string& out_encoded) const {
            if (in_data == nullptr || in_size <= 0) {
                return;
            }
            encode(in_data, static_cast<std::size_t>(in_size), out_encoded);
        }

        void encode(std::string_view in_str, std::string& out_encoded) const {
            const auto* ptr = reinterpret_cast<const unsigned char*>(in_str.data());
            encode(ptr, in_str.size(), out_encoded);
        }
        void decode(std::string_view in_str, std::string& out_decoded) const {
            std::size_t i = 0;
            std::size_t j = 0;
            std::array<std::byte, 4> char_array_4{};
            std::array<std::byte, 3> char_array_3{};

            for (const char rawChar : in_str) {
                const auto c = static_cast<unsigned char>(rawChar);
                if (c == '=' || !is_base64(c)) {
                    break;
                }

                char_array_4[i] = static_cast<std::byte>(c);
                ++i;
                if (i == 4) {
                    for (i = 0; i < 4; ++i) {
                        char_array_4[i] = base64_index(char_array_4[i]);
                    }

                    char_array_3[0] = (char_array_4[0] << 2) | ((char_array_4[1] & static_cast<std::byte>(0x30)) >> 4);
                    char_array_3[1] = ((char_array_4[1] & static_cast<std::byte>(0x0f)) << 4) | ((char_array_4[2] & static_cast<std::byte>(0x3c)) >> 2);
                    char_array_3[2] = ((char_array_4[2] & static_cast<std::byte>(0x03)) << 6) | char_array_4[3];

                    for (i = 0; i < 3; ++i) {
                        out_decoded.push_back(static_cast<char>(std::to_integer<unsigned char>(char_array_3[i])));
                    }
                    i = 0;
                }
            }

            if (i) {
                for (j = i; j < 4; ++j) {
                    char_array_4[j] = static_cast<std::byte>(0);
                }

                for (j = 0; j < 4; ++j) {
                    char_array_4[j] = base64_index(char_array_4[j]);
                }

                char_array_3[0] = (char_array_4[0] << 2) | ((char_array_4[1] & static_cast<std::byte>(0x30)) >> 4);
                char_array_3[1] = ((char_array_4[1] & static_cast<std::byte>(0x0f)) << 4) | ((char_array_4[2] & static_cast<std::byte>(0x3c)) >> 2);
                char_array_3[2] = ((char_array_4[2] & static_cast<std::byte>(0x03)) << 6) | char_array_4[3];

                for (j = 0; j < i - 1; ++j) {
                    out_decoded.push_back(static_cast<char>(std::to_integer<unsigned char>(char_array_3[j])));
                }
            }
        }
        std::string decode(const std::string& in_str) const {
            std::string out_decoded;
            decode(in_str, out_decoded);
            return out_decoded;
        }
    };
}


#endif //ANALYZER_BASE64_H
