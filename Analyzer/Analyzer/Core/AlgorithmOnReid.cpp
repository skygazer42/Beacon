#include "AlgorithmOnReid.h"

#include "Config.h"
#include "ImagePreprocess.h"
#include "ReidFeature.h"
#include "Utils/Log.h"

#include <algorithm>
#include <exception>
#include <new>
#include <stdexcept>
#include <cctype>
#if defined(_WIN32)
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#else
#include <dlfcn.h>
#endif

namespace AVSAnalyzer {
    namespace {
#if defined(_WIN32)
        template <typename Fn>
        Fn lookupOrtProviderSymbol(const char* name) {
            HMODULE module = GetModuleHandleA("onnxruntime.dll");
            if (!module) {
                module = LoadLibraryA("onnxruntime.dll");
            }
            if (!module) {
                return nullptr;
            }
            return reinterpret_cast<Fn>(GetProcAddress(module, name));
        }
#else
        template <typename Fn>
        Fn lookupOrtProviderSymbol(const char* name) {
            return reinterpret_cast<Fn>(dlsym(RTLD_DEFAULT, name));
        }
#endif

        std::string toUpper(std::string value) {
            std::transform(value.begin(), value.end(), value.begin(),
                [](unsigned char c) { return static_cast<char>(std::toupper(c)); });
            return value;
        }

        bool hasProvider(const std::vector<std::string>& providers, const std::string& name) {
            return std::find(providers.begin(), providers.end(), name) != providers.end();
        }

        bool appendCudaProvider(Ort::SessionOptions& options, const std::vector<std::string>& providers, int deviceId, std::string& errMsg) {
            if (!hasProvider(providers, "CUDAExecutionProvider")) {
                errMsg = "CUDAExecutionProvider not available";
                return false;
            }
            using AppendCudaProviderFn = OrtStatus* (*)(OrtSessionOptions*, int) noexcept;
            const auto appendCuda = lookupOrtProviderSymbol<AppendCudaProviderFn>("OrtSessionOptionsAppendExecutionProvider_CUDA");
            if (!appendCuda) {
                errMsg = "CUDAExecutionProvider symbol not linked";
                return false;
            }
            OrtStatus* status = appendCuda(options, deviceId);
            if (status != nullptr) {
                errMsg = Ort::GetApi().GetErrorMessage(status);
                Ort::GetApi().ReleaseStatus(status);
                return false;
            }
            return true;
        }

        bool appendTensorRTProvider(Ort::SessionOptions& options, const std::vector<std::string>& providers, int deviceId, std::string& errMsg) {
            if (!hasProvider(providers, "TensorrtExecutionProvider")) {
                errMsg = "TensorrtExecutionProvider not available";
                return false;
            }
            using AppendTensorRtProviderFn = OrtStatus* (*)(OrtSessionOptions*, int) noexcept;
            const auto appendTensorRt = lookupOrtProviderSymbol<AppendTensorRtProviderFn>("OrtSessionOptionsAppendExecutionProvider_Tensorrt");
            if (!appendTensorRt) {
                errMsg = "TensorrtExecutionProvider symbol not linked";
                return false;
            }
            OrtStatus* status = appendTensorRt(options, deviceId);
            if (status != nullptr) {
                errMsg = Ort::GetApi().GetErrorMessage(status);
                Ort::GetApi().ReleaseStatus(status);
                return false;
            }
            return true;
        }

        struct DeviceInfo {
            std::string type; // CUDA/TENSORRT/CPU/AUTO
            int deviceId;
        };

        DeviceInfo parseDevice(const std::string& device) {
            DeviceInfo info;
            info.type = "CPU";
            info.deviceId = 0;
            if (device.empty()) {
                return info;
            }
            std::string upper = toUpper(device);
            if (const size_t colonPos = upper.find(':'); colonPos != std::string::npos) {
                info.type = upper.substr(0, colonPos);
                try {
                    info.deviceId = std::stoi(upper.substr(colonPos + 1));
                    if (info.deviceId < 0) info.deviceId = 0;
                }
                catch (const std::invalid_argument&) {
                    info.deviceId = 0;
                }
                catch (const std::out_of_range&) {
                    info.deviceId = 0;
                }
            }
            else {
                info.type = upper;
                info.deviceId = 0;
            }

            if (info.type == "GPU") info.type = "CUDA";
            if (info.type == "TRT") info.type = "TENSORRT";
            return info;
        }
    }

