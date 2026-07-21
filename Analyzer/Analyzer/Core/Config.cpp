#include "Config.h"
#include <fstream>
#include <iostream>
#include <filesystem>
#include <algorithm>
#include <cctype>
#include <exception>
#include <stdexcept>
#include <cstdlib>
#include <json/json.h>
#include "Utils/Log.h"
#include "Version.h"

namespace AVSAnalyzer {
    namespace {
        std::string trim(std::string value) {
            auto notSpace = [](unsigned char ch) { return !std::isspace(ch); };
            value.erase(value.begin(), std::find_if(value.begin(), value.end(), notSpace));
            value.erase(std::find_if(value.rbegin(), value.rend(), notSpace).base(), value.end());
            return value;
        }

        bool looksLikeWindowsAbsPath(const std::string& value) {
            if (value.size() < 3) {
                return false;
            }
            const auto drive = static_cast<unsigned char>(value[0]);
            return std::isalpha(drive) && value[1] == ':' && (value[2] == '\\' || value[2] == '/');
        }

        std::string resolveConfigPath(
            const Json::Value& root,
            const std::filesystem::path& configDir,
            const char* envName,
            const char* jsonKey,
            const std::string& defaultRelative) {
            std::string value = trim(root.get(jsonKey, "").asString());
            if (const char* envValue = std::getenv(envName); envValue && *envValue) {
                value = trim(envValue);
            }
            if (value.empty()) {
                value = defaultRelative;
            }
            if (value.empty()) {
                return std::string();
            }

#ifndef _WIN32
            if (looksLikeWindowsAbsPath(value)) {
                LOGW("config.%s looks like a Windows path on non-Windows: %s; fallback to %s",
                     jsonKey, value.c_str(), defaultRelative.c_str());
                value = defaultRelative;
            }
#endif
            if (value.empty()) {
                return std::string();
            }

            std::filesystem::path path(value);
            if (path.is_relative()) {
                path = configDir / path;
            }
            return path.lexically_normal().string();
        }
    }

