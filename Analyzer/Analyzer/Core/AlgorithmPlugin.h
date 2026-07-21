#ifndef ANALYZER_ALGORITHMPLUGIN_H
#define ANALYZER_ALGORITHMPLUGIN_H

#include <atomic>
#include <cstdint>
#include <deque>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

#include "Algorithm.h"
#include "PluginSdkV3.h"
#include "PluginSdkV2.h"

namespace AVSAnalyzer {
class Config;

struct AlgorithmPluginPreprocessConfig {
    int inputWidth = 0;
    int inputHeight = 0;
    int mode = 0;
};

class AlgorithmPlugin : public Algorithm {
public:
    // 兼容多版本插件导出接口，按优先级逐级回退
    using GetSdkV3Fn = BeaconGetAlgorithmPluginV3Fn;
    using GetSdkV2Fn = BeaconGetAlgorithmPluginV2Fn;
    using CreateFnV3 = Algorithm* (*)(Config* config, const char* algorithmCode, const char* modelPath);
    using CreateFnV2 = Algorithm* (*)(Config* config, const char* algorithmCode);
    using CreateFnV1 = Algorithm* (*)(Config* config);
    using DestroyFn  = void (*)(Algorithm* algorithm);

    AlgorithmPlugin(const Config* config,
                    const std::string& libraryPath,
                    const std::string& algorithmCode,
                    const std::string& modelPath,
                    int concurrency = 1,
                    AlgorithmPluginPreprocessConfig preprocess = {});
    ~AlgorithmPlugin() override;

    bool objectDetect(cv::Mat& image, std::vector<DetectObject>& detects,
                      float scoreThreshold, float nmsThreshold) override;

private:
    bool loadLibrary(const std::string& path);
    void unloadLibrary();
    std::uintptr_t resolveSymbol(const char* name);

private:
    struct LegacyAbiState {
        CreateFnV3 createV3 = nullptr;
        CreateFnV2 createV2 = nullptr;
        CreateFnV1 createV1 = nullptr;
        DestroyFn destroy = nullptr;
        std::unique_ptr<Config> pluginConfig;
    };

    std::string mLibraryPath;
    std::string mAlgorithmCode;
    std::string mModelPath;

    AlgorithmPluginPreprocessConfig mPreprocess;

    std::uintptr_t mLibHandle = 0;
    // Preferred: stable C ABI (SDK v3 function table, pose-capable).
    GetSdkV3Fn mGetSdkV3 = nullptr;
    const BeaconAlgorithmPluginV3* mSdkV3 = nullptr;

    // Preferred: stable C ABI (SDK v2)
    GetSdkV2Fn mGetSdkV2 = nullptr;
    const BeaconAlgorithmPluginV2* mSdkV2 = nullptr;

    LegacyAbiState mLegacyAbi;

    std::vector<Algorithm*> mInstances;
    std::vector<BeaconPluginInstanceV3> mSdkV3Instances;
    std::vector<std::vector<BeaconPluginDetectV3>> mSdkV3OutBuffers;
    std::vector<BeaconPluginInstanceV2> mSdkV2Instances;
    std::vector<std::vector<BeaconPluginDetectV2>> mSdkV2OutBuffers;
    std::deque<std::mutex> mInstanceMtx;
    std::atomic<size_t> mRR{0};
};

} // namespace AVSAnalyzer

#endif // ANALYZER_ALGORITHMPLUGIN_H
