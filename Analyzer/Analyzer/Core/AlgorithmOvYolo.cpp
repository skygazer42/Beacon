#include "AlgorithmOvYolo.h"
#include "Config.h"
#include "ImagePreprocess.h"
#include "YoloOutputLayout.h"
#include "Utils/Log.h"
#include "Utils/Common.h"
#include <algorithm>
#include <exception>
#include <new>
#include <cmath>

namespace AVSAnalyzer {

    namespace {

        void applyCompiledInputShape(const ov::CompiledModel& model, int& inputWidth, int& inputHeight) {
            try {
                auto inShape = model.input().get_shape();
                if (inShape.size() >= 4) {
                    const auto h = static_cast<int>(inShape[2]);
                    const auto w = static_cast<int>(inShape[3]);
                    if (w > 0) inputWidth = w;
                    if (h > 0) inputHeight = h;
                }
            } catch (const ov::Exception&) {}
        }

        void detectClassifierOutput(const ov::CompiledModel& model, bool& isClassifier, int& classifierClassCount) {
            try {
                auto outShape = model.output().get_shape();
                const bool isFlatClassifier = outShape.size() == 2 && outShape[0] == 1 && outShape[1] > 1;
                const bool isSpatialClassifier =
                    outShape.size() == 4 && outShape[0] == 1 && outShape[2] == 1 && outShape[3] == 1 && outShape[1] > 1;
                if (isFlatClassifier || isSpatialClassifier) {
                    isClassifier = true;
                    classifierClassCount = static_cast<int>(outShape[1]);
                }
            } catch (const ov::Exception&) {}
        }

        std::vector<std::vector<int64_t>> collectOutputShapes(const ov::CompiledModel& model) {
            std::vector<std::vector<int64_t>> outputShapes;
            try {
                const auto outs = model.outputs();
                outputShapes.reserve(outs.size());
                for (const auto& out : outs) {
                    std::vector<int64_t> dims;
                    const auto shape = out.get_shape();
                    dims.reserve(shape.size());
                    for (size_t i = 0; i < shape.size(); ++i) {
                        dims.push_back(static_cast<int64_t>(shape[i]));
                    }
                    outputShapes.push_back(std::move(dims));
                }
            } catch (const ov::Exception&) {}
            return outputShapes;
        }

    }  // namespace

    AlgorithmOvYolo::AlgorithmOvYolo(const Config* config, const std::string& modelPath, const std::vector<std::string>& classNames, const std::string& device,
                                     int concurrency, int requestedInputWidth, int requestedInputHeight):
        Algorithm(config), mClassNames(classNames), mDevice(device.empty() ? "CPU" : device) {
        if (concurrency < 1) {
            concurrency = 1;
        }
        if (requestedInputWidth > 0) mInputWidth = requestedInputWidth;
        if (requestedInputHeight > 0) mInputHeight = requestedInputHeight;
	        LOGI("modelPath=%s, device=%s, concurrency=%d, requestedInput=%dx%d",
	             modelPath.data(), mDevice.c_str(), concurrency, requestedInputWidth, requestedInputHeight);
	        try {
	            core = std::make_unique<ov::Core>();
	            compiled_model = core->compile_model(modelPath, mDevice);
            applyCompiledInputShape(compiled_model, mInputWidth, mInputHeight);
            detectClassifierOutput(compiled_model, mIsClassifier, mClassifierClassCount);

            if (mIsClassifier) {
                LOGI("OpenVINO model detected as classifier (classes=%d)", mClassifierClassCount);
            }
            else {
                // v4.646: seg models can have multiple outputs (e.g. prototypes + detection head). Select the
                // output that looks like YOLO detection output (bbox + class scores [+ extras]).
                std::vector<std::vector<int64_t>> outputShapes = collectOutputShapes(compiled_model);

                YoloOutputLayout layout;
                std::string layoutErr;
                size_t selected = 0;
                if (!selectYoloDetectionOutput(outputShapes, static_cast<int>(mClassNames.size()), selected, layout, layoutErr)) {
                    LOGE("openvino yolo output selection failed (outputs=%zu): %s", outputShapes.size(), layoutErr.c_str());
                    core.reset();
                    setCreateState(false);
                    return;
                }
                mSelectedOutputIndex = selected;
                mDetectFormat = inferYoloDetectionFormat(layout.dim, static_cast<int>(mClassNames.size()), modelPath);
                mHasSegmentation = false;
                if (!mDetectFormat.hasAngle && !mClassNames.empty()) {
                    const int base = 4 + (mDetectFormat.hasAngle ? 1 : 0) + (mDetectFormat.hasObjectness ? 1 : 0);
                    const int coeffDim = layout.dim - (base + static_cast<int>(mClassNames.size()));
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
                            LOGI("openvino yolo seg prototype selected: index=%zu channels=%d size=%dx%d",
                                 mProtoOutputIndex,
                                 mProtoLayout.channels,
                                 mProtoLayout.width,
                                 mProtoLayout.height);
                        } else {
                            LOGW("openvino yolo seg prototype not selected (coeff=%d): %s", coeffDim, protoErr.c_str());
                        }
                    }
                }
                LOGI("openvino yolo output selected: index=%zu rows=%d dim=%d", mSelectedOutputIndex, layout.rows, layout.dim);
            }