    OnnxRuntimeReidEngine::OnnxRuntimeReidEngine(
        const Config* config,
        const std::string& modelPath,
        const std::string& device,
        int requestedInputWidth,
        int requestedInputHeight
    ) : mModelPath(modelPath),
        mDevice(device.empty() ? "CPU" : device),
        mRequestedInputWidth(std::max(0, requestedInputWidth)),
        mRequestedInputHeight(std::max(0, requestedInputHeight)) {
        (void)config;
        LOGI("ReID(onnx) modelPath=%s device=%s requestedInput=%dx%d",
             modelPath.c_str(), mDevice.c_str(), mRequestedInputWidth, mRequestedInputHeight);

        try {
            mEnv = Ort::Env(OrtLoggingLevel::ORT_LOGGING_LEVEL_WARNING, "BEACON_REID");
            mSessionOptions = Ort::SessionOptions();
            mSessionOptions.SetGraphOptimizationLevel(ORT_ENABLE_BASIC);

            std::vector<std::string> providers = Ort::GetAvailableProviders();
            DeviceInfo deviceInfo = parseDevice(mDevice);

            std::string selectedProvider = "CPU";
            std::string err;
            if (deviceInfo.type == "AUTO") {
                if (appendTensorRTProvider(mSessionOptions, providers, deviceInfo.deviceId, err)) {
                    selectedProvider = "TENSORRT";
                }
                else if (appendCudaProvider(mSessionOptions, providers, deviceInfo.deviceId, err)) {
                    selectedProvider = "CUDA";
                }
            }
            else if (deviceInfo.type == "TENSORRT") {
                if (!appendTensorRTProvider(mSessionOptions, providers, deviceInfo.deviceId, err)) {
                    LOGE("ReID(onnx) tensorrt init failed: %s", err.c_str());
                    mReady = false;
                    return;
                }
                selectedProvider = "TENSORRT";
            }
            else if (deviceInfo.type == "CUDA") {
                if (!appendCudaProvider(mSessionOptions, providers, deviceInfo.deviceId, err)) {
                    LOGE("ReID(onnx) cuda init failed: %s", err.c_str());
                    mReady = false;
                    return;
                }
                selectedProvider = "CUDA";
            }
            else {
                selectedProvider = "CPU";
            }
            LOGI("ReID(onnx) provider selected=%s", selectedProvider.c_str());

#ifdef _WIN32
            std::wstring modelPath_ws = std::wstring(modelPath.begin(), modelPath.end());
            mSession = Ort::Session(mEnv, modelPath_ws.c_str(), mSessionOptions);
#else
            mSession = Ort::Session(mEnv, modelPath.c_str(), mSessionOptions);
#endif

            std::string ioErr;
            mReady = initModelIO(ioErr);
            if (!mReady) {
                LOGE("ReID(onnx) initModelIO failed: %s", ioErr.c_str());
            }
        }
        catch (const Ort::Exception& ex) {
            LOGE("ReID(onnx) init error: %s", ex.what());
            mReady = false;
        }
        catch (const std::exception& ex) { // NOSONAR
            LOGE("ReID(onnx) exception: %s", ex.what());
            mReady = false;
        }
    }

    OnnxRuntimeReidEngine::~OnnxRuntimeReidEngine() = default;

