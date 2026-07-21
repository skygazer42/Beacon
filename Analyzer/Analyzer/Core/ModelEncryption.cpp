#include "ModelEncryption.h"

#include <algorithm>
#include <array>
#include <cctype>
#include <chrono>
#include <cstddef>
#include <filesystem>
#include <fstream>
#include <limits>
#include <string_view>
#include <system_error>

namespace AVSAnalyzer {

namespace fs = std::filesystem;

namespace {
    constexpr std::array<unsigned char, 8> kEncV2Magic = {'B', 'E', 'N', 'C', 'v', '2', 0, 0};
    constexpr uint32_t kEncV2Version = 2;
    constexpr uint32_t kEncV2HeaderMinSize = 8 /*magic*/ + 4 /*version*/ + 4 /*headerSize*/ + 8 /*encryptedAtMs*/
        + 4 /*trialSeconds*/ + 4 /*customIdLen*/;
    constexpr uint32_t kEncV2HeaderMaxSize = 4096;

    uint64_t nowMs() {
        using namespace std::chrono;
        const auto ms = duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count();
        if (ms < 0) {
            return 0;
        }
        return static_cast<uint64_t>(ms);
    }

    bool read_exact(std::ifstream& ifs, unsigned char* dst, size_t n) {
        if (!ifs.good()) {
            return false;
        }
        ifs.read(reinterpret_cast<char*>(dst), static_cast<std::streamsize>(n));
        return static_cast<size_t>(ifs.gcount()) == n;
    }

    uint32_t read_u32_le(const unsigned char* p) {
        return static_cast<uint32_t>(p[0])
            | (static_cast<uint32_t>(p[1]) << 8)
            | (static_cast<uint32_t>(p[2]) << 16)
            | (static_cast<uint32_t>(p[3]) << 24);
    }

    uint64_t read_u64_le(const unsigned char* p) {
        uint64_t v = 0;
        for (int i = 7; i >= 0; --i) {
            v = (v << 8) | static_cast<uint64_t>(p[i]);
        }
        return v;
    }

    bool looksLikeEncV2File(const fs::path& path) {
        std::ifstream ifs(path, std::ios::binary);
        if (!ifs.is_open()) {
            return false;
        }
        unsigned char magic[8] = {0};
        if (!read_exact(ifs, magic, sizeof(magic))) {
            return false;
        }
        for (size_t i = 0; i < sizeof(magic); ++i) {
            if (magic[i] != kEncV2Magic[i]) {
                return false;
            }
        }
        return true;
    }

    struct EncV2Header {
        uint32_t version = 0;
        uint32_t headerSize = 0;
        uint64_t encryptedAtMs = 0;
        uint32_t trialSeconds = 0;
        std::string customId{};
    };

    bool try_parse_enc_v2_header(std::ifstream& ifs, EncV2Header& out, std::string& errMsg) {
        out = EncV2Header{};
        errMsg.clear();

        // magic already read by caller and stream pos is right after magic
        unsigned char fixed[4 + 4 + 8 + 4 + 4] = {0};
        if (!read_exact(ifs, fixed, sizeof(fixed))) {
            errMsg = "read v2 header failed";
            return false;
        }

        const uint32_t version = read_u32_le(fixed + 0);
        const uint32_t headerSize = read_u32_le(fixed + 4);
        const uint64_t encryptedAtMs = read_u64_le(fixed + 8);
        const uint32_t trialSeconds = read_u32_le(fixed + 16);
        const uint32_t customIdLen = read_u32_le(fixed + 20);

        if (version != kEncV2Version) {
            errMsg = "invalid v2 version";
            return false;
        }
        if (headerSize < kEncV2HeaderMinSize || headerSize > kEncV2HeaderMaxSize) {
            errMsg = "invalid v2 header size";
            return false;
        }

        const uint64_t alreadyRead = 8ULL + static_cast<uint64_t>(sizeof(fixed));
        if (alreadyRead > headerSize) {
            errMsg = "invalid v2 header size";
            return false;
        }

        if (customIdLen > (headerSize - alreadyRead)) {
            errMsg = "invalid v2 customIdLen";
            return false;
        }

        std::string customId;
        if (customIdLen > 0) {
            customId.resize(static_cast<size_t>(customIdLen));
            if (!read_exact(ifs, reinterpret_cast<unsigned char*>(&customId[0]), static_cast<size_t>(customIdLen))) {
                errMsg = "read v2 customId failed";
                return false;
            }
        }

	        // Skip remaining header padding/fields (forward compatible).
	        if (const uint64_t consumed = alreadyRead + customIdLen; consumed < headerSize) {
	            const uint64_t remain = headerSize - consumed;
	            ifs.seekg(static_cast<std::streamoff>(remain), std::ios::cur);
	            if (!ifs.good()) {
	                errMsg = "skip v2 header padding failed";
	                return false;
            }
        }

        out.version = version;
        out.headerSize = headerSize;
        out.encryptedAtMs = encryptedAtMs;
        out.trialSeconds = trialSeconds;
        out.customId = std::move(customId);
        return true;
    }
}  // namespace

static std::string trimCopy(std::string value) {
    auto notSpace = [](unsigned char ch) { return !std::isspace(ch); };
    value.erase(value.begin(), std::find_if(value.begin(), value.end(), notSpace));
    value.erase(std::find_if(value.rbegin(), value.rend(), notSpace).base(), value.end());
    return value;
}

static std::string toLowerCopy(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return value;
}

static std::string toUpperCopy(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(),
                   [](unsigned char c) { return static_cast<char>(std::toupper(c)); });
    return value;
}

