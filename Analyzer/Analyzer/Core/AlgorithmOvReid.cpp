#include "AlgorithmOvReid.h"

#include "Config.h"
#include "ImagePreprocess.h"
#include "ReidFeature.h"
#include "Utils/Log.h"

#include <algorithm>
#include <exception>
#include <new>

namespace AVSAnalyzer {

    namespace {

        void applyCompiledInputShape(const ov::CompiledModel& model, int64_t& inputBatchDim, int& inputWidth, int& inputHeight) {
            try {
                auto inShape = model.input().get_shape();
                if (!inShape.empty()) {
                    inputBatchDim = static_cast<int64_t>(inShape[0]);
                }
                if (inShape.size() >= 4) {
                    const auto h = static_cast<int>(inShape[2]);
                    const auto w = static_cast<int>(inShape[3]);
                    if (w > 0) inputWidth = w;
                    if (h > 0) inputHeight = h;
                }
            } catch (const ov::Exception&) {}
        }

        void applyCompiledOutputShape(const ov::CompiledModel& model, int& embeddingDim) {
            try {
                auto outShape = model.output().get_shape();
                if (outShape.size() >= 2) {
                    const auto d = static_cast<int>(outShape[1]);
                    if (d > 0) {
                        embeddingDim = d;
                    }
                }
            } catch (const ov::Exception&) {}
        }

    }  // namespace

    AlgorithmOvReid::AlgorithmOvReid(
        const Config* config,
        const std::string& modelPath,
        const std::string& device,
        int concurrency,
        int requestedInputWidth,
        int requestedInputHeight
    ) : Algorithm(config), mDevice(device.empty() ? "CPU" : device) {
        if (concurrency < 1) {
            concurrency = 1;
        }
        if (requestedInputWidth > 0) mInputWidth = requestedInputWidth;
        if (requestedInputHeight > 0) mInputHeight = requestedInputHeight;

        LOGI("ReID(openvino) modelPath=%s device=%s concurrency=%d requestedInput=%dx%d",
             modelPath.c_str(), mDevice.c_str(), concurrency, requestedInputWidth, requestedInputHeight);

        try {
            core = std::make_unique<ov::Core>();
            compiled_model = core->compile_model(modelPath, mDevice);
            applyCompiledInputShape(compiled_model, mInputBatchDim, mInputWidth, mInputHeight);
            applyCompiledOutputShape(compiled_model, mEmbeddingDim);

            if (mInputWidth <= 0) mInputWidth = 640;
            if (mInputHeight <= 0) mInputHeight = 640;

            mRequests.reserve(static_cast<size_t>(concurrency));
            mReqMtx.resize(static_cast<size_t>(concurrency));
            for (int i = 0; i < concurrency; ++i) {
                mRequests.emplace_back(compiled_model.create_infer_request());
            }

            setCreateState(!mRequests.empty());
        }
        catch (const ov::Exception& ex) {
            LOGE("ReID(openvino) init error: %s", ex.what());
            core.reset();
            setCreateState(false);
        }
        catch (const std::bad_alloc& ex) {
            LOGE("ReID(openvino) init error: %s", ex.what());
            core.reset();
            setCreateState(false);
        }
    }

    AlgorithmOvReid::~AlgorithmOvReid() {
        core.reset();
    }

    bool AlgorithmOvReid::objectDetect(cv::Mat& image, std::vector<DetectObject>& detects, float scoreThreshold, float nmsThreshold) {
        (void)image;
        (void)detects;
        (void)scoreThreshold;
        (void)nmsThreshold;
        LOGE("AlgorithmOvReid::objectDetect called (unsupported)");
        return false;
    }

    bool AlgorithmOvReid::extractEmbeddings(
        const std::vector<cv::Mat>& images,
        std::vector<std::vector<float>>& embeddings,
        std::string& errMsg
    ) {
        embeddings.clear();
        if (!createState() || !core || mRequests.empty()) {
            errMsg = "openvino engine not ready";
            return false;
        }
        if (images.empty()) {
            errMsg.clear();
            return true;
        }

        // Static batch=1 models: run per-image inference for compatibility.
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

        if (mInputWidth <= 0 || mInputHeight <= 0) {
            errMsg = "invalid input shape";
            return false;
        }

	        size_t idx = mRR.fetch_add(1) % mRequests.size();
	        std::scoped_lock lock(mReqMtx[idx]);
	        auto& infer_request = mRequests[idx];

        ImagePreprocessBlob blob;
        if (!preprocessImagesToNchw(images, mInputWidth, mInputHeight, ImagePreprocessMode::Stretch, blob, errMsg)) {
            if (errMsg.empty()) {
                errMsg = "preprocessImagesToNchw failed";
            }
            return false;
        }

        const auto batch = static_cast<int64_t>(blob.batch);
        ov::Shape shape = { static_cast<size_t>(batch), 3, static_cast<size_t>(mInputHeight), static_cast<size_t>(mInputWidth) };

        auto input_port = compiled_model.input();
        ov::Tensor input_tensor(input_port.get_element_type(), shape, blob.data());
        infer_request.set_input_tensor(input_tensor);
        infer_request.infer();

        ov::Tensor output = infer_request.get_output_tensor(0);
        auto outShape = output.get_shape();
        size_t outCount = output.get_size();
        if (outCount == 0) {
            errMsg = "empty output";
            return false;
        }

        int outBatch = 0;
        int dim = 0;
        if (outShape.size() >= 2) {
            outBatch = static_cast<int>(outShape[0]);
            dim = static_cast<int>(outShape[1]);
        }
        if (outBatch <= 0) outBatch = static_cast<int>(batch);
        if (dim <= 0 && outBatch > 0) {
            dim = static_cast<int>(outCount / static_cast<size_t>(outBatch));
        }
        if (dim <= 0) {
            errMsg = "invalid embedding dim";
            return false;
        }

        const float* data = output.data<float>();
        embeddings.reserve(static_cast<size_t>(batch));
        for (int i = 0; i < static_cast<int>(batch); ++i) {
            std::vector<float> feat(static_cast<size_t>(dim));
            const size_t offset = static_cast<size_t>(i) * static_cast<size_t>(dim);
            for (int j = 0; j < dim; ++j) {
                const size_t k = offset + static_cast<size_t>(j);
                feat[static_cast<size_t>(j)] = (k < outCount) ? data[k] : 0.0f;
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

} // namespace AVSAnalyzer
