#include "AlgorithmOnYolo.h"
#include "Config.h"
#include "ImagePreprocess.h"
#include "YoloPosePostprocess.h"
#include "YoloOutputLayout.h"
#include "YoloSegmentationPostprocess.h"
#include "Utils/Log.h"
#include "Utils/Common.h"
#include <algorithm>
#include <exception>
#include <new>
#include <stdexcept>
#include <cmath>
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
            LOGI("CUDA provider initialized with device %d", deviceId);
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
            LOGI("TensorRT provider initialized with device %d", deviceId);
            return true;
        }

        // 解析设备字符串，支持格式：CUDA, CUDA:0, CUDA:1, TRT:0, GPU:1 等
        struct DeviceInfo {
            std::string type;   // CUDA, TENSORRT, CPU, AUTO
            int deviceId;       // GPU 设备 ID (0, 1, 2, ...)
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
                // 格式: "CUDA:1" 或 "TRT:0"
                info.type = upper.substr(0, colonPos);
	                try {
	                    info.deviceId = std::stoi(upper.substr(colonPos + 1));
	                    if (info.deviceId < 0) info.deviceId = 0;
	                } catch (const std::invalid_argument&) {
	                    info.deviceId = 0;
	                } catch (const std::out_of_range&) {
	                    info.deviceId = 0;
	                }
            } else {
                // 格式: "CUDA" 或 "GPU"
                info.type = upper;
                info.deviceId = 0;
            }

            // 规范化设备类型名称
            if (info.type == "GPU") {
                info.type = "CUDA";
            } else if (info.type == "TRT") {
                info.type = "TENSORRT";
            }

            return info;
        }
    }

    OnnxRuntimeEngine::OnnxRuntimeEngine(const Config* config, const std::string& modelPath, const std::vector<std::string>& classNames, const std::string& device,
                                         int requestedInputWidth, int requestedInputHeight) :
        OnnxRuntimeEngineModelState{
            classNames,
            modelPath,
            std::max(0, requestedInputWidth),
            std::max(0, requestedInputHeight),
            "CPU",
            0
        }
    {
        (void)config;
        LOGI("modelPath=%s, device=%s, requestedInput=%dx%d", modelPath.data(), device.c_str(), mRequestedInputWidth, mRequestedInputHeight);

        try {
            mEnv = Ort::Env(OrtLoggingLevel::ORT_LOGGING_LEVEL_WARNING, "YOLOV8");
            mSessionOptions = Ort::SessionOptions();
            mSessionOptions.SetGraphOptimizationLevel(ORT_ENABLE_BASIC);

            std::vector<std::string> providers = Ort::GetAvailableProviders();

            LOGI("supported onnxruntime providers");
            for (size_t i = 0; i < providers.size(); i++)
            {
                LOGI("%zu,%s", i, providers[i].data());
            }

            // 解析设备字符串（支持多卡）
            DeviceInfo deviceInfo = parseDevice(device);
            mRequestedDevice = deviceInfo.type;
            mRequestedDeviceId = deviceInfo.deviceId;
            mSelectedProvider = "CPU";
            mTensorRTInitError.clear();
            mCudaInitError.clear();

            std::string selectedProvider = "CPU";

            LOGI("Parsed device: type=%s, deviceId=%d", deviceInfo.type.c_str(), deviceInfo.deviceId);

            if (deviceInfo.type == "AUTO") {
                std::string trtErr;
                if (appendTensorRTProvider(mSessionOptions, providers, deviceInfo.deviceId, trtErr)) {
                    selectedProvider = "TENSORRT";
                }
                else {
                    mTensorRTInitError = trtErr;
                }

                if (selectedProvider != "TENSORRT") {
                    std::string cudaErr;
                    if (appendCudaProvider(mSessionOptions, providers, deviceInfo.deviceId, cudaErr)) {
                        selectedProvider = "CUDA";
                    }
                    else {
                        mCudaInitError = cudaErr;
                    }
                }
            }
            else if (deviceInfo.type == "TENSORRT") {
                std::string trtErr;
                if (!appendTensorRTProvider(mSessionOptions, providers, deviceInfo.deviceId, trtErr)) {
                    mTensorRTInitError = trtErr;
                    LOGE("TensorRT provider init failed: %s", trtErr.c_str());
                    mReady = false;
                    return;
                }
                selectedProvider = "TENSORRT";
            }
            else if (deviceInfo.type == "CUDA") {
                std::string cudaErr;
                if (!appendCudaProvider(mSessionOptions, providers, deviceInfo.deviceId, cudaErr)) {
                    mCudaInitError = cudaErr;
                    LOGE("CUDA provider init failed: %s", cudaErr.c_str());
                    mReady = false;
                    return;
                }
                selectedProvider = "CUDA";
            }

            mSelectedProvider = selectedProvider;
            LOGI("onnxruntime provider selected: %s (requested=%s, deviceId=%d)",
                 selectedProvider.c_str(), deviceInfo.type.c_str(), deviceInfo.deviceId);
#ifdef WIN32
            //const ORTCHAR_T* modelPath_ws_str = L"data/yolov8n.onnx";
            std::wstring modelPath_ws = std::wstring(modelPath.begin(), modelPath.end());
            mSession = Ort::Session(mEnv, modelPath_ws.c_str(), mSessionOptions);
#else
            mSession = Ort::Session(mEnv, modelPath.c_str(), mSessionOptions);
#endif

            mReady = initModelIO();
        }
        catch (const Ort::Exception& ex) {
            LOGE("onnxruntime init error: %s", ex.what());
            mReady = false;
        }
    }

    OnnxRuntimeEngine::~OnnxRuntimeEngine() = default;
    bool OnnxRuntimeEngine::isReady() const {
        return mReady;
    }
    std::string OnnxRuntimeEngine::getPreprocessReport() const {
        return "preprocess=shared_opencv_cpu(legacy_square_pad_rgb_nchw_fp32), cuda_preprocess=no, cuda_stream_reuse=no";
    }
    bool OnnxRuntimeEngine::initModelIO() {
        Ort::AllocatorWithDefaultOptions allocator;
        size_t numInputNodes = mSession.GetInputCount();
        size_t numOutputNodes = mSession.GetOutputCount();
        if (numInputNodes == 0 || numOutputNodes == 0) {
            LOGE("invalid model io: inputs=%zu, outputs=%zu", numInputNodes, numOutputNodes);
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
                if (input_dims[2] > 0) {
                    mInputHeight = static_cast<int>(input_dims[2]);
                }
                if (input_dims[3] > 0) {
                    mInputWidth = static_cast<int>(input_dims[3]);
                }
            }
        }

        if (mRequestedInputWidth > 0 && mRequestedInputHeight > 0 &&
            mInputWidth > 0 && mInputHeight > 0 &&
            (mInputWidth != mRequestedInputWidth || mInputHeight != mRequestedInputHeight)) {
            LOGW("requested input %dx%d ignored (model static input %dx%d)",
                 mRequestedInputWidth, mRequestedInputHeight, mInputWidth, mInputHeight);
        }

        if (mInputHeight <= 0 || mInputWidth <= 0) {
            // Dynamic/unknown input shape: allow per-control override.
            int fallbackH = (mRequestedInputHeight > 0) ? mRequestedInputHeight : 640;
            int fallbackW = (mRequestedInputWidth > 0) ? mRequestedInputWidth : 640;
            LOGW("invalid/dynamic input shape, fallback to %dx%d (requested=%dx%d)",
                 fallbackW, fallbackH, mRequestedInputWidth, mRequestedInputHeight);
            if (mInputHeight <= 0) mInputHeight = fallbackH;
            if (mInputWidth <= 0) mInputWidth = fallbackW;
        }
        mInputTensorSize = static_cast<size_t>(mInputHeight) * static_cast<size_t>(mInputWidth) * 3;
        mInputShapeInfo = { 1, 3, mInputHeight, mInputWidth };

        mOutputNames.reserve(numOutputNodes);
        std::vector<std::vector<int64_t>> outputShapes;
        outputShapes.reserve(numOutputNodes);
        for (size_t i = 0; i < numOutputNodes; i++) {
            auto out_name = mSession.GetOutputNameAllocated(i, allocator);
            mOutputNames.push_back(out_name.get());

            Ort::TypeInfo output_type_info = mSession.GetOutputTypeInfo(i);
            auto output_tensor_info = output_type_info.GetTensorTypeAndShapeInfo();
            outputShapes.push_back(output_tensor_info.GetShape());
        }

        YoloOutputLayout layout;
        std::string layoutErr;
        size_t selected = 0;
        if (!selectYoloDetectionOutput(outputShapes, static_cast<int>(mClassNames.size()), selected, layout, layoutErr)) {
            LOGE("unsupported output layout (outputs=%zu): %s", outputShapes.size(), layoutErr.c_str());
            return false;
        }
        if (selected >= mOutputNames.size()) {
            LOGE("invalid selected output index=%zu (outputs=%zu)", selected, mOutputNames.size());
            return false;
        }
        mSelectedOutputIndex = selected;
        mOutputDim = layout.dim;
        mOutputRow = layout.rows;
        mOutputRowsFirst = layout.rowsFirst;

        LOGI("yolo output selected: index=%zu name=%s rows=%d dim=%d",
             mSelectedOutputIndex, mOutputNames[mSelectedOutputIndex].c_str(), mOutputRow, mOutputDim);

        // Best-effort model output format:
        // - AABB YOLOv8: [cx,cy,w,h,cls...]
        // - AABB YOLOv5: [cx,cy,w,h,obj,cls...]
        // - OBB YOLOv8:  [cx,cy,w,h,angle,cls...]
        // - OBB YOLOv5:  [cx,cy,w,h,angle,obj,cls...]
        mHasObjectness = false;
        mHasAngle = false;
        mHasSegmentation = false;
        mIndex4ObjOrAngleAmbiguous = false;
        mIndex4ObjOrAngleDecided = false;
        mIndex4UseObjectness = true;

        mClassOffset = 4;
        if (mOutputDim >= 6) {
            int classCountV8 = mOutputDim - 4;
            int classCountV5 = mOutputDim - 5;
            if (!mClassNames.empty()) {
                if (classCountV5 == static_cast<int>(mClassNames.size()) && classCountV8 != static_cast<int>(mClassNames.size())) {
                    mHasObjectness = true;
                }
            }
            else {
                // 无类别列表时，按常见维度猜测
                if (mOutputDim == 85) {
                    mHasObjectness = true;
                }
            }
        }
        if (mHasObjectness) {
            mClassOffset = 5;
        }

        // OBB hint: model filename/path contains "obb" (common in YOLOv8-obb/YOLO11-obb exports).
        // For exact ambiguous dims (5 + classCount), defer decision to runtime when not hinted.
        if (!mClassNames.empty()) {
            const auto clsCount = static_cast<int>(mClassNames.size());
            std::string lowerPath = mModelPath;
            std::transform(lowerPath.begin(), lowerPath.end(), lowerPath.begin(),
                [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
            const bool hintedObb = (lowerPath.find("obb") != std::string::npos);

            if (hintedObb) {
                // Prefer explicit OBB layouts.
                if (mOutputDim >= (6 + clsCount)) {
                    mHasAngle = true;
                    mHasObjectness = true;
                    mClassOffset = 6;
                }
                else if (mOutputDim >= (5 + clsCount)) {
                    mHasAngle = true;
                    mHasObjectness = false;
                    mClassOffset = 5;
                }
            }
            else if (mOutputDim == (5 + clsCount)) {
                // Ambiguous: could be YOLOv5 (obj) or YOLO-OBB (angle). Decide after first inference.
                mIndex4ObjOrAngleAmbiguous = true;
                mIndex4ObjOrAngleDecided = false;
                mIndex4UseObjectness = true;
                mHasObjectness = false; // do not assume; will be decided
                mHasAngle = false;
                mClassOffset = 5;
            }
        }

        if (!mHasAngle && !mClassNames.empty()) {
            const int base = 4 + (mHasAngle ? 1 : 0) + (mHasObjectness ? 1 : 0);
            const int coeffDim = mOutputDim - (base + static_cast<int>(mClassNames.size()));
            if (coeffDim > 0) {
                std::string protoErr;
                if (selectYoloSegmentationPrototypeOutput(
                        outputShapes,
                        mSelectedOutputIndex,
                        coeffDim,
                        mProtoOutputIndex,
                        mProtoLayout,
                        protoErr)) {
                    mHasSegmentation = true;
                    LOGI("yolo seg prototype selected: index=%zu name=%s channels=%d size=%dx%d",
                         mProtoOutputIndex,
                         (mProtoOutputIndex < mOutputNames.size() ? mOutputNames[mProtoOutputIndex].c_str() : ""),
                         mProtoLayout.channels,
                         mProtoLayout.width,
                         mProtoLayout.height);
                }
                else {
                    LOGW("yolo seg prototype not selected (coeff=%d): %s", coeffDim, protoErr.c_str());
                }
            }
        }

        if (!isValidYoloDetectionModelIo(mInputNames.size(), mOutputNames.size(), mOutputDim, mOutputRow)) {
            LOGE("invalid model io details, output_dim=%d, output_row=%d", mOutputDim, mOutputRow);
            return false;
        }

        return true;
    }
    bool OnnxRuntimeEngine::runInference(const cv::Mat& image, std::vector<DetectObject>& detects,
        float scoreThreshold, float nmsThreshold) {
        if (!mReady) {
            LOGE("engine is not ready");
            return false;
        }
        int image_w = image.cols;
        int image_h = image.rows;

        float score_threshold = scoreThreshold;
        float nms_threshold = nmsThreshold;
        if (!std::isfinite(score_threshold) || score_threshold < 0.0f || score_threshold > 1.0f) {
            score_threshold = 0.5f;
        }
        if (!std::isfinite(nms_threshold) || nms_threshold < 0.0f || nms_threshold > 1.0f) {
            nms_threshold = 0.5f;
        }

        ImagePreprocessBlob preprocessed;
        std::string preprocessErr;
        if (!preprocessImageToNchw(image, mInputWidth, mInputHeight, ImagePreprocessMode::Letterbox, preprocessed, preprocessErr)) {
            LOGE("onnx yolo preprocess failed: %s", preprocessErr.c_str());
            return false;
        }

        float x_factor = 1.0f;
        float y_factor = 1.0f;
        if (!preprocessed.mappings.empty()) {
            x_factor = preprocessed.mappings[0].scaleX;
            y_factor = preprocessed.mappings[0].scaleY;
        }

        // set input data and inference
        auto allocator_info = Ort::MemoryInfo::CreateCpu(OrtDeviceAllocator, OrtMemTypeCPU);
        Ort::Value input_tensor_ = Ort::Value::CreateTensor<float>(
            allocator_info,
            preprocessed.data(),
            preprocessed.elementCount(),
            mInputShapeInfo.data(),
            mInputShapeInfo.size()
        );
        const std::array<const char*, 1> inputNames = { mInputNames[0].c_str() };
        std::vector<const char*> outNames;
        outNames.reserve(mHasSegmentation ? 2 : 1);
        outNames.push_back(mOutputNames[mSelectedOutputIndex].c_str());
        if (mHasSegmentation && mProtoOutputIndex < mOutputNames.size()) {
            outNames.push_back(mOutputNames[mProtoOutputIndex].c_str());
        }

        std::vector<Ort::Value> ort_outputs = mSession.Run(
            Ort::RunOptions{ nullptr },
            inputNames.data(),
            &input_tensor_,
            1,
            outNames.data(),
            outNames.size());


        // output data
        float* pdata = ort_outputs[0].GetTensorMutableData<float>();
        const float* protoData = nullptr;
        if (mHasSegmentation && ort_outputs.size() >= 2) {
            protoData = ort_outputs[1].GetTensorMutableData<float>();
        }
        cv::Mat det_output;
        if (mOutputRowsFirst) {
            det_output = cv::Mat(mOutputRow, mOutputDim, CV_32F, pdata);
        }
        else {
            cv::Mat dout(mOutputDim, mOutputRow, CV_32F, pdata);
            det_output = dout.t(); // rows x dim
        }

        // post-process
        if (isYolov8PoseDim(mOutputDim)) {
            std::vector<cv::Rect> boxes;
            std::vector<float> confidences;
            std::vector<YoloPoseResult> candidates;

            boxes.reserve(static_cast<size_t>(det_output.rows));
            confidences.reserve(static_cast<size_t>(det_output.rows));
            candidates.reserve(static_cast<size_t>(det_output.rows));

            for (int i = 0; i < det_output.rows; i++) {
                const float* row = det_output.ptr<float>(i);
                YoloPoseResult cand;
                if (!parseYolov8PoseRow(row, mOutputDim, x_factor, y_factor, cand)) {
                    continue;
                }
                if (cand.score > score_threshold) {
                    cv::Rect box;
                    box.x = cand.x1;
                    box.y = cand.y1;
                    box.width = cand.x2 - cand.x1;
                    box.height = cand.y2 - cand.y1;

                    boxes.push_back(box);
                    confidences.push_back(cand.score);
                    candidates.push_back(cand);
                }
            }

            // NMS
            std::vector<int> indexes;
            cv::dnn::NMSBoxes(boxes, confidences, score_threshold, nms_threshold, indexes);

            detects.clear();
            detects.reserve(indexes.size());

            for (size_t i = 0; i < indexes.size(); i++) {
                int index = indexes[i];
                if (index < 0 || index >= static_cast<int>(candidates.size())) {
                    continue;
                }
                const auto& cand = candidates[static_cast<size_t>(index)];

                DetectObject detect;
                detect.x1 = cand.x1;
                detect.y1 = cand.y1;
                detect.x2 = cand.x2;
                detect.y2 = cand.y2;
                detect.class_id = cand.class_id;
                if (!mClassNames.empty()) {
                    detect.class_name = mClassNames[0];
                }
                else {
                    detect.class_name = "person";
                }
                detect.class_score = cand.score;

                detect.hasPose = cand.hasPose;
                if (cand.hasPose) {
                    detect.keypoints.reserve(cand.keypoints.size());
                    for (const auto& kp : cand.keypoints) {
                        detect.keypoints.emplace_back(kp.x, kp.y, kp.confidence);
                    }
                }

                detects.push_back(detect);
            }

            return true;
        }

        // Disambiguate the common ambiguous layout:
        //   [cx,cy,w,h,?,cls...] where ? can be objectness (YOLOv5) or angle (YOLO-OBB).
        bool hasObjectness = mHasObjectness;
        bool hasAngle = mHasAngle;

        if (mIndex4ObjOrAngleAmbiguous) {
            if (!mIndex4ObjOrAngleDecided) {
                bool looksLikeAngle = false;
                const int sampleN = std::min(det_output.rows, 32);
                for (int i = 0; i < sampleN; ++i) {
                    const float v = det_output.at<float>(i, 4);
                    if (!std::isfinite(v)) {
                        continue;
                    }
                    if (v < 0.0f || v > 1.0f) {
                        looksLikeAngle = true;
                        break;
                    }
                }
                mIndex4UseObjectness = !looksLikeAngle;
                mIndex4ObjOrAngleDecided = true;
            }
            if (mIndex4UseObjectness) {
                hasObjectness = true;
                hasAngle = false;
            }
            else {
                hasObjectness = false;
                hasAngle = true;
            }

            // Cache decision in the engine instance (thread-safe via per-engine mutex in AlgorithmOnYolo::objectDetect).
            mHasObjectness = hasObjectness;
            mHasAngle = hasAngle;
            mClassOffset = 4 + (hasAngle ? 1 : 0) + (hasObjectness ? 1 : 0);
        }

        if (mHasSegmentation && !hasAngle && protoData != nullptr) {
            YoloDetectionFormat detectFormat;
            detectFormat.outputDim = mOutputDim;
            detectFormat.hasObjectness = hasObjectness;
	            detectFormat.hasAngle = false;
	            detectFormat.classOffset = 4 + (hasObjectness ? 1 : 0);

	            std::string segErr;
	            YoloSegmentationDecodeOptions segOptions;
	            segOptions.classNames = &mClassNames;
	            segOptions.scoreThreshold = score_threshold;
	            segOptions.nmsThreshold = nms_threshold;
	            segOptions.xFactor = x_factor;
	            segOptions.yFactor = y_factor;
	            segOptions.imageWidth = image_w;
	            segOptions.imageHeight = image_h;
	            YoloDetectionDecodeOutput segOutput;
	            segOutput.format = &detectFormat;
	            segOutput.detects = &detects;
	            segOutput.errMsg = &segErr;
	            if (!decodeYoloSegmentationDetections(det_output, protoData, mProtoLayout, segOptions, segOutput)) {
	                LOGE("yolo seg postprocess failed: %s", segErr.c_str());
	                return false;
	            }

            mHasObjectness = detectFormat.hasObjectness;
            mHasAngle = detectFormat.hasAngle;
            mClassOffset = detectFormat.classOffset;
            return true;
        }

        const int base = 4 + (hasAngle ? 1 : 0) + (hasObjectness ? 1 : 0);
        int model_classes = mOutputDim - base;
        if (model_classes <= 0) {
            LOGE("invalid output dim=%d (base=%d)", mOutputDim, base);
            return false;
        }
        int class_begin = base;
        int class_range = model_classes;
        if (!mClassNames.empty()) {
            class_range = std::min(model_classes, static_cast<int>(mClassNames.size()));
        }
        int class_end = class_begin + class_range;

        std::vector<cv::Rect> boxes;
        std::vector<int> classIds;
        std::vector<float> confidences;
        std::vector<std::array<cv::Point2f, 4>> obbCorners;
        if (hasAngle) {
            obbCorners.reserve(static_cast<size_t>(det_output.rows));
        }

        const float kPi = 3.14159265358979323846f;

        for (int i = 0; i < det_output.rows; i++) {
            cv::Mat classes_scores = det_output.row(i).colRange(class_begin, class_end);
            cv::Point classIdPoint;
            double score;
            minMaxLoc(classes_scores, nullptr, &score, nullptr, &classIdPoint);

            float obj = 1.0f;
            if (hasObjectness) {
                const int objIndex = base - 1;
                obj = det_output.at<float>(i, objIndex);
                if (!std::isfinite(obj)) {
                    obj = 0.0f;
                }
                score = score * obj;
            }

            if (score > score_threshold) {
                float cx = det_output.at<float>(i, 0);
                float cy = det_output.at<float>(i, 1);
                float ow = det_output.at<float>(i, 2);
                float oh = det_output.at<float>(i, 3);

                if (hasAngle) {
                    float angle = det_output.at<float>(i, 4);
                    if (!std::isfinite(angle)) {
                        angle = 0.0f;
                    }

                    // YOLO-OBB exports vary: some use radians, some degrees. Heuristic:
                    // - abs(angle) <= ~pi => radians
                    // - otherwise treat as degrees.
                    float angleDeg = angle;
                    if (std::fabs(angle) <= 3.2f) {
                        angleDeg = angle * 180.0f / kPi;
                    }

                    const float cxp = cx * x_factor;
                    const float cyp = cy * y_factor;
                    const float wp = ow * x_factor;
                    const float hp = oh * y_factor;

                    cv::RotatedRect rr(cv::Point2f(cxp, cyp), cv::Size2f(wp, hp), angleDeg);
                    cv::Point2f pts[4];
                    rr.points(pts);

                    std::array<cv::Point2f, 4> corners;
                    for (int k = 0; k < 4; ++k) {
                        corners[k] = pts[k];
                    }
                    cv::Rect box = rr.boundingRect();

                    boxes.push_back(box);
                    classIds.push_back(classIdPoint.x);
                    confidences.push_back(static_cast<float>(score));
                    obbCorners.push_back(corners);
                }
                else {
                    const auto x = static_cast<int>((cx - 0.5f * ow) * x_factor);
                    const auto y = static_cast<int>((cy - 0.5f * oh) * y_factor);
                    const auto width = static_cast<int>(ow * x_factor);
                    const auto height = static_cast<int>(oh * y_factor);

                    cv::Rect box;
                    box.x = x;
                    box.y = y;
                    box.width = width;
                    box.height = height;

                    boxes.push_back(box);
                    classIds.push_back(classIdPoint.x);
                    confidences.push_back(static_cast<float>(score));
                }
            }
        }

        // NMS
        std::vector<int> indexes;
        cv::dnn::NMSBoxes(boxes, confidences, score_threshold, nms_threshold, indexes);

        detects.clear();
        detects.reserve(indexes.size());

        for (size_t i = 0; i < indexes.size(); i++) {
            int index = indexes[i];
            if (index < 0 || index >= static_cast<int>(boxes.size())) {
                continue;
            }

            int class_id = classIds[index];
            float class_score = confidences[index];
            cv::Rect box = boxes[index];

            DetectObject detect;
            detect.x1 = box.x;
            detect.y1 = box.y;
            detect.x2 = box.x + box.width;
            detect.y2 = box.y + box.height;
            detect.class_id = class_id;
            if (class_id >= 0 && class_id < static_cast<int>(mClassNames.size())) {
                detect.class_name = mClassNames[class_id];
            }
            else {
                detect.class_name = "unknown";
            }
            detect.class_score = class_score;

            if (hasAngle && index < static_cast<int>(obbCorners.size())) {
                detect.hasObb = true;
                detect.obb = obbCorners[static_cast<size_t>(index)];
            }

            detects.push_back(detect);
        }

        return true;
    }
    AlgorithmOnYolo::AlgorithmOnYolo(const Config* config, const std::string& modelPath, const std::vector<std::string>& classNames, const std::string& device,
                                     int concurrency, int requestedInputWidth, int requestedInputHeight) :Algorithm(config),
        mClassNames(classNames),
        mDevice(device.empty() ? "CPU" : device) {
        if (concurrency < 1) {
            concurrency = 1;
        }
        LOGI("modelPath=%s, device=%s, concurrency=%d, requestedInput=%dx%d",
             modelPath.data(), mDevice.c_str(), concurrency, requestedInputWidth, requestedInputHeight);
	        try {
	            mEngines.reserve(static_cast<size_t>(concurrency));
	            mEngineMtx.resize(static_cast<size_t>(concurrency));
	            for (int i = 0; i < concurrency; ++i) {
	                auto engine = std::make_unique<OnnxRuntimeEngine>(config, modelPath, classNames, mDevice, requestedInputWidth, requestedInputHeight);
	                if (!engine || !engine->isReady()) {
	                    LOGE("failed to init onnxruntime engine");
	                    mEngines.clear();
	                    mEngineMtx.clear();
	                    setCreateState(false);
	                    return;
	                }
	                mEngines.push_back(std::move(engine));
	            }
	            setCreateState(!mEngines.empty());
	        }
	        catch (const Ort::Exception& ex) {
	            LOGE("onnxruntime engine ort exception: %s", ex.what());
	            mEngines.clear();
	            mEngineMtx.clear();
	            setCreateState(false);
	        }
	        catch (const std::bad_alloc& ex) {
	            LOGE("onnxruntime engine bad_alloc: %s", ex.what());
	            mEngines.clear();
	            mEngineMtx.clear();
	            setCreateState(false);
	        }
	    }

	    AlgorithmOnYolo::~AlgorithmOnYolo()
	    {
	        LOGI("");
	        mEngines.clear();
	        mEngineMtx.clear();
	    }

	    bool AlgorithmOnYolo::objectDetect(cv::Mat& image, std::vector<DetectObject>& detects,
	        float scoreThreshold, float nmsThreshold){
	        if (!createState() || mEngines.empty()) {
	            LOGE("onnxruntime engine not ready");
	            return false;
	        }
	        size_t idx = mRR.fetch_add(1) % mEngines.size();
	        std::scoped_lock lock(mEngineMtx[idx]);
	        auto* engine = mEngines[idx].get();
	        if (!engine || !engine->isReady()) {
	            LOGE("onnxruntime engine not ready");
	            return false;
	        }
	        return engine->runInference(image, detects, scoreThreshold, nmsThreshold);
	    }

    std::string AlgorithmOnYolo::getSelectedProvider() const {
        if (!mEngines.empty() && mEngines[0]) {
            return mEngines[0]->getSelectedProvider();
        }
        return "CPU";
    }

	    std::string AlgorithmOnYolo::getProviderInitReport() const {
	        if (mEngines.empty() || !mEngines[0]) {
	            return "";
	        }
	        const auto* e = mEngines[0].get();
	        std::string report;
	        report += "requested=" + e->getRequestedDevice();
        report += ":" + std::to_string(e->getRequestedDeviceId());
        report += ", selected=" + e->getSelectedProvider();
        const std::string trtErr = e->getTensorRTInitError();
        const std::string cudaErr = e->getCudaInitError();
        if (!trtErr.empty()) {
            report += ", tensorrt_error=" + trtErr;
        }
        if (!cudaErr.empty()) {
            report += ", cuda_error=" + cudaErr;
        }
        report += ", " + e->getPreprocessReport();
        return report;
    }

}