    bool OnnxRuntimeReidEngine::initModelIO(std::string& errMsg) {
        Ort::AllocatorWithDefaultOptions allocator;
        size_t numInputNodes = mSession.GetInputCount();
        size_t numOutputNodes = mSession.GetOutputCount();
        if (numInputNodes == 0 || numOutputNodes == 0) {
            errMsg = "invalid model io";
            return false;
        }

        mInputNames.reserve(numInputNodes);
        for (size_t i = 0; i < numInputNodes; i++) {
            auto input_name = mSession.GetInputNameAllocated(i, allocator);
            mInputNames.push_back(input_name.get());
            Ort::TypeInfo input_type_info = mSession.GetInputTypeInfo(i);
            auto input_tensor_info = input_type_info.GetTensorTypeAndShapeInfo();
            auto input_dims = input_tensor_info.GetShape();
            if (input_dims.size() >= 4) {
                if (input_dims[0] != 0) {
                    mInputBatchDim = input_dims[0];
                }
                if (input_dims[2] > 0) mInputHeight = static_cast<int>(input_dims[2]);
                if (input_dims[3] > 0) mInputWidth = static_cast<int>(input_dims[3]);
            }
        }

        if (mInputHeight <= 0 || mInputWidth <= 0) {
            int fallbackH = (mRequestedInputHeight > 0) ? mRequestedInputHeight : 640;
            int fallbackW = (mRequestedInputWidth > 0) ? mRequestedInputWidth : 640;
            LOGW("ReID(onnx) dynamic input shape, fallback to %dx%d (requested=%dx%d)",
                 fallbackW, fallbackH, mRequestedInputWidth, mRequestedInputHeight);
            if (mInputHeight <= 0) mInputHeight = fallbackH;
            if (mInputWidth <= 0) mInputWidth = fallbackW;
        }

        // Output: expect [N, D] or [N, D, 1, 1] (D may be dynamic at init)
        try {
            Ort::TypeInfo output_type_info = mSession.GetOutputTypeInfo(0);
            auto output_tensor_info = output_type_info.GetTensorTypeAndShapeInfo();
            auto output_dims = output_tensor_info.GetShape();
            if (output_dims.size() >= 2 && output_dims[1] > 0) {
                mEmbeddingDim = static_cast<int>(output_dims[1]);
            }
        } catch (const Ort::Exception&) {}

        mOutputNames.reserve(numOutputNodes);
        for (size_t i = 0; i < numOutputNodes; i++) {
            auto out_name = mSession.GetOutputNameAllocated(i, allocator);
            mOutputNames.push_back(out_name.get());
        }

        if (mInputNames.empty() || mOutputNames.empty()) {
            errMsg = "empty input/output names";
            return false;
        }
        return true;
    }

    bool OnnxRuntimeReidEngine::extractEmbeddings(
        const std::vector<cv::Mat>& images,
        std::vector<std::vector<float>>& embeddings,
        std::string& errMsg
    ) {
        embeddings.clear();
        if (!mReady) {
            errMsg = "engine not ready";
            return false;
        }
        if (images.empty()) {
            errMsg.clear();
            return true;
        }
        if (mInputWidth <= 0 || mInputHeight <= 0) {
            errMsg = "invalid input shape";
            return false;
        }

        // Some exported models have static batch=1. In that case, run per-image inference.
        if (mInputBatchDim == 1 && images.size() > 1) {
            embeddings.reserve(images.size());
            for (const auto& img : images) {
                std::vector<cv::Mat> one{ img };
                std::vector<std::vector<float>> oneOut;
                std::string oneErr;
                if (!extractEmbeddings(one, oneOut, oneErr)) {
                    errMsg = oneErr;
                    embeddings.clear();
                    return false;
                }
                if (!oneOut.empty()) {
                    embeddings.push_back(std::move(oneOut[0]));
                } else {
                    embeddings.push_back(std::vector<float>());
                }
            }
            errMsg.clear();
            return true;
        }

        ImagePreprocessBlob blob;
        if (!preprocessImagesToNchw(images, mInputWidth, mInputHeight, ImagePreprocessMode::Stretch, blob, errMsg)) {
            if (errMsg.empty()) {
                errMsg = "preprocessImagesToNchw failed";
            }
            return false;
        }

        const auto batch = static_cast<int64_t>(blob.batch);
        std::vector<int64_t> inputShape = { batch, 3, mInputHeight, mInputWidth };

        Ort::MemoryInfo memoryInfo = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
        float* inputData = blob.data();
        size_t inputCount = blob.elementCount();

        Ort::Value inputTensor = Ort::Value::CreateTensor<float>(
            memoryInfo,
            inputData,
            inputCount,
            inputShape.data(),
            inputShape.size()
        );

        const char* inputNames[] = { mInputNames[0].c_str() };
        const char* outputNames[] = { mOutputNames[0].c_str() };

        std::vector<Ort::Value> outputs;
        try {
            outputs = mSession.Run(
                Ort::RunOptions{ nullptr },
                inputNames,
                &inputTensor,
                1,
                outputNames,
                1
            );
        }
        catch (const Ort::Exception& ex) {
            errMsg = ex.what();
            return false;
        }

        if (outputs.empty() || !outputs[0].IsTensor()) {
            errMsg = "empty output";
            return false;
        }

        Ort::Value& out = outputs[0];
        auto outInfo = out.GetTensorTypeAndShapeInfo();
        std::vector<int64_t> outShape = outInfo.GetShape();
        const size_t outCount = outInfo.GetElementCount();

        int outBatch = 0;
        int dim = 0;
        if (outShape.size() >= 2) {
            outBatch = static_cast<int>(outShape[0]);
            dim = static_cast<int>(outShape[1]);
        }
        if (outBatch <= 0) {
            outBatch = static_cast<int>(batch);
        }
        if (dim <= 0 && outBatch > 0) {
            dim = static_cast<int>(outCount / static_cast<size_t>(outBatch));
        }
        if (dim <= 0) {
            errMsg = "invalid embedding dim";
            return false;
        }
        if (outBatch != static_cast<int>(batch)) {
            LOGW("ReID(onnx) output batch mismatch outBatch=%d reqBatch=%d", outBatch, (int)batch);
        }

        const float* outData = out.GetTensorMutableData<float>();
        embeddings.reserve(static_cast<size_t>(batch));
        for (int i = 0; i < static_cast<int>(batch); ++i) {
            std::vector<float> feat(static_cast<size_t>(dim));
            const size_t offset = static_cast<size_t>(i) * static_cast<size_t>(dim);
            for (int j = 0; j < dim; ++j) {
                size_t idx = offset + static_cast<size_t>(j);
                feat[static_cast<size_t>(j)] = (idx < outCount) ? outData[idx] : 0.0f;
            }
            reid_l2_normalize(feat);
            embeddings.push_back(std::move(feat));
        }

        if (mEmbeddingDim <= 0) {
            mEmbeddingDim = dim;
        }
        errMsg.clear();
        return true;
    }