static std::string normalizeSuffix(std::string suffix) {
    suffix = trimCopy(std::move(suffix));
    if (suffix.empty()) {
        return "";
    }
    if (suffix == "." || suffix == "..") {
        return "";
    }
    if (!suffix.empty() && suffix[0] != '.') {
        suffix.insert(suffix.begin(), '.');
    }
    // Guardrail: overly long suffix is almost always misconfiguration.
    if (suffix.size() > 16) {
        return ".enc";
    }
    return suffix;
}

static bool existsNoThrow(const fs::path& path) {
    std::error_code ec;
    const bool ok = fs::exists(path, ec);
    return ok && !ec;
}

static uint64_t fnv1a64(const std::string& value) {
    uint64_t h = 14695981039346656037ULL;
    for (unsigned char c : value) {
        h ^= static_cast<uint64_t>(c);
        h *= 1099511628211ULL;
    }
    return h;
}

static std::string hex16(uint64_t value) {
    static const char* kHex = "0123456789abcdef";
    std::string out(16, '0');
    for (int i = 15; i >= 0; --i) {
        out[static_cast<size_t>(i)] = kHex[value & 0xFULL];
        value >>= 4;
    }
    return out;
}

static std::string sanitizeDirPrefix(const std::string& value, size_t maxLen) {
    std::string out;
    out.reserve(std::min(maxLen, value.size()));
    for (unsigned char c : value) {
        if (out.size() >= maxLen) {
            break;
        }
        if (std::isalnum(c) || c == '_' || c == '-' || c == '.') {
            out.push_back(static_cast<char>(c));
        } else {
            out.push_back('_');
        }
    }
    while (!out.empty() && (out.back() == '_' || out.back() == '.')) {
        out.pop_back();
    }
    if (out.empty() || out == "." || out == "..") {
        out = "algo";
    }
    return out;
}

static std::string algorithmCacheSubdir(const std::string& algorithmCode) {
    // Prevent path traversal / absolute path injection:
    // algorithmCode is user-controlled (from API/DB), must never be used as a path segment directly.
    std::string prefix = sanitizeDirPrefix(algorithmCode, 32);
    return prefix + "__" + hex16(fnv1a64(algorithmCode));
}

