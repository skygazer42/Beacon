#include "ModelEncryption.h"

#include <cassert>
#include <cstdint>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

namespace fs = std::filesystem;

static std::vector<uint8_t> read_all_bytes(const fs::path& path) {
    std::ifstream ifs(path, std::ios::binary);
    std::vector<uint8_t> data;
    if (!ifs.is_open()) {
        return data;
    }
    ifs.seekg(0, std::ios::end);
    std::streamsize size = ifs.tellg();
    ifs.seekg(0, std::ios::beg);
    if (size <= 0) {
        return data;
    }
    data.resize(static_cast<size_t>(size));
    ifs.read(reinterpret_cast<char*>(data.data()), size);
    return data;
}

static bool write_all_bytes(const fs::path& path, const std::vector<uint8_t>& data) {
    std::ofstream ofs(path, std::ios::binary | std::ios::trunc);
    if (!ofs.is_open()) {
        return false;
    }
    if (!data.empty()) {
        ofs.write(reinterpret_cast<const char*>(data.data()), static_cast<std::streamsize>(data.size()));
    }
    ofs.flush();
    return true;
}

static std::vector<uint8_t> xor_crypt(const std::vector<uint8_t>& plain, const std::string& key) {
    std::vector<uint8_t> out = plain;
    if (key.empty()) {
        return out;
    }
    for (size_t i = 0; i < out.size(); ++i) {
        out[i] = static_cast<uint8_t>(out[i] ^ static_cast<uint8_t>(key[i % key.size()]));
    }
    return out;
}

static void append_le32(std::vector<uint8_t>& out, uint32_t value) {
    out.push_back(static_cast<uint8_t>(value & 0xFF));
    out.push_back(static_cast<uint8_t>((value >> 8) & 0xFF));
    out.push_back(static_cast<uint8_t>((value >> 16) & 0xFF));
    out.push_back(static_cast<uint8_t>((value >> 24) & 0xFF));
}

static void append_le64(std::vector<uint8_t>& out, uint64_t value) {
    for (int i = 0; i < 8; ++i) {
        out.push_back(static_cast<uint8_t>((value >> (i * 8)) & 0xFF));
    }
}

static uint64_t now_ms() {
    using namespace std::chrono;
    const auto ms = duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count();
    return static_cast<uint64_t>(ms);
}

static std::vector<uint8_t> encrypt_v2(
    const std::vector<uint8_t>& plain,
    const std::string& key,
    uint64_t encryptedAtMs,
    uint32_t trialSeconds,
    const std::string& customId
) {
    // Format (v2):
    // magic[8]="BENCv2\\0\\0"
    // u32 version=2
    // u32 headerSize
    // u64 encryptedAtMs
    // u32 trialSeconds
    // u32 customIdLen + bytes
    // payload: xor(plain, key) (key index reset at payload start)
    std::vector<uint8_t> header;
    header.reserve(64 + customId.size());
    const uint8_t magic[8] = {'B', 'E', 'N', 'C', 'v', '2', 0, 0};
    header.insert(header.end(), magic, magic + 8);
    append_le32(header, 2);  // version

    const size_t headerSizePos = header.size();
    append_le32(header, 0);  // placeholder headerSize

    append_le64(header, encryptedAtMs);
    append_le32(header, trialSeconds);

    const uint32_t cidLen = static_cast<uint32_t>(customId.size());
    append_le32(header, cidLen);
    if (cidLen > 0) {
        header.insert(header.end(), customId.begin(), customId.end());
    }

    const uint32_t headerSize = static_cast<uint32_t>(header.size());
    header[headerSizePos + 0] = static_cast<uint8_t>(headerSize & 0xFF);
    header[headerSizePos + 1] = static_cast<uint8_t>((headerSize >> 8) & 0xFF);
    header[headerSizePos + 2] = static_cast<uint8_t>((headerSize >> 16) & 0xFF);
    header[headerSizePos + 3] = static_cast<uint8_t>((headerSize >> 24) & 0xFF);

    std::vector<uint8_t> out = header;
    std::vector<uint8_t> payload = xor_crypt(plain, key);
    out.insert(out.end(), payload.begin(), payload.end());
    return out;
}