    Config::Config(const char* configFilePath) :
        ConfigRuntimeState{ false, configFilePath }
    {

        std::ifstream ifs(configFilePath, std::ios::binary);

        if (!ifs.is_open()) {
            LOGE("open %s error", configFilePath);
            return;
        }
        else {
            Json::CharReaderBuilder builder;
            builder["collectComments"] = true;
            JSONCPP_STRING errs;
            Json::Value root;

            if (parseFromStream(builder, ifs, &root, &errs)) {
                auto readInt = [&](const char* key, int defaultValue) {
                    const Json::Value& node = root[key];
                    if (node.isInt()) {
                        return node.asInt();
                    }
                    if (node.isString()) {
                        try {
                            return std::stoi(node.asString());
                        }
                        catch (const std::invalid_argument&) {
                            return defaultValue;
                        }
                        catch (const std::out_of_range&) {
                            return defaultValue;
                        }
                    }
                    return defaultValue;
                };
                std::filesystem::path configDir;
                try {
                    configDir = std::filesystem::absolute(std::filesystem::path(file)).parent_path();
                }
                catch (const std::filesystem::filesystem_error&) {
                    try {
                        configDir = std::filesystem::current_path();
                    }
                    catch (const std::filesystem::filesystem_error&) {
                        configDir = ".";
                    }
                }

                this->code = root["code"].asString();
                this->host = root["host"].asString();
                this->adminPort = root["adminPort"].asInt();
                const std::string internalAdminHost =
                    (this->host.empty() || this->host == "0.0.0.0" || this->host == "::")
                        ? "127.0.0.1"
                        : this->host;
                this->adminHost = "http://" + internalAdminHost + ":" + std::to_string(this->adminPort);
                this->licenseType = trim(root.get("licenseType", "").asString());
                if (const char* envLicenseType = std::getenv("BEACON_LICENSE_TYPE"); envLicenseType && *envLicenseType) {
                    this->licenseType = trim(envLicenseType);
                }
                this->licenseKey = trim(root.get("licenseKey", "").asString());
                if (const char* envLicenseKey = std::getenv("BEACON_LICENSE_KEY"); envLicenseKey && *envLicenseKey) {
                    this->licenseKey = trim(envLicenseKey);
                }
                this->licenseDongleCmd = trim(root.get("licenseDongleCmd", "").asString());
                if (const char* envDongleCmd = std::getenv("BEACON_LICENSE_DONGLE_CMD"); envDongleCmd && *envDongleCmd) {
                    this->licenseDongleCmd = trim(envDongleCmd);
                }
                this->licenseDongleFile = resolveConfigPath(root, configDir, "BEACON_LICENSE_DONGLE_FILE", "licenseDongleFile", "license.dongle");
                this->openApiToken = trim(root.get("openApiToken", "").asString());
                if (const char* envToken = std::getenv("BEACON_OPEN_API_TOKEN"); envToken && *envToken) {
                    this->openApiToken = trim(envToken);
                }
                this->analyzerPort = root["analyzerPort"].asInt();
                this->mediaHttpPort = root["mediaHttpPort"].asInt();
                this->mediaRtspPort = root["mediaRtspPort"].asInt();

                // Paths can be injected via env (preferred for production), or configured in config.json.
                // Relative paths are resolved from the directory containing config.json.
                this->uploadDir = resolveConfigPath(root, configDir, "BEACON_UPLOAD_DIR", "uploadDir", "Admin/static/upload");
                this->modelDir = resolveConfigPath(root, configDir, "BEACON_MODEL_DIR", "modelDir", "Analyzer/models");
                this->faceDefaultFeatureAlgorithmCode = trim(root.get("faceDefaultFeatureAlgorithmCode", "").asString());
                if (const char* envFaceDefault = std::getenv("BEACON_FACE_DEFAULT_FEATURE_ALGORITHM_CODE"); envFaceDefault && *envFaceDefault) {
                    this->faceDefaultFeatureAlgorithmCode = trim(envFaceDefault);
                }
                this->alarmQueueMaxSize = std::max(1, readInt("alarmQueueMaxSize", this->alarmQueueMaxSize));
                this->alarmPrefixFrames = std::max(1, readInt("alarmPrefixFrames", this->alarmPrefixFrames));
                this->alarmTotalFrames = std::max(this->alarmPrefixFrames, readInt("alarmTotalFrames", this->alarmTotalFrames));
                this->alarmVideoSeconds = std::max(0, readInt("alarmVideoSeconds", this->alarmVideoSeconds));
                this->alarmMergeWindowSeconds = std::max(1, std::min(3600, readInt("alarmMergeWindowSeconds", this->alarmMergeWindowSeconds)));
                this->alarmSegmentMaxSeconds = std::max(1, std::min(3600, readInt("alarmSegmentMaxSeconds", this->alarmSegmentMaxSeconds)));
                int pushDelaySec = std::max(0, readInt("alarmPushDelaySeconds", 0));
                this->alarmPushDelayMs = std::max(0, pushDelaySec * 1000);
                this->alarmEncodeProfile = trim(root.get("alarmEncodeProfile", this->alarmEncodeProfile).asString());
                std::transform(this->alarmEncodeProfile.begin(), this->alarmEncodeProfile.end(), this->alarmEncodeProfile.begin(),
                    [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
                if (this->alarmEncodeProfile.empty()) {
                    this->alarmEncodeProfile = "balanced";
                }
                if (this->alarmEncodeProfile != "balanced" && this->alarmEncodeProfile != "high_quality" && this->alarmEncodeProfile != "low_cpu") {
                    LOGW("Unknown alarmEncodeProfile '%s', fallback to balanced", this->alarmEncodeProfile.c_str());
                    this->alarmEncodeProfile = "balanced";
                }
                this->modelEncrypt = root.get("modelEncrypt", false).asBool();
                this->modelEncryptKey = root.get("modelEncryptKey", "").asString();
                {
                    std::string suffix = trim(root.get("modelEncryptSuffix", this->modelEncryptSuffix).asString());
                    if (const char* envSuffix = std::getenv("BEACON_MODEL_ENCRYPT_SUFFIX"); envSuffix && *envSuffix) {
                        suffix = trim(envSuffix);
                    }
                    if (suffix.empty()) {
                        suffix = this->modelEncryptSuffix;
                    }
                    if (!suffix.empty() && suffix[0] != '.') {
                        suffix.insert(suffix.begin(), '.');
                    }
                    std::transform(suffix.begin(), suffix.end(), suffix.begin(),
                        [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
                    if (suffix.size() > 16) {
                        suffix = ".enc";
                    }
                    this->modelEncryptSuffix = suffix;
                }
                this->modelDecryptDir = resolveConfigPath(root, configDir, "BEACON_MODEL_DECRYPT_DIR", "modelDecryptDir", "");
                // 兼容历史字段名：modelCacheTime（秒）
                int legacyCacheTime = readInt("modelCacheTime", this->modelCacheSeconds);
	                this->modelCacheSeconds = std::max(0, readInt("modelCacheSeconds", legacyCacheTime));
	                this->modelConcurrency = std::max(1, readInt("modelConcurrency", this->modelConcurrency));
                {
                    std::string pluginPath = trim(root.get("tensorrtEnginePluginPath", "").asString());
                    if (!pluginPath.empty()) {
                        std::filesystem::path path(pluginPath);
                        if (path.is_relative()) {
                            path = configDir / path;
                        }
                        this->tensorrtEnginePluginPath = path.lexically_normal().string();
                    }
                }
	                this->compatLibPath = resolveConfigPath(root, configDir, "BEACON_COMPAT_LIB_PATH", "compatLibPath", "");
	                this->rknpuPreprocessMode = std::max(0, std::min(3, readInt("rknpuPreprocessMode", this->rknpuPreprocessMode)));
                if (const char* envPre = std::getenv("BEACON_RKNPU_PREPROCESS_MODE"); envPre && *envPre) {
                    try {
                        this->rknpuPreprocessMode = std::max(0, std::min(3, std::stoi(trim(envPre))));
                    }
                    catch (const std::invalid_argument&) {}
                    catch (const std::out_of_range&) {}
                }
	                this->maxHardwareDecodeChannels = std::max(0, readInt("maxHardwareDecodeChannels", this->maxHardwareDecodeChannels));
	                this->maxHardwareEncodeChannels = std::max(0, readInt("maxHardwareEncodeChannels", this->maxHardwareEncodeChannels));
	                this->maxControls = std::max(1, readInt("maxControls", this->maxControls));
	                this->maxPendingControls = std::max(1, readInt("maxPendingControls", this->maxPendingControls));
                this->ffmpegDecodeThreadCount = std::max(0, readInt("ffmpegDecodeThreadCount", this->ffmpegDecodeThreadCount));
                this->ffmpegEncodeThreadCount = std::max(0, readInt("ffmpegEncodeThreadCount", this->ffmpegEncodeThreadCount));

                // ========== API 推理（外部服务）稳定性保护 ==========
	                auto readEnvInt = [&](const char* envName, int defaultValue) {
	                    if (const char* envValue = std::getenv(envName); envValue && *envValue) {
	                        try {
	                            return std::stoi(trim(envValue));
                        }
                        catch (const std::invalid_argument&) {
                            return defaultValue;
                        }
                        catch (const std::out_of_range&) {
                            return defaultValue;
                        }
                    }
                    return defaultValue;
                };

                {
                    int connectTimeout = readInt("apiInferConnectTimeoutSeconds", this->apiInferConnectTimeoutSeconds);
                    connectTimeout = readEnvInt("BEACON_API_INFER_CONNECT_TIMEOUT_SECONDS", connectTimeout);
                    this->apiInferConnectTimeoutSeconds = std::max(1, std::min(60, connectTimeout));

                    int timeout = readInt("apiInferTimeoutSeconds", this->apiInferTimeoutSeconds);
                    timeout = readEnvInt("BEACON_API_INFER_TIMEOUT_SECONDS", timeout);
                    this->apiInferTimeoutSeconds = std::max(1, std::min(300, timeout));

                    int retryMax = readInt("apiInferRetryMax", this->apiInferRetryMax);
                    retryMax = readEnvInt("BEACON_API_INFER_RETRY_MAX", retryMax);
                    this->apiInferRetryMax = std::max(0, std::min(10, retryMax));

                    int cbFails = readInt("apiInferCircuitBreakerFails", this->apiInferCircuitBreakerFails);
                    cbFails = readEnvInt("BEACON_API_INFER_CIRCUIT_BREAKER_FAILS", cbFails);
                    this->apiInferCircuitBreakerFails = std::max(0, std::min(100, cbFails));

                    int cbOpenSec = readInt("apiInferCircuitBreakerOpenSeconds", this->apiInferCircuitBreakerOpenSeconds);
                    cbOpenSec = readEnvInt("BEACON_API_INFER_CIRCUIT_BREAKER_OPEN_SECONDS", cbOpenSec);
                    this->apiInferCircuitBreakerOpenSeconds = std::max(0, std::min(3600, cbOpenSec));

                    int minIntervalMs = readInt("apiInferMinIntervalMs", this->apiInferMinIntervalMs);
                    minIntervalMs = readEnvInt("BEACON_API_INFER_MIN_INTERVAL_MS", minIntervalMs);
                    this->apiInferMinIntervalMs = std::max(0, std::min(10 * 60 * 1000, minIntervalMs));
                }
                // ==========================================

	                // ========== 硬件编解码配置 ==========
	                this->hardwareDecoderType = root.get("hardwareDecoderType", this->hardwareDecoderType).asString();
	                this->hardwareEncoderType = root.get("hardwareEncoderType", this->hardwareEncoderType).asString();
	                this->forceHardwareCodec = root.get("forceHardwareCodec", this->forceHardwareCodec).asBool();
                this->hardwareCodecDeviceId = std::max(0, readInt("hardwareCodecDeviceId", this->hardwareCodecDeviceId));
                // ==========================================

                // ========== License Manager（浮动池授权） ==========
                this->licenseLeaseTtlSeconds = std::max(30, std::min(600, readInt("licenseLeaseTtlSeconds", this->licenseLeaseTtlSeconds)));
                this->licenseGraceSeconds = std::max(0, readInt("licenseGraceSeconds", this->licenseGraceSeconds));
                if (const char* envTtl = std::getenv("BEACON_LICENSE_LEASE_TTL_SECONDS"); envTtl && *envTtl) {
                    try {
                        this->licenseLeaseTtlSeconds = std::max(30, std::min(600, std::stoi(trim(envTtl))));
                    }
                    catch (const std::invalid_argument&) {}
                    catch (const std::out_of_range&) {}
                }
                if (const char* envGrace = std::getenv("BEACON_LICENSE_GRACE_SECONDS"); envGrace && *envGrace) {
                    try {
                        this->licenseGraceSeconds = std::max(0, std::stoi(trim(envGrace)));
                    }
                    catch (const std::invalid_argument&) {}
                    catch (const std::out_of_range&) {}
                }
                // ==========================================

                if (this->modelDecryptDir.empty()) {
                    this->modelDecryptDir = this->uploadDir + "/.model_cache";
                }

                try {
                    if (!this->uploadDir.empty()) {
                        std::filesystem::create_directories(std::filesystem::path(this->uploadDir));
                    }
                    if (!this->modelDir.empty()) {
                        std::filesystem::create_directories(std::filesystem::path(this->modelDir));
                    }

                    mState = true;
                }
                catch (std::filesystem::filesystem_error& e) {
                    std::cout << e.what() << std::endl;
                }

              
            }
            else {
                LOGE("parse %s error", file);
            }
            ifs.close();
        }
    }

    Config::~Config() = default;

    void Config::show() {

        printf("config.file=%s\n", file);
        printf("config.host=%s\n", host.data());
        printf("config.adminPort=%d\n", adminPort);
        printf("config.analyzerPort=%d\n", analyzerPort);
        printf("config.mediaHttpPort=%d\n", mediaHttpPort);
        printf("config.mediaRtspPort=%d\n", mediaRtspPort);
        printf("config.licenseType=%s\n", licenseType.c_str());
        printf("config.licenseKey=%s\n", licenseKey.empty() ? "" : "***");
        printf("config.licenseDongleCmd=%s\n", licenseDongleCmd.c_str());
        printf("config.licenseDongleFile=%s\n", licenseDongleFile.c_str());
        printf("config.openApiToken=%s\n", openApiToken.empty() ? "" : "***");

        printf("config.uploadDir=%s\n", uploadDir.data());
        printf("config.modelDir=%s\n", modelDir.data());
        printf("config.faceDefaultFeatureAlgorithmCode=%s\n", faceDefaultFeatureAlgorithmCode.c_str());
        printf("config.alarmQueueMaxSize=%d\n", alarmQueueMaxSize);
        printf("config.alarmPrefixFrames=%d\n", alarmPrefixFrames);
        printf("config.alarmTotalFrames=%d\n", alarmTotalFrames);
        printf("config.alarmVideoSeconds=%d\n", alarmVideoSeconds);
        printf("config.alarmMergeWindowSeconds=%d\n", alarmMergeWindowSeconds);
        printf("config.alarmSegmentMaxSeconds=%d\n", alarmSegmentMaxSeconds);
        printf("config.alarmPushDelayMs=%d\n", alarmPushDelayMs);
        printf("config.alarmEncodeProfile=%s\n", alarmEncodeProfile.c_str());
        printf("config.modelEncrypt=%d\n", modelEncrypt ? 1 : 0);
        printf("config.modelEncryptSuffix=%s\n", modelEncryptSuffix.c_str());
        printf("config.modelCacheSeconds=%d\n", modelCacheSeconds);
        printf("config.modelConcurrency=%d\n", modelConcurrency);
        printf("config.tensorrtEnginePluginPath=%s\n", tensorrtEnginePluginPath.c_str());
        printf("config.compatLibPath=%s\n", compatLibPath.c_str());
        printf("config.rknpuPreprocessMode=%d\n", rknpuPreprocessMode);
        printf("config.maxHardwareDecodeChannels=%d\n", maxHardwareDecodeChannels);
        printf("config.maxHardwareEncodeChannels=%d\n", maxHardwareEncodeChannels);
        printf("config.maxControls=%d\n", maxControls);
        printf("config.maxPendingControls=%d\n", maxPendingControls);
        printf("config.ffmpegDecodeThreadCount=%d\n", ffmpegDecodeThreadCount);
        printf("config.ffmpegEncodeThreadCount=%d\n", ffmpegEncodeThreadCount);
        printf("config.hardwareDecoderType=%s\n", hardwareDecoderType.c_str());
        printf("config.hardwareEncoderType=%s\n", hardwareEncoderType.c_str());
        printf("config.forceHardwareCodec=%d\n", forceHardwareCodec ? 1 : 0);
        printf("config.hardwareCodecDeviceId=%d\n", hardwareCodecDeviceId);
        printf("config.licenseLeaseTtlSeconds=%d\n", licenseLeaseTtlSeconds);
        printf("config.licenseGraceSeconds=%d\n", licenseGraceSeconds);


	    }

	    std::string Config::resolveFaceFeatureAlgorithmCode(const std::string& requestedCode) const {
	        if (const std::string requested = trim(requestedCode); !requested.empty()) {
	            return requested;
	        }
	        return trim(faceDefaultFeatureAlgorithmCode);
	    }
}
