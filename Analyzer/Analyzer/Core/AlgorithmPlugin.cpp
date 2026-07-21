#include "AlgorithmPlugin.h"

#include "Config.h"
#include "Utils/Log.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <string_view>

#ifdef _WIN32
#include <windows.h>
#else
#include <dlfcn.h>
#endif

namespace AVSAnalyzer {
namespace {
    class AlgorithmPluginInitError final : public std::runtime_error {
    public:
        using std::runtime_error::runtime_error;
    };

    bool endsWithIgnoreCase(std::string_view value, std::string_view suffix) {
        if (value.size() < suffix.size()) {
            return false;
        }
        auto it = value.end() - static_cast<long>(suffix.size());
        for (size_t i = 0; i < suffix.size(); ++i) {
            auto a = static_cast<char>(std::tolower(static_cast<unsigned char>(it[i])));
            auto b = static_cast<char>(std::tolower(static_cast<unsigned char>(suffix[i])));
            if (a != b) {
                return false;
            }
        }
        return true;
    }

    struct PreprocessMapping {
        bool enabled = false;
        int origW = 0;
        int origH = 0;
        float scaleX = 1.0f;
        float scaleY = 1.0f;
        float offsetX = 0.0f;
        float offsetY = 0.0f;
    };

    static int clampInt(int v, int lo, int hi) {
        if (v < lo) return lo;
        if (v > hi) return hi;
        return v;
    }

    static bool preprocessImage(
        const cv::Mat& src,
        int inputW,
        int inputH,
        int mode,
        cv::Mat& out,
        PreprocessMapping& mapping
    ) {
        mapping = PreprocessMapping{};
        if (src.empty() || src.cols <= 0 || src.rows <= 0) {
            return false;
        }
        if (inputW <= 0 || inputH <= 0) {
            return false;
        }

        mapping.origW = src.cols;
        mapping.origH = src.rows;

        // 1=adaptive(letterbox), 2=stretch, 3=rga_stretch(best-effort fallback to stretch)
        if (mode == 2 || mode == 3) {
            cv::resize(src, out, cv::Size(inputW, inputH), 0, 0, cv::INTER_LINEAR);
            mapping.scaleX = static_cast<float>(mapping.origW) / static_cast<float>(inputW);
            mapping.scaleY = static_cast<float>(mapping.origH) / static_cast<float>(inputH);
            mapping.enabled = true;
            return true;
        }

        // mode 1: adaptive (keep aspect ratio, pad to target). Keep padding at top-left for simple mapping.
        const float sx = static_cast<float>(inputW) / static_cast<float>(mapping.origW);
        const float sy = static_cast<float>(inputH) / static_cast<float>(mapping.origH);
        const float scale = std::min(sx, sy);
        if (!std::isfinite(scale) || scale <= 0.0f) {
            return false;
        }
        auto newW = static_cast<int>(std::lround(static_cast<double>(mapping.origW) * static_cast<double>(scale)));
        auto newH = static_cast<int>(std::lround(static_cast<double>(mapping.origH) * static_cast<double>(scale)));
        newW = std::max(1, std::min(newW, inputW));
        newH = std::max(1, std::min(newH, inputH));

        cv::Mat resized;
        cv::resize(src, resized, cv::Size(newW, newH), 0, 0, cv::INTER_LINEAR);
        out = cv::Mat::zeros(cv::Size(inputW, inputH), CV_8UC3);
        resized.copyTo(out(cv::Rect(0, 0, newW, newH)));

        const float inv = 1.0f / scale;
        mapping.scaleX = inv;
        mapping.scaleY = inv;
        mapping.enabled = true;
        return true;
    }