    AlgorithmOnReid::AlgorithmOnReid(
        const Config* config,
        const std::string& modelPath,
        const std::string& device,
        int concurrency,
        int requestedInputWidth,
        int requestedInputHeight
    ) : Algorithm(config), mDevice(device.empty() ? "CPU" : device) {
        if (concurrency < 1) concurrency = 1;
        LOGI("AlgorithmOnReid device=%s concurrency=%d requestedInput=%dx%d", mDevice.c_str(), concurrency, requestedInputWidth, requestedInputHeight);
	        try {
	            mEngines.reserve(static_cast<size_t>(concurrency));
	            mEngineMtx.resize(static_cast<size_t>(concurrency));
	            for (int i = 0; i < concurrency; ++i) {
	                auto engine = std::make_unique<OnnxRuntimeReidEngine>(config, modelPath, mDevice, requestedInputWidth, requestedInputHeight);
	                if (!engine || !engine->isReady()) {
	                    LOGE("failed to init reid engine");
	                    mEngines.clear();
	                    mEngineMtx.clear();
	                    setCreateState(false);
	                    return;
	                }
	                mEngines.push_back(std::move(engine));
	            }
	            setCreateState(!mEngines.empty());
	        }
	        catch (const std::bad_alloc& ex) {
	            LOGE("AlgorithmOnReid init exception: %s", ex.what());
	            mEngines.clear();
	            mEngineMtx.clear();
	            setCreateState(false);
	        }
	    }

	    AlgorithmOnReid::~AlgorithmOnReid() {
	        mEngines.clear();
	        mEngineMtx.clear();
	    }

    bool AlgorithmOnReid::objectDetect(cv::Mat& image, std::vector<DetectObject>& detects, float scoreThreshold, float nmsThreshold) {
        (void)image;
        (void)detects;
        (void)scoreThreshold;
        (void)nmsThreshold;
        LOGE("AlgorithmOnReid::objectDetect called (unsupported)");
        return false;
    }

	    bool AlgorithmOnReid::extractEmbeddings(
        const std::vector<cv::Mat>& images,
        std::vector<std::vector<float>>& embeddings,
        std::string& errMsg
	    ) {
	        if (!createState() || mEngines.empty()) {
	            errMsg = "reid engine not ready";
	            embeddings.clear();
	            return false;
	        }
	        size_t idx = mRR.fetch_add(1) % mEngines.size();
	        std::scoped_lock lock(mEngineMtx[idx]);
	        auto* engine = mEngines[idx].get();
	        if (!engine || !engine->isReady()) {
	            errMsg = "reid engine not ready";
	            embeddings.clear();
	            return false;
	        }
	        return engine->extractEmbeddings(images, embeddings, errMsg);
	    }

	    int AlgorithmOnReid::embeddingDim() const {
	        if (!mEngines.empty() && mEngines[0]) {
	            return mEngines[0]->embeddingDim();
	        }
	        return 0;
	    }

} // namespace AVSAnalyzer