            if (mInputWidth <= 0) mInputWidth = 640;
            if (mInputHeight <= 0) mInputHeight = 640;

            mRequests.reserve(static_cast<size_t>(concurrency));
            mReqMtx.resize(static_cast<size_t>(concurrency));
            for (int i = 0; i < concurrency; ++i) {
                mRequests.emplace_back(compiled_model.create_infer_request());
            }
            setCreateState(true);
        }
	        catch (const ov::Exception& ex) {
	            LOGE("openvino init error: %s", ex.what());
	            core.reset();
	            setCreateState(false);
	        }
	        catch (const std::bad_alloc& ex) {
	            LOGE("openvino init bad_alloc: %s", ex.what());
	            core.reset();
	            setCreateState(false);
	        }
	    }

	    AlgorithmOvYolo::~AlgorithmOvYolo()
	    {
	        LOGI("");
	        core.reset();

	    }

    bool AlgorithmOvYolo::objectDetect(cv::Mat& image, std::vector<DetectObject>& detects,
        float scoreThreshold, float nmsThreshold){
        if (!createState() || !core || mRequests.empty()) {
            LOGE("openvino engine not ready");
            return false;
        }

	        size_t idx = mRR.fetch_add(1) % mRequests.size();
	        std::scoped_lock lock(mReqMtx[idx]);
	        auto& infer_request = mRequests[idx];

        // Preprocess the image
        const int inW = (mInputWidth > 0) ? mInputWidth : 640;
        const int inH = (mInputHeight > 0) ? mInputHeight : 640;

        ImagePreprocessBlob preprocessed;
        float x_factor = 1.0f;
        float y_factor = 1.0f;
        std::string preprocessErr;
        const ImagePreprocessMode preprocessMode = mIsClassifier
            ? ImagePreprocessMode::Stretch
            : ImagePreprocessMode::Letterbox;
        if (!preprocessImageToNchw(image, inW, inH, preprocessMode, preprocessed, preprocessErr)) {
            LOGE("openvino yolo preprocess failed: %s", preprocessErr.c_str());
            return false;
        }
        if (!preprocessed.mappings.empty()) {
            x_factor = preprocessed.mappings[0].scaleX;
            y_factor = preprocessed.mappings[0].scaleY;
        }

        // -------- Step 5. Feed the blob into the input node of the Model -------
        // Get input port for model with one input
        auto input_port = compiled_model.input();

        // Create tensor from external memory
        ov::Shape shape;
        try {
            shape = input_port.get_shape();
        } catch (const ov::Exception&) {}
        if (shape.size() < 4 || static_cast<int>(shape[2]) != inH || static_cast<int>(shape[3]) != inW) {
            shape = { 1, 3, static_cast<size_t>(inH), static_cast<size_t>(inW) };
        }
        ov::Tensor input_tensor(input_port.get_element_type(), shape, preprocessed.data());
        // Set input tensor for model with one input
        infer_request.set_input_tensor(input_tensor);

        // -------- Step 6. Start inference --------
        infer_request.infer();

        // -------- Step 7. Get the inference result --------
        auto output = infer_request.get_output_tensor(mSelectedOutputIndex);
        auto output_shape = output.get_shape();
        ov::Tensor protoTensor;
        const float* protoData = nullptr;
        if (mHasSegmentation) {
            try {
                protoTensor = infer_request.get_output_tensor(mProtoOutputIndex);
                protoData = protoTensor.data<float>();
            } catch (const ov::Exception&) {
                protoData = nullptr;
            }
        }

        // Classifier output: [1, C] or [1, C, 1, 1]
        if (mIsClassifier) {
            const size_t n = output.get_size();
            if (n == 0) {
                LOGE("classifier output is empty");
                return false;
            }
            const float* data = output.data<float>();
            int bestIdx = -1;
            float bestVal = -1e30f;
            for (size_t i = 0; i < n; ++i) {
                const float v = data[i];
                if (v > bestVal) {
                    bestVal = v;
                    bestIdx = static_cast<int>(i);
                }
            }

            // Softmax probability for top-1 (best-effort).
            double sum = 0.0;
            for (size_t i = 0; i < n; ++i) {
                sum += std::exp(static_cast<double>(data[i] - bestVal));
            }
            float prob = 0.0f;
            if (sum > 0.0) {
                prob = static_cast<float>(1.0 / sum);
            }

            DetectObject detect;
            detect.x1 = 0;
            detect.y1 = 0;
            detect.x2 = image.cols;
            detect.y2 = image.rows;
            detect.class_id = bestIdx;
            detect.class_score = prob;
            if (bestIdx >= 0 && bestIdx < static_cast<int>(mClassNames.size())) {
                detect.class_name = mClassNames[bestIdx];
            }
            else {
                detect.class_name = "class_" + std::to_string(bestIdx);
            }

            detects.clear();
            detects.push_back(detect);
            return true;
        }

        std::vector<int64_t> outShape;
        outShape.reserve(output_shape.size());
        for (size_t i = 0; i < output_shape.size(); ++i) {
            outShape.push_back(static_cast<int64_t>(output_shape[i]));
        }
        YoloOutputLayout layout;
        std::string layoutErr;
        if (!parseYoloOutputLayout(outShape, static_cast<int>(mClassNames.size()), layout, layoutErr)) {
            LOGE("unsupported output layout (dims=%zu): %s", output_shape.size(), layoutErr.c_str());
            return false;
        }

        int rows = layout.rows;
        int dimensions = layout.dim;
        bool rowsFirst = layout.rowsFirst;

        // -------- Step 8. Postprocess the result --------
        float* data = output.data<float>();
        cv::Mat output_buffer;
        if (rowsFirst) {
            output_buffer = cv::Mat(rows, dimensions, CV_32F, data);
        }
        else {
            cv::Mat raw(dimensions, rows, CV_32F, data);
            cv::transpose(raw, output_buffer); // rows x dim
        }

	        YoloDetectionFormat detectFormat;
	        {
	            std::scoped_lock formatLock(mDetectFormatMtx);
	            detectFormat = mDetectFormat;
	        }
	        detectFormat.outputDim = dimensions;

	        if (mHasSegmentation && !detectFormat.hasAngle && protoData != nullptr) {
	            std::string segErr;
	            YoloSegmentationDecodeOptions segOptions;
	            segOptions.classNames = &mClassNames;
	            segOptions.scoreThreshold = scoreThreshold;
	            segOptions.nmsThreshold = nmsThreshold;
	            segOptions.xFactor = x_factor;
	            segOptions.yFactor = y_factor;
	            segOptions.imageWidth = image.cols;
	            segOptions.imageHeight = image.rows;
	            YoloDetectionDecodeOutput segOutput;
	            segOutput.format = &detectFormat;
	            segOutput.detects = &detects;
	            segOutput.errMsg = &segErr;
	            if (!decodeYoloSegmentationDetections(output_buffer, protoData, mProtoLayout, segOptions, segOutput)) {
	                LOGE("openvino yolo seg postprocess failed: %s", segErr.c_str());
	                return false;
		            }
	            {
	                std::scoped_lock formatLock(mDetectFormatMtx);
	                mDetectFormat = detectFormat;
	            }
	            return true;
	        }

	        std::string postErr;
	        YoloDetectionDecodeOptions detectOptions;
	        detectOptions.classNames = &mClassNames;
	        detectOptions.scoreThreshold = scoreThreshold;
	        detectOptions.nmsThreshold = nmsThreshold;
	        detectOptions.xFactor = x_factor;
	        detectOptions.yFactor = y_factor;
	        YoloDetectionDecodeOutput detectOutput;
	        detectOutput.format = &detectFormat;
	        detectOutput.detects = &detects;
	        detectOutput.errMsg = &postErr;
	        if (!decodeYoloDetections(output_buffer, detectOptions, detectOutput)) {
	            LOGE("openvino yolo postprocess failed: %s", postErr.c_str());
	            return false;
		        }
	        {
	            std::scoped_lock formatLock(mDetectFormatMtx);
	            mDetectFormat = detectFormat;
	        }

        return true;
    }

}