    static void mapDetectToOriginal(DetectObject& d, const PreprocessMapping& m) {
        if (!m.enabled || m.origW <= 0 || m.origH <= 0) {
            return;
        }
        auto mapX = [&](int x) {
            const double v = (static_cast<double>(x) - static_cast<double>(m.offsetX)) * static_cast<double>(m.scaleX);
            auto xi = static_cast<int>(std::lround(v));
            return clampInt(xi, 0, m.origW);
        };
        auto mapY = [&](int y) {
            const double v = (static_cast<double>(y) - static_cast<double>(m.offsetY)) * static_cast<double>(m.scaleY);
            auto yi = static_cast<int>(std::lround(v));
            return clampInt(yi, 0, m.origH);
        };

        d.x1 = mapX(d.x1);
        d.x2 = mapX(d.x2);
        d.y1 = mapY(d.y1);
        d.y2 = mapY(d.y2);

        if (d.hasPose) {
            for (auto& kp : d.keypoints) {
                kp.x = std::max(0.0f, std::min(static_cast<float>(m.origW),
                                               (kp.x - m.offsetX) * m.scaleX));
                kp.y = std::max(0.0f, std::min(static_cast<float>(m.origH),
                                               (kp.y - m.offsetY) * m.scaleY));
            }
        }
    }
}

AlgorithmPlugin::AlgorithmPlugin(const Config* config,
                                 const std::string& libraryPath,
                                 const std::string& algorithmCode,
                                 const std::string& modelPath,
                                 int concurrency,
                                 AlgorithmPluginPreprocessConfig preprocess)
    : Algorithm(config),
      mLibraryPath(libraryPath),
      mAlgorithmCode(algorithmCode),
      mModelPath(modelPath),
      mPreprocess(preprocess) {
    if (concurrency < 1) {
        concurrency = 1;
    }
    if (mPreprocess.inputWidth < 0) mPreprocess.inputWidth = 0;
    if (mPreprocess.inputHeight < 0) mPreprocess.inputHeight = 0;
    if (mPreprocess.inputWidth > 8192) mPreprocess.inputWidth = 8192;
    if (mPreprocess.inputHeight > 8192) mPreprocess.inputHeight = 8192;
    if (mPreprocess.mode < 0 || mPreprocess.mode > 3) {
        mPreprocess.mode = 0;
    }

    try {
        if (!loadLibrary(libraryPath)) {
            throw AlgorithmPluginInitError("loadLibrary failed");
        }

        // Preferred: stable C ABI (SDK v3 function table, pose-capable).
        mGetSdkV3 = reinterpret_cast<GetSdkV3Fn>(resolveSymbol("BeaconGetAlgorithmPluginV3"));
        if (mGetSdkV3) {
            mSdkV3 = mGetSdkV3();
            if (!mSdkV3 ||
                mSdkV3->abi_version != BEACON_PLUGIN_SDK_V3_ABI_VERSION ||
                !mSdkV3->create ||
                !mSdkV3->destroy ||
                !mSdkV3->detect) {
                LOGW("AlgorithmPlugin: SDK v3 symbol present but invalid, fallback to SDK v2/legacy ABI");
                mGetSdkV3 = nullptr;
                mSdkV3 = nullptr;
            }
        }

        // Preferred: stable C ABI (SDK v2 function table).
        mGetSdkV2 = reinterpret_cast<GetSdkV2Fn>(resolveSymbol("BeaconGetAlgorithmPluginV2"));
        if (mGetSdkV2) {
            mSdkV2 = mGetSdkV2();
            if (!mSdkV2 ||
                mSdkV2->abi_version != BEACON_PLUGIN_SDK_V2_ABI_VERSION ||
                !mSdkV2->create ||
                !mSdkV2->destroy ||
                !mSdkV2->detect) {
                LOGW("AlgorithmPlugin: SDK v2 symbol present but invalid, fallback to legacy ABI");
                mGetSdkV2 = nullptr;
                mSdkV2 = nullptr;
            }
        }

        mInstanceMtx.resize(static_cast<size_t>(concurrency));

        if (mSdkV3) {
            mSdkV3Instances.reserve(static_cast<size_t>(concurrency));
            for (int i = 0; i < concurrency; ++i) {
                BeaconPluginInstanceV3 instance = mSdkV3->create(mAlgorithmCode.c_str(), mModelPath.c_str());
                if (!instance) {
                    throw AlgorithmPluginInitError("sdk v3 create failed");
                }
                mSdkV3Instances.push_back(instance);
            }
            // Perf: reuse the output buffer per instance to avoid per-frame allocations.
            constexpr size_t kMaxDetections = 256;
            mSdkV3OutBuffers.resize(mSdkV3Instances.size());
            for (auto& buf : mSdkV3OutBuffers) {
                buf.resize(kMaxDetections);
            }

            setCreateState(!mSdkV3Instances.empty());
            LOGI("AlgorithmPlugin loaded (sdk v3): path=%s, algorithmCode=%s, modelPath=%s, instances=%d",
                 mLibraryPath.c_str(), mAlgorithmCode.c_str(), mModelPath.c_str(), concurrency);
            return;
        }

        if (mSdkV2) {
            mSdkV2Instances.reserve(static_cast<size_t>(concurrency));
            for (int i = 0; i < concurrency; ++i) {
                BeaconPluginInstanceV2 instance = mSdkV2->create(mAlgorithmCode.c_str(), mModelPath.c_str());
                if (!instance) {
                    throw AlgorithmPluginInitError("sdk v2 create failed");
                }
                mSdkV2Instances.push_back(instance);
            }
            // Perf: reuse the output buffer per instance to avoid per-frame allocations.
            constexpr size_t kMaxDetections = 256;
            mSdkV2OutBuffers.resize(mSdkV2Instances.size());
            for (auto& buf : mSdkV2OutBuffers) {
                buf.resize(kMaxDetections);
            }

            setCreateState(!mSdkV2Instances.empty());
            LOGI("AlgorithmPlugin loaded (sdk v2): path=%s, algorithmCode=%s, modelPath=%s, instances=%d",
                 mLibraryPath.c_str(), mAlgorithmCode.c_str(), mModelPath.c_str(), concurrency);
            return;
        }

        // Legacy fallback: C++ Algorithm* ABI (unstable across toolchains, kept for compatibility).
        mLegacyAbi.createV3 = reinterpret_cast<CreateFnV3>(resolveSymbol("BeaconCreateAlgorithmEx"));
        if (!mLegacyAbi.createV3) {
            mLegacyAbi.createV3 = reinterpret_cast<CreateFnV3>(resolveSymbol("BeaconCreateAlgorithmV3"));
        }
        mLegacyAbi.createV2 = reinterpret_cast<CreateFnV2>(resolveSymbol("BeaconCreateAlgorithmV2"));
        mLegacyAbi.createV1 = reinterpret_cast<CreateFnV1>(resolveSymbol("BeaconCreateAlgorithm"));

        mLegacyAbi.destroy = reinterpret_cast<DestroyFn>(resolveSymbol("BeaconDestroyAlgorithm"));
        if (!mLegacyAbi.destroy) {
            mLegacyAbi.destroy = reinterpret_cast<DestroyFn>(resolveSymbol("destroy_algorithm"));
        }

        if ((!mLegacyAbi.createV3 && !mLegacyAbi.createV2 && !mLegacyAbi.createV1) || !mLegacyAbi.destroy) {
            throw AlgorithmPluginInitError("plugin symbols not found (BeaconGetAlgorithmPluginV2 or BeaconCreateAlgorithm*/BeaconDestroyAlgorithm)");
        }

        // Legacy plugin entrypoints still use a mutable Config* in the ABI.
        // Keep a private copy so plugins can mutate their own view without
        // writing through the shared scheduler configuration.
        if (config != nullptr) {
            mLegacyAbi.pluginConfig = std::make_unique<Config>(*config);
        }

        mInstances.reserve(static_cast<size_t>(concurrency));
        for (int i = 0; i < concurrency; ++i) {
            Algorithm* instance = nullptr;
            auto* pluginConfig = mLegacyAbi.pluginConfig.get();
            if (mLegacyAbi.createV3) {
                instance = mLegacyAbi.createV3(pluginConfig, mAlgorithmCode.c_str(), mModelPath.c_str());
            }
            else if (mLegacyAbi.createV2) {
                instance = mLegacyAbi.createV2(pluginConfig, mAlgorithmCode.c_str());
            }
            else if (mLegacyAbi.createV1) {
                instance = mLegacyAbi.createV1(pluginConfig);
            }
            if (!instance || !instance->createState()) {
                if (instance) {
                    mLegacyAbi.destroy(instance);
                }
                throw AlgorithmPluginInitError("plugin instance not ready");
            }
            mInstances.push_back(instance);
        }

        setCreateState(!mInstances.empty());
        LOGI("AlgorithmPlugin loaded (legacy): path=%s, algorithmCode=%s, modelPath=%s, instances=%d",
             mLibraryPath.c_str(), mAlgorithmCode.c_str(), mModelPath.c_str(), concurrency);
    } catch (const std::exception& ex) { // NOSONAR
        LOGE("AlgorithmPlugin init failed: %s", ex.what());
        for (auto instance : mSdkV3Instances) {
            if (instance && mSdkV3 && mSdkV3->destroy) {
                mSdkV3->destroy(instance);
            }
        }
        mSdkV3Instances.clear();
        mSdkV3OutBuffers.clear();
        mSdkV3 = nullptr;
        mGetSdkV3 = nullptr;

        for (auto instance : mSdkV2Instances) {
            if (instance && mSdkV2 && mSdkV2->destroy) {
                mSdkV2->destroy(instance);
            }
        }
        mSdkV2Instances.clear();
        mSdkV2OutBuffers.clear();
        mSdkV2 = nullptr;
        mGetSdkV2 = nullptr;

        for (auto* instance : mInstances) {
            if (instance && mLegacyAbi.destroy) {
                mLegacyAbi.destroy(instance);
            }
        }
        mInstances.clear();
        mInstanceMtx.clear();
        unloadLibrary();
        setCreateState(false);
    }
}

AlgorithmPlugin::~AlgorithmPlugin() {
    for (auto instance : mSdkV3Instances) {
        if (instance && mSdkV3 && mSdkV3->destroy) {
            mSdkV3->destroy(instance);
        }
    }
    mSdkV3Instances.clear();
    mSdkV3OutBuffers.clear();
    mSdkV3 = nullptr;
    mGetSdkV3 = nullptr;

    for (auto instance : mSdkV2Instances) {
        if (instance && mSdkV2 && mSdkV2->destroy) {
            mSdkV2->destroy(instance);
        }
    }
    mSdkV2Instances.clear();
    mSdkV2OutBuffers.clear();
    mSdkV2 = nullptr;
    mGetSdkV2 = nullptr;

    for (auto* instance : mInstances) {
        if (instance && mLegacyAbi.destroy) {
            mLegacyAbi.destroy(instance);
        }
    }
    mInstances.clear();
    mInstanceMtx.clear();
    unloadLibrary();
}

bool AlgorithmPlugin::objectDetect(cv::Mat& image, std::vector<DetectObject>& detects,
                                   float scoreThreshold, float nmsThreshold) {
    if (!createState()) {
        LOGE("AlgorithmPlugin not ready");
        return false;
    }

	    if (mSdkV3 && !mSdkV3Instances.empty()) {
	        const size_t idx = mRR.fetch_add(1) % mSdkV3Instances.size();
	        std::scoped_lock lock(mInstanceMtx[idx]);

        BeaconPluginInstanceV3 instance = mSdkV3Instances[idx];
        if (!instance) {
            LOGE("AlgorithmPlugin sdk v3 instance is null");
            return false;
        }
        if (!image.data || image.cols <= 0 || image.rows <= 0) {
            LOGE("AlgorithmPlugin sdk v3 invalid image");
            return false;
        }

        const cv::Mat* inputMat = &image;
        cv::Mat pre;
        PreprocessMapping mapping;
        if (mPreprocess.mode > 0 && mPreprocess.inputWidth > 0 && mPreprocess.inputHeight > 0 &&
            preprocessImage(image, mPreprocess.inputWidth, mPreprocess.inputHeight, mPreprocess.mode, pre, mapping)) {
            inputMat = &pre;
        }

        BeaconPluginImageV3 in;
        in.bgr = inputMat->data;
        in.width = inputMat->cols;
        in.height = inputMat->rows;
        in.stride = static_cast<int32_t>(inputMat->step);

        constexpr int32_t kMaxDetections = 256;
        if (idx >= mSdkV3OutBuffers.size()) {
            LOGE("AlgorithmPlugin sdk v3 out buffer missing: idx=%zu", idx);
            return false;
        }
        std::vector<BeaconPluginDetectV3>& out = mSdkV3OutBuffers[idx];
        if (out.size() < static_cast<size_t>(kMaxDetections)) {
            out.resize(static_cast<size_t>(kMaxDetections));
        }
        const int32_t n = mSdkV3->detect(instance, &in, scoreThreshold, nmsThreshold,
                                         out.data(), static_cast<int32_t>(out.size()));
        if (n < 0) {
            LOGE("AlgorithmPlugin sdk v3 detect failed");
            return false;
        }

        detects.clear();
        const int32_t limit = std::min<int32_t>(n, static_cast<int32_t>(out.size()));
        detects.reserve(static_cast<size_t>(limit));
        for (int32_t i = 0; i < limit; ++i) {
            const auto& r = out[static_cast<size_t>(i)];
            DetectObject d;
            d.x1 = (int)r.x1;
            d.y1 = (int)r.y1;
            d.x2 = (int)r.x2;
            d.y2 = (int)r.y2;
            d.class_score = r.score;
            d.class_id = (int)r.class_id;
            if (r.class_name) {
                d.class_name = r.class_name;
            }
            if (r.has_pose != 0) {
                d.hasPose = true;
                d.keypoints.reserve(BEACON_PLUGIN_SDK_V3_MAX_KEYPOINTS);
                for (int j = 0; j < BEACON_PLUGIN_SDK_V3_MAX_KEYPOINTS; ++j) {
                    const auto& kp = r.keypoints[j];
                    d.keypoints.emplace_back(kp.x, kp.y, kp.confidence);
                }
            }
            mapDetectToOriginal(d, mapping);
            detects.push_back(d);
        }
        return true;
    }

	    if (mSdkV2 && !mSdkV2Instances.empty()) {
	        const size_t idx = mRR.fetch_add(1) % mSdkV2Instances.size();
	        std::scoped_lock lock(mInstanceMtx[idx]);

        BeaconPluginInstanceV2 instance = mSdkV2Instances[idx];
        if (!instance) {
            LOGE("AlgorithmPlugin sdk v2 instance is null");
            return false;
        }
        if (!image.data || image.cols <= 0 || image.rows <= 0) {
            LOGE("AlgorithmPlugin sdk v2 invalid image");
            return false;
        }

        const cv::Mat* inputMat = &image;
        cv::Mat pre;
        PreprocessMapping mapping;
        if (mPreprocess.mode > 0 && mPreprocess.inputWidth > 0 && mPreprocess.inputHeight > 0 &&
            preprocessImage(image, mPreprocess.inputWidth, mPreprocess.inputHeight, mPreprocess.mode, pre, mapping)) {
            inputMat = &pre;
        }

        BeaconPluginImageV2 in;
        in.bgr = inputMat->data;
        in.width = inputMat->cols;
        in.height = inputMat->rows;
        in.stride = static_cast<int32_t>(inputMat->step);

        constexpr int32_t kMaxDetections = 256;
        if (idx >= mSdkV2OutBuffers.size()) {
            LOGE("AlgorithmPlugin sdk v2 out buffer missing: idx=%zu", idx);
            return false;
        }
        std::vector<BeaconPluginDetectV2>& out = mSdkV2OutBuffers[idx];
        if (out.size() < static_cast<size_t>(kMaxDetections)) {
            out.resize(static_cast<size_t>(kMaxDetections));
        }
        const int32_t n = mSdkV2->detect(instance, &in, scoreThreshold, nmsThreshold,
                                         out.data(), static_cast<int32_t>(out.size()));
        if (n < 0) {
            LOGE("AlgorithmPlugin sdk v2 detect failed");
            return false;
        }

        detects.clear();
        const int32_t limit = std::min<int32_t>(n, static_cast<int32_t>(out.size()));
        detects.reserve(static_cast<size_t>(limit));
        for (int32_t i = 0; i < limit; ++i) {
            const auto& r = out[static_cast<size_t>(i)];
            DetectObject d;
            d.x1 = (int)r.x1;
            d.y1 = (int)r.y1;
            d.x2 = (int)r.x2;
            d.y2 = (int)r.y2;
            d.class_score = r.score;
            d.class_id = (int)r.class_id;
            if (r.class_name) {
                d.class_name = r.class_name;
            }
            mapDetectToOriginal(d, mapping);
            detects.push_back(d);
        }
        return true;
    }

    if (mInstances.empty()) {
        LOGE("AlgorithmPlugin legacy instances empty");
        return false;
    }

	    const size_t idx = mRR.fetch_add(1) % mInstances.size();
	    std::scoped_lock lock(mInstanceMtx[idx]);
	    Algorithm* instance = mInstances[idx];
    if (!instance || !instance->createState()) {
        LOGE("AlgorithmPlugin legacy instance not ready");
        return false;
    }
    return instance->objectDetect(image, detects, scoreThreshold, nmsThreshold);
}

bool AlgorithmPlugin::loadLibrary(const std::string& path) {
    unloadLibrary();

    if (path.empty()) {
        return false;
    }

#ifdef _WIN32
    HMODULE mod = LoadLibraryA(path.c_str());
    if (!mod) {
        LOGE("LoadLibraryA failed: path=%s", path.c_str());
        return false;
    }
    mLibHandle = reinterpret_cast<std::uintptr_t>(mod);
#else
    mLibHandle = reinterpret_cast<std::uintptr_t>(dlopen(path.c_str(), RTLD_NOW)); //NOSONAR - POSIX dlopen returns void*
    if (!mLibHandle) {
        LOGE("dlopen failed: path=%s, err=%s", path.c_str(), dlerror());
        return false;
    }
#endif

    return true;
}

void AlgorithmPlugin::unloadLibrary() {
    if (!mLibHandle) {
        return;
    }
#ifdef _WIN32
    FreeLibrary(reinterpret_cast<HMODULE>(mLibHandle));
#else
    dlclose(reinterpret_cast<void*>(mLibHandle)); //NOSONAR - POSIX dlclose uses void*
#endif
    mLibHandle = 0;
    mGetSdkV3 = nullptr;
    mSdkV3 = nullptr;
    mGetSdkV2 = nullptr;
    mSdkV2 = nullptr;
    mLegacyAbi.createV3 = nullptr;
    mLegacyAbi.createV2 = nullptr;
    mLegacyAbi.createV1 = nullptr;
    mLegacyAbi.destroy = nullptr;
}

std::uintptr_t AlgorithmPlugin::resolveSymbol(const char* name) {
    if (!mLibHandle || !name || !name[0]) {
        return 0;
    }
#ifdef _WIN32
    return reinterpret_cast<std::uintptr_t>(GetProcAddress(reinterpret_cast<HMODULE>(mLibHandle), name));
#else
    return reinterpret_cast<std::uintptr_t>(dlsym(reinterpret_cast<void*>(mLibHandle), name)); //NOSONAR - POSIX dlsym uses void*
#endif
}

} // namespace AVSAnalyzer