static bool endsWithLower(std::string_view value, std::string_view suffix) {
    if (suffix.empty()) {
        return false;
    }
    if (value.size() < suffix.size()) {
        return false;
    }
    const std::string_view tail = value.substr(value.size() - suffix.size());
    std::string a(tail.data(), tail.size());
    std::string b(suffix.data(), suffix.size());
    std::transform(a.begin(), a.end(), a.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    std::transform(b.begin(), b.end(), b.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return a == b;
}

static std::string stripSuffixIfPresent(const std::string& value, const std::string& suffix) {
    if (suffix.empty()) {
        return value;
    }
    if (!endsWithLower(value, suffix)) {
        return value;
    }
    return value.substr(0, value.size() - suffix.size());
}

static bool decryptXorFile(const fs::path& encPath, const fs::path& dstPath, const std::string& key, std::string& errMsg) {
    std::ifstream ifs(encPath, std::ios::binary);
    std::ofstream ofs(dstPath, std::ios::binary | std::ios::trunc);
    if (!ifs.is_open() || !ofs.is_open()) {
        errMsg = "open model file failed: src=" + encPath.string() + " dst=" + dstPath.string();
        return false;
    }
    if (key.empty()) {
        errMsg = "modelEncryptKey is empty";
        return false;
    }

    // v2 header format:
    // - allows "already encrypted" detection without relying on suffix
    // - supports embedded trialSeconds + customId
    unsigned char magic[8] = {0};
    ifs.read(reinterpret_cast<char*>(magic), static_cast<std::streamsize>(sizeof(magic)));
    const std::streamsize magicRead = ifs.gcount();

    // Legacy encrypted files might be very small in unit tests or edge cases.
    // If we can't read the full magic, it can't be v2; fall back to legacy xor.
    bool isV2 = (magicRead == static_cast<std::streamsize>(sizeof(magic)));
    if (isV2) {
        for (size_t i = 0; i < sizeof(magic); ++i) {
            if (magic[i] != kEncV2Magic[i]) {
                isV2 = false;
                break;
            }
        }
    }

    EncV2Header v2;
    if (isV2) {
        std::string perr;
        if (!try_parse_enc_v2_header(ifs, v2, perr)) {
            ofs.close();
            std::error_code removeErr;
            fs::remove(dstPath, removeErr);
            errMsg = "invalid v2 encrypted model header: " + perr;
            return false;
        } else {
            if (v2.trialSeconds > 0 && v2.encryptedAtMs > 0) {
                const uint64_t now = nowMs();
                const uint64_t trialMs = static_cast<uint64_t>(v2.trialSeconds) * 1000ULL;
                const uint64_t expireAt = (v2.encryptedAtMs > (std::numeric_limits<uint64_t>::max() - trialMs))
                    ? std::numeric_limits<uint64_t>::max()
                    : (v2.encryptedAtMs + trialMs);
                if (now > expireAt) {
                    errMsg = "model trial expired: customId=" + v2.customId;
                    return false;
                }
            }
        }
    } else {
        ifs.clear();
        ifs.seekg(0, std::ios::beg);
    }

    const size_t klen = key.size();
    size_t idx = 0;
    char buf[4096];
    while (ifs.good()) {
        ifs.read(buf, sizeof(buf));
        std::streamsize n = ifs.gcount();
        for (std::streamsize i = 0; i < n; ++i) {
            const auto b = static_cast<std::byte>(static_cast<unsigned char>(buf[i]));
            const auto k = static_cast<std::byte>(static_cast<unsigned char>(key[idx % klen]));
            buf[i] = static_cast<char>(std::to_integer<unsigned char>(b ^ k));
            idx++;
        }
        ofs.write(buf, n);
    }
    ofs.flush();
    return true;
}

bool resolveAndMaybeDecryptModel(
    const ModelEncryptionConfig& cfg,
    const std::string& algorithmCode,
    const std::string& requestedPath,
    std::string& outPath,
    std::string& outDecryptedDir,
    std::string& errMsg
) {
    outPath = requestedPath;
    outDecryptedDir.clear();
    errMsg.clear();

    const std::string suffix = normalizeSuffix(cfg.suffix);
    const std::string suffixLower = toLowerCopy(suffix);
    const std::string suffixUpper = toUpperCopy(suffix);

    // Keep legacy behavior when feature is disabled:
    // do not attempt any decryption and just return requestedPath.
    if (!cfg.enabled || suffix.empty()) {
        return true;
    }

    fs::path src(requestedPath);
    bool isEncrypted = false;
    std::string requestedPlain = requestedPath;

    const bool requestedLooksEnc = endsWithLower(requestedPath, suffix);
    const bool requestedExists = existsNoThrow(src);

    // Explicit encrypted path: "<model>.enc"
    if (requestedLooksEnc) {
        isEncrypted = true;
        requestedPlain = stripSuffixIfPresent(requestedPath, suffix);
    } else {
        // Prefer encrypted sibling if present: "<model>" -> "<model>.enc"
        fs::path candidate;
        bool candidateExists = false;

        // Try multiple suffix variants for compatibility (e.g. "enc"/".ENC" misconfiguration).
        const std::string variants[] = {suffix, suffixLower, suffixUpper};
        for (const auto& sfx : variants) {
            if (sfx.empty()) {
                continue;
            }
            fs::path p(requestedPath + sfx);
            if (existsNoThrow(p)) {
                candidate = p;
                candidateExists = true;
                break;
            }
        }

        if (candidateExists) {
            // If we have the key, prefer the encrypted model to avoid accidentally
            // loading plaintext models in production.
            //
            // If key is missing but plaintext exists, fall back to plaintext.
            if (!cfg.key.empty() || !requestedExists) {
                src = candidate;
                isEncrypted = true;
                requestedPlain = requestedPath;
            } else {
                outPath = requestedPath;
                return true;
            }
        } else if (requestedExists) {
            // v2 format supports detection by magic header even without suffix.
            if (looksLikeEncV2File(src)) {
                isEncrypted = true;
                requestedPlain = requestedPath;
            } else {
                outPath = requestedPath;
                return true;
            }
        } else {
            errMsg = "model file not found: " + requestedPath;
            return false;
        }
    }

    if (!isEncrypted) {
        outPath = requestedPlain;
        return true;
    }

    if (!existsNoThrow(src)) {
        errMsg = "model file not found: " + src.string();
        return false;
    }

    if (cfg.key.empty()) {
        errMsg = "modelEncryptKey is empty";
        return false;
    }

    fs::path cacheDir(trimCopy(cfg.decryptDir));
    if (cacheDir.empty()) {
        errMsg = "modelDecryptDir is empty";
        return false;
    }

    {
        std::error_code ec;
        fs::create_directories(cacheDir, ec);
        if (ec) {
            errMsg = "create modelDecryptDir failed: dir=" + cacheDir.string() + " err=" + ec.message();
            return false;
        }
    }

    fs::path workDir = cacheDir / algorithmCacheSubdir(algorithmCode);
    {
        std::error_code ec;
        fs::create_directories(workDir, ec);
        if (ec) {
            errMsg = "create modelDecryptDir subdir failed: dir=" + workDir.string() + " err=" + ec.message();
            return false;
        }
    }

    fs::path requestedPlainPath(requestedPlain);
    fs::path dst = workDir / requestedPlainPath.filename();

    if (!decryptXorFile(src, dst, cfg.key, errMsg)) {
        return false;
    }

    // OpenVINO IR needs xml + bin in the same directory.
    std::string lowerName = requestedPlainPath.filename().string();
    std::transform(lowerName.begin(), lowerName.end(), lowerName.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    if (lowerName.size() >= 4 && lowerName.rfind(".xml") == lowerName.size() - 4) {
        fs::path bin = requestedPlainPath;
        bin.replace_extension(".bin");
        fs::path binEnc;
        bool binEncExists = false;
        const std::string variants[] = {suffix, suffixLower, suffixUpper};
        for (const auto& sfx : variants) {
            if (sfx.empty()) {
                continue;
            }
            fs::path p(bin.string() + sfx);
            if (existsNoThrow(p)) {
                binEnc = p;
                binEncExists = true;
                break;
            }
        }
        fs::path dstBin = workDir / bin.filename();
        if (binEncExists) {
            if (!decryptXorFile(binEnc, dstBin, cfg.key, errMsg)) {
                return false;
            }
        } else if (existsNoThrow(bin)) {
            // Some deliveries may pre-encrypt bin without suffix (v2 header).
            if (looksLikeEncV2File(bin)) {
                if (!decryptXorFile(bin, dstBin, cfg.key, errMsg)) {
                    return false;
                }
            } else {
                std::error_code ec;
                fs::copy_file(bin, dstBin, fs::copy_options::overwrite_existing, ec);
                // ignore; OpenVINO may fail later if bin missing
            }
        }
    }

    outPath = dst.string();
    outDecryptedDir = workDir.string();
    return true;
}

}  // namespace AVSAnalyzer