int main() {
    const std::string key = "k123";
    const std::string suffix = ".enc";

    fs::path root = fs::temp_directory_path() / "beacon_model_encrypt_test";
    fs::remove_all(root);
    fs::create_directories(root);

    fs::path decryptDir = root / "dec";
    fs::create_directories(decryptDir);

    // ========== Case 1: base path missing, .enc exists ==========
    {
        fs::path base = root / "model.onnx";
        fs::path enc = fs::path(base.string() + suffix);
        std::vector<uint8_t> plain = {1, 2, 3, 4, 5, 6, 7};
        assert(write_all_bytes(enc, xor_crypt(plain, key)));

        AVSAnalyzer::ModelEncryptionConfig cfg;
        cfg.enabled = true;
        cfg.key = key;
        cfg.suffix = suffix;
        cfg.decryptDir = decryptDir.string();

        std::string outPath;
        std::string outDecryptedDir;
        std::string err;
        bool ok = AVSAnalyzer::resolveAndMaybeDecryptModel(cfg, /*algorithmCode=*/"algo1", base.string(), outPath, outDecryptedDir, err);
        assert(ok);
        assert(!outPath.empty());
        assert(fs::exists(outPath));
        assert(read_all_bytes(outPath) == plain);
    }

    // ========== Case 2: prefer encrypted sibling when present ==========
    {
        fs::path base = root / "prefer.onnx";
        fs::path enc = fs::path(base.string() + suffix);
        std::vector<uint8_t> plainOnDisk = {0x11, 0x22, 0x33};
        std::vector<uint8_t> plainEncrypted = {0xAA, 0xBB, 0xCC};
        assert(write_all_bytes(base, plainOnDisk));
        assert(write_all_bytes(enc, xor_crypt(plainEncrypted, key)));

        AVSAnalyzer::ModelEncryptionConfig cfg;
        cfg.enabled = true;
        cfg.key = key;
        cfg.suffix = suffix;
        cfg.decryptDir = decryptDir.string();

        std::string outPath;
        std::string outDecryptedDir;
        std::string err;
        bool ok = AVSAnalyzer::resolveAndMaybeDecryptModel(cfg, /*algorithmCode=*/"algo_pref", base.string(), outPath, outDecryptedDir, err);
        assert(ok);
        assert(fs::exists(outPath));
        assert(read_all_bytes(outPath) == plainEncrypted);
    }

    // ========== Case 3: explicit .enc path ==========
    {
        fs::path enc = root / "explicit.onnx.enc";
        fs::path base = root / "explicit.onnx";
        std::vector<uint8_t> plain = {'b', 'e', 'a', 'c', 'o', 'n'};
        assert(write_all_bytes(enc, xor_crypt(plain, key)));

        AVSAnalyzer::ModelEncryptionConfig cfg;
        cfg.enabled = true;
        cfg.key = key;
        cfg.suffix = suffix;
        cfg.decryptDir = decryptDir.string();

        std::string outPath;
        std::string outDecryptedDir;
        std::string err;
        bool ok = AVSAnalyzer::resolveAndMaybeDecryptModel(cfg, /*algorithmCode=*/"algo2", enc.string(), outPath, outDecryptedDir, err);
        assert(ok);
        assert(outPath.find(".enc") == std::string::npos);
        assert(fs::exists(outPath));
        assert(read_all_bytes(outPath) == plain);

        // Also ensure outPath is treated as the base filename.
        assert(fs::path(outPath).filename().string() == base.filename().string());
    }

    // ========== Case 4: enabled but key missing: explicit encrypted path should fail ==========
    {
        fs::path enc = root / "nokey.onnx.enc";
        std::vector<uint8_t> plain = {1, 2, 3, 4};
        assert(write_all_bytes(enc, xor_crypt(plain, key)));

        AVSAnalyzer::ModelEncryptionConfig cfg;
        cfg.enabled = true;
        cfg.key = "";
        cfg.suffix = suffix;
        cfg.decryptDir = decryptDir.string();

        std::string outPath;
        std::string outDecryptedDir;
        std::string err;
        bool ok = AVSAnalyzer::resolveAndMaybeDecryptModel(cfg, /*algorithmCode=*/"algo_nokey", enc.string(), outPath, outDecryptedDir, err);
        assert(!ok);
        assert(err.find("modelEncryptKey") != std::string::npos);
    }

    // ========== Case 5: enabled but key missing: fallback to plaintext if present ==========
    {
        fs::path base = root / "fallback.onnx";
        fs::path enc = fs::path(base.string() + suffix);
        std::vector<uint8_t> plain = {'p', 'l', 'a', 'i', 'n'};
        std::vector<uint8_t> shouldNotBeUsed = {'e', 'n', 'c'};
        assert(write_all_bytes(base, plain));
        assert(write_all_bytes(enc, xor_crypt(shouldNotBeUsed, key)));

        AVSAnalyzer::ModelEncryptionConfig cfg;
        cfg.enabled = true;
        cfg.key = "";
        cfg.suffix = suffix;
        cfg.decryptDir = decryptDir.string();

        std::string outPath;
        std::string outDecryptedDir;
        std::string err;
        bool ok = AVSAnalyzer::resolveAndMaybeDecryptModel(cfg, /*algorithmCode=*/"algo_fb", base.string(), outPath, outDecryptedDir, err);
        assert(ok);
        assert(outPath == base.string());
        assert(outDecryptedDir.empty());
        assert(read_all_bytes(outPath) == plain);
    }

    // ========== Case 6: OpenVINO IR xml+bin (both encrypted) ==========
    {
        fs::path xmlEnc = root / "y.xml.enc";
        fs::path binEnc = root / "y.bin.enc";

        std::vector<uint8_t> xmlPlain = {'<', 'x', 'm', 'l', '>', '\n'};
        std::vector<uint8_t> binPlain = {9, 8, 7, 6, 5};
        assert(write_all_bytes(xmlEnc, xor_crypt(xmlPlain, key)));
        assert(write_all_bytes(binEnc, xor_crypt(binPlain, key)));

        AVSAnalyzer::ModelEncryptionConfig cfg;
        cfg.enabled = true;
        cfg.key = key;
        cfg.suffix = suffix;
        cfg.decryptDir = decryptDir.string();

        std::string outPath;
        std::string outDecryptedDir;
        std::string err;
        bool ok = AVSAnalyzer::resolveAndMaybeDecryptModel(cfg, /*algorithmCode=*/"ov1", xmlEnc.string(), outPath, outDecryptedDir, err);
        assert(ok);
        assert(fs::exists(outPath));
        assert(read_all_bytes(outPath) == xmlPlain);

        fs::path outBin = fs::path(outDecryptedDir) / "y.bin";
        assert(fs::exists(outBin));
        assert(read_all_bytes(outBin) == binPlain);
    }

    // ========== Case 7: suffix configured without leading dot ("enc") ==========
    {
        fs::path base = root / "nodot.onnx";
        fs::path enc = fs::path(base.string() + ".enc");
        std::vector<uint8_t> plain = {0x10, 0x20, 0x30};
        assert(write_all_bytes(enc, xor_crypt(plain, key)));

        AVSAnalyzer::ModelEncryptionConfig cfg;
        cfg.enabled = true;
        cfg.key = key;
        cfg.suffix = "enc";
        cfg.decryptDir = decryptDir.string();

        std::string outPath;
        std::string outDecryptedDir;
        std::string err;
        bool ok = AVSAnalyzer::resolveAndMaybeDecryptModel(cfg, /*algorithmCode=*/"algo_nodot", base.string(), outPath, outDecryptedDir, err);
        assert(ok);
        assert(fs::exists(outPath));
        assert(read_all_bytes(outPath) == plain);
    }

    // ========== Case 8: suffix configured as uppercase (".ENC") while disk uses ".enc" ==========
    {
        fs::path base = root / "upper.onnx";
        fs::path enc = fs::path(base.string() + ".enc");
        std::vector<uint8_t> plain = {'u', 'p', 'p', 'e', 'r'};
        assert(write_all_bytes(enc, xor_crypt(plain, key)));

        AVSAnalyzer::ModelEncryptionConfig cfg;
        cfg.enabled = true;
        cfg.key = key;
        cfg.suffix = ".ENC";
        cfg.decryptDir = decryptDir.string();

        std::string outPath;
        std::string outDecryptedDir;
        std::string err;
        bool ok = AVSAnalyzer::resolveAndMaybeDecryptModel(cfg, /*algorithmCode=*/"algo_upper", base.string(), outPath, outDecryptedDir, err);
        assert(ok);
        assert(fs::exists(outPath));
        assert(read_all_bytes(outPath) == plain);
    }

    // ========== Case 9: v2 encrypted file WITHOUT ".enc" suffix should still decrypt ==========
    {
        fs::path encNoSuffix = root / "v2nosuffix.onnx";
        std::vector<uint8_t> plain = {'v', '2', '-', 'n', 'o', 's', 'u', 'f', 'f', 'i', 'x'};
        const auto encBytes = encrypt_v2(plain, key, now_ms(), /*trialSeconds=*/0, /*customId=*/"CUST001");
        assert(write_all_bytes(encNoSuffix, encBytes));

        AVSAnalyzer::ModelEncryptionConfig cfg;
        cfg.enabled = true;
        cfg.key = key;
        cfg.suffix = suffix;
        cfg.decryptDir = decryptDir.string();

        std::string outPath;
        std::string outDecryptedDir;
        std::string err;
        bool ok = AVSAnalyzer::resolveAndMaybeDecryptModel(cfg, /*algorithmCode=*/"algo_v2", encNoSuffix.string(), outPath, outDecryptedDir, err);
        assert(ok);
        assert(fs::exists(outPath));
        assert(read_all_bytes(outPath) == plain);
    }

    // ========== Case 10: explicit ".enc" path with v2 header should decrypt payload (header not part of plaintext) ==========
    {
        fs::path enc = root / "v2explicit.engine.enc";
        std::vector<uint8_t> plain = {0xDE, 0xAD, 0xBE, 0xEF};
        const auto encBytes = encrypt_v2(plain, key, now_ms(), /*trialSeconds=*/0, /*customId=*/"TRT-42");
        assert(write_all_bytes(enc, encBytes));

        AVSAnalyzer::ModelEncryptionConfig cfg;
        cfg.enabled = true;
        cfg.key = key;
        cfg.suffix = suffix;
        cfg.decryptDir = decryptDir.string();

        std::string outPath;
        std::string outDecryptedDir;
        std::string err;
        bool ok = AVSAnalyzer::resolveAndMaybeDecryptModel(cfg, /*algorithmCode=*/"algo_v2_explicit", enc.string(), outPath, outDecryptedDir, err);
        assert(ok);
        assert(fs::exists(outPath));
        assert(read_all_bytes(outPath) == plain);
    }

    // ========== Case 11: v2 trial expired should fail with diagnostics ==========
    {
        fs::path enc = root / "v2expired.onnx.enc";
        std::vector<uint8_t> plain = {'e', 'x', 'p', 'i', 'r', 'e', 'd'};
        // encryptedAtMs=1ms since epoch => always expired for trialSeconds=1.
        const auto encBytes = encrypt_v2(plain, key, /*encryptedAtMs=*/1, /*trialSeconds=*/1, /*customId=*/"CID_EXPIRED");
        assert(write_all_bytes(enc, encBytes));

        AVSAnalyzer::ModelEncryptionConfig cfg;
        cfg.enabled = true;
        cfg.key = key;
        cfg.suffix = suffix;
        cfg.decryptDir = decryptDir.string();

        std::string outPath;
        std::string outDecryptedDir;
        std::string err;
        bool ok = AVSAnalyzer::resolveAndMaybeDecryptModel(cfg, /*algorithmCode=*/"algo_v2_expired", enc.string(), outPath, outDecryptedDir, err);
        assert(!ok);
        assert(err.find("expired") != std::string::npos);
        assert(err.find("CID_EXPIRED") != std::string::npos);
    }

    // ========== Case 12: recognized v2 magic with malformed header must not fall back to legacy XOR ==========
    {
        fs::path enc = root / "v2malformed.onnx.enc";
        std::vector<uint8_t> malformed = {'B', 'E', 'N', 'C', 'v', '2', 0, 0};
        append_le32(malformed, 2);  // version only; the remaining fixed header is truncated
        assert(write_all_bytes(enc, malformed));

        AVSAnalyzer::ModelEncryptionConfig cfg;
        cfg.enabled = true;
        cfg.key = key;
        cfg.suffix = suffix;
        cfg.decryptDir = decryptDir.string();

        std::string outPath;
        std::string outDecryptedDir;
        std::string err;
        bool ok = AVSAnalyzer::resolveAndMaybeDecryptModel(
            cfg,
            /*algorithmCode=*/"algo_v2_malformed",
            enc.string(),
            outPath,
            outDecryptedDir,
            err
        );
        assert(!ok);
        assert(err.find("v2") != std::string::npos);
        assert(err.find("header") != std::string::npos);
    }

    fs::remove_all(root);
    return 0;
}
