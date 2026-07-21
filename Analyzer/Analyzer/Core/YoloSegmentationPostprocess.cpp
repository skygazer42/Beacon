#include "YoloSegmentationPostprocess.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <sstream>
#include <string_view>
#include <vector>

namespace AVSAnalyzer {
namespace {

struct SegCandidate {
    cv::Rect box;
    int classId = -1;
    float score = 0.0f;
    std::vector<float> coeffs;
};

void set_error(std::string* errMsg, std::string_view msg) {
    if (errMsg) {
        errMsg->assign(msg.data(), msg.size());
    }
}

float sigmoid(float v) {
    if (v >= 0.0f) {
        const float z = std::exp(-v);
        return 1.0f / (1.0f + z);
    }
    const float z = std::exp(v);
    return z / (1.0f + z);
}

float proto_at(const float* protoData, const YoloSegmentationPrototypeLayout& layout, int c, int y, int x) {
    if (layout.channelsFirst) {
        const size_t idx =
            static_cast<size_t>(c) * static_cast<size_t>(layout.height) * static_cast<size_t>(layout.width) +
            static_cast<size_t>(y) * static_cast<size_t>(layout.width) +
            static_cast<size_t>(x);
        return protoData[idx];
    }

    const size_t idx =
        static_cast<size_t>(y) * static_cast<size_t>(layout.width) * static_cast<size_t>(layout.channels) +
        static_cast<size_t>(x) * static_cast<size_t>(layout.channels) +
        static_cast<size_t>(c);
    return protoData[idx];
}

cv::Rect clamp_rect_to_image(const cv::Rect& box, int imageWidth, int imageHeight) {
    const int x1 = std::max(0, std::min(imageWidth, box.x));
    const int y1 = std::max(0, std::min(imageHeight, box.y));
    const int x2 = std::max(0, std::min(imageWidth, box.x + box.width));
    const int y2 = std::max(0, std::min(imageHeight, box.y + box.height));
    if (x2 <= x1 || y2 <= y1) {
        return cv::Rect();
    }
    return cv::Rect(x1, y1, x2 - x1, y2 - y1);
}

void attach_segmentation_polygon(
    const SegCandidate& cand,
    const float* protoData,
    const YoloSegmentationPrototypeLayout& protoLayout,
    int imageWidth,
    int imageHeight,
    DetectObject& detect
) {
    if (!protoData || protoLayout.channels <= 0 || protoLayout.height <= 0 || protoLayout.width <= 0) {
        return;
    }
    if (static_cast<int>(cand.coeffs.size()) != protoLayout.channels) {
        return;
    }
    if (imageWidth <= 0 || imageHeight <= 0) {
        return;
    }

    cv::Mat logits(protoLayout.height, protoLayout.width, CV_32F, cv::Scalar(0));
    for (int y = 0; y < protoLayout.height; ++y) {
        float* row = logits.ptr<float>(y);
        for (int x = 0; x < protoLayout.width; ++x) {
            float sum = 0.0f;
            for (int c = 0; c < protoLayout.channels; ++c) {
                sum += cand.coeffs[static_cast<size_t>(c)] * proto_at(protoData, protoLayout, c, y, x);
            }
            row[x] = sigmoid(sum);
        }
    }

    const int canvasSize = std::max(imageWidth, imageHeight);
    if (canvasSize <= 0) {
        return;
    }

    cv::Mat resized;
    cv::resize(logits, resized, cv::Size(canvasSize, canvasSize), 0, 0, cv::INTER_LINEAR);

    cv::Mat binaryCanvas;
    cv::threshold(resized, binaryCanvas, 0.5, 255.0, cv::THRESH_BINARY);
	    binaryCanvas.convertTo(binaryCanvas, CV_8UC1);

	    cv::Mat binary = binaryCanvas(cv::Rect(0, 0, imageWidth, imageHeight)).clone();
	    if (const cv::Rect bbox = clamp_rect_to_image(cand.box, imageWidth, imageHeight); bbox.area() > 0) {
	        cv::Mat bboxMask = cv::Mat::zeros(binary.size(), CV_8UC1);
	        binary(bbox).copyTo(bboxMask(bbox));
	        binary = bboxMask;
	    }

    std::vector<std::vector<cv::Point>> contours;
    cv::findContours(binary, contours, cv::RETR_EXTERNAL, cv::CHAIN_APPROX_SIMPLE);
    if (contours.empty()) {
        return;
    }

    size_t bestIdx = 0;
    double bestArea = 0.0;
    for (size_t i = 0; i < contours.size(); ++i) {
        const double area = std::fabs(cv::contourArea(contours[i]));
        if (area > bestArea) {
            bestArea = area;
            bestIdx = i;
        }
    }
    if (bestArea <= 0.0) {
        return;
    }

    std::vector<cv::Point> approx;
    cv::approxPolyDP(contours[bestIdx], approx, 1.0, true);
    const std::vector<cv::Point>& chosen = (approx.size() >= 3) ? approx : contours[bestIdx];
    if (chosen.size() < 3) {
        return;
    }

    detect.hasSegmentation = true;
    detect.segmentation.clear();
    detect.segmentation.reserve(chosen.size());
    for (const auto& p : chosen) {
        detect.segmentation.emplace_back(static_cast<float>(p.x), static_cast<float>(p.y));
    }
}

}  // namespace

bool parseYoloSegmentationPrototypeLayout(
    const std::vector<int64_t>& shape,
    int coeffDim,
    YoloSegmentationPrototypeLayout& out,
    std::string& errMsg
) {
    out = YoloSegmentationPrototypeLayout{};
    errMsg.clear();

    if (coeffDim <= 0) {
        errMsg = "invalid coeff dim";
        return false;
    }
    if (shape.size() < 3 || shape.size() > 4) {
        errMsg = "prototype output must be 3D or 4D";
        return false;
    }

    std::vector<int64_t> dims;
    dims.reserve(shape.size());
    for (size_t i = 0; i < shape.size(); ++i) {
        if (shape.size() == 4 && i == 0 && shape[i] == 1) {
            continue;
        }
        dims.push_back(shape[i]);
    }
    if (dims.size() != 3) {
        errMsg = "prototype output must resolve to 3 dims";
        return false;
    }
    if (dims[0] <= 0 || dims[1] <= 0 || dims[2] <= 0) {
        errMsg = "prototype output has invalid dims";
        return false;
    }

    if (dims[0] == coeffDim && dims[1] > 1 && dims[2] > 1) {
        out.channels = static_cast<int>(dims[0]);
        out.height = static_cast<int>(dims[1]);
        out.width = static_cast<int>(dims[2]);
        out.channelsFirst = true;
        return true;
    }

    if (dims[2] == coeffDim && dims[0] > 1 && dims[1] > 1) {
        out.channels = static_cast<int>(dims[2]);
        out.height = static_cast<int>(dims[0]);
        out.width = static_cast<int>(dims[1]);
        out.channelsFirst = false;
        return true;
    }

    std::ostringstream oss;
    oss << "prototype output does not match coeff dim=" << coeffDim;
    errMsg = oss.str();
    return false;
}

bool selectYoloSegmentationPrototypeOutput(
    const std::vector<std::vector<int64_t>>& outputShapes,
    size_t detectionIndex,
    int coeffDim,
    size_t& selectedIndex,
    YoloSegmentationPrototypeLayout& selectedLayout,
    std::string& errMsg
) {
    errMsg.clear();
    bool hasBest = false;
    int bestScore = std::numeric_limits<int>::min();

	    for (size_t i = 0; i < outputShapes.size(); ++i) {
	        if (i == detectionIndex) {
	            continue;
	        }

	        YoloSegmentationPrototypeLayout layout;
	        if (std::string perr; !parseYoloSegmentationPrototypeLayout(outputShapes[i], coeffDim, layout, perr)) {
	            continue;
	        }

        const int area = layout.height * layout.width;
        const int score = area;
        if (!hasBest || score > bestScore) {
            hasBest = true;
            bestScore = score;
            selectedIndex = i;
            selectedLayout = layout;
        }
    }

    if (!hasBest) {
        errMsg = "no segmentation prototype output";
        return false;
    }

    return true;
}

bool decodeYoloSegmentationDetections(
    const cv::Mat& detOutput,
    const float* protoData,
    const YoloSegmentationPrototypeLayout& protoLayout,
    const YoloSegmentationDecodeOptions& options,
    YoloDetectionDecodeOutput& output
) {
    if (options.classNames == nullptr || output.format == nullptr || output.detects == nullptr) {
        set_error(output.errMsg, "invalid segmentation decode configuration");
        return false;
    }

    const auto& classNames = *options.classNames;
    auto& format = *output.format;
    auto& detects = *output.detects;
    std::string* errMsg = output.errMsg;
    const float xFactor = options.xFactor;
    const float yFactor = options.yFactor;
    const int imageWidth = options.imageWidth;
    const int imageHeight = options.imageHeight;

    detects.clear();
    set_error(errMsg, "");

    if (detOutput.empty()) {
        set_error(errMsg, "det_output is empty");
        return false;
    }
    if (!protoData) {
        set_error(errMsg, "proto output is null");
        return false;
    }
    if (protoLayout.channels <= 0 || protoLayout.height <= 0 || protoLayout.width <= 0) {
        set_error(errMsg, "invalid proto layout");
        return false;
    }
    if (classNames.empty()) {
        set_error(errMsg, "segmentation requires class names");
        return false;
    }

    if (format.outputDim <= 0) {
        format.outputDim = detOutput.cols;
    }
    resolveAmbiguousYoloDetectionFormat(detOutput, format);

    const int base = 4 + (format.hasAngle ? 1 : 0) + (format.hasObjectness ? 1 : 0);
    const auto classCount = static_cast<int>(classNames.size());
    const int coeffBegin = base + classCount;
    if (coeffBegin >= detOutput.cols) {
        set_error(errMsg, "mask coeffs missing");
        return false;
    }
    const int coeffDim = detOutput.cols - coeffBegin;
    if (coeffDim != protoLayout.channels) {
        std::ostringstream oss;
        oss << "mask coeff dim mismatch det=" << coeffDim << " proto=" << protoLayout.channels;
        set_error(errMsg, oss.str());
        return false;
    }

    float score_threshold = options.scoreThreshold;
    float nms_threshold = options.nmsThreshold;
    if (!std::isfinite(score_threshold) || score_threshold < 0.0f || score_threshold > 1.0f) {
        score_threshold = 0.25f;
    }
    if (!std::isfinite(nms_threshold) || nms_threshold < 0.0f || nms_threshold > 1.0f) {
        nms_threshold = 0.5f;
    }

    std::vector<cv::Rect> boxes;
    std::vector<float> confidences;
    std::vector<SegCandidate> candidates;

    for (int i = 0; i < detOutput.rows; ++i) {
        cv::Mat classesScores = detOutput.row(i).colRange(base, base + classCount);
        cv::Point classIdPoint;
        double score = 0.0;
        cv::minMaxLoc(classesScores, nullptr, &score, nullptr, &classIdPoint);

        if (format.hasObjectness) {
            float objectness = detOutput.at<float>(i, base - 1);
            if (!std::isfinite(objectness)) {
                objectness = 0.0f;
            }
            score = score * objectness;
        }
        if (score <= score_threshold) {
            continue;
        }

        const float cx = detOutput.at<float>(i, 0);
        const float cy = detOutput.at<float>(i, 1);
        const float ow = detOutput.at<float>(i, 2);
        const float oh = detOutput.at<float>(i, 3);

        const auto x = static_cast<int>((cx - 0.5f * ow) * xFactor);
        const auto y = static_cast<int>((cy - 0.5f * oh) * yFactor);
        const auto width = static_cast<int>(ow * xFactor);
        const auto height = static_cast<int>(oh * yFactor);
        cv::Rect box(x, y, width, height);

        SegCandidate cand;
        cand.box = box;
        cand.classId = classIdPoint.x;
        cand.score = static_cast<float>(score);
        cand.coeffs.reserve(static_cast<size_t>(coeffDim));
        for (int c = 0; c < coeffDim; ++c) {
            cand.coeffs.push_back(detOutput.at<float>(i, coeffBegin + c));
        }

        boxes.push_back(box);
        confidences.push_back(cand.score);
        candidates.push_back(std::move(cand));
    }

    std::vector<int> indexes;
    cv::dnn::NMSBoxes(boxes, confidences, score_threshold, nms_threshold, indexes);
    detects.reserve(indexes.size());

    for (int index : indexes) {
        if (index < 0 || index >= static_cast<int>(candidates.size())) {
            continue;
        }
        const SegCandidate& cand = candidates[static_cast<size_t>(index)];

        DetectObject detect;
        detect.x1 = cand.box.x;
        detect.y1 = cand.box.y;
        detect.x2 = cand.box.x + cand.box.width;
        detect.y2 = cand.box.y + cand.box.height;
        detect.class_id = cand.classId;
        detect.class_score = cand.score;
        if (cand.classId >= 0 && cand.classId < static_cast<int>(classNames.size())) {
            detect.class_name = classNames[static_cast<size_t>(cand.classId)];
        } else {
            detect.class_name = "unknown";
        }

        attach_segmentation_polygon(cand, protoData, protoLayout, imageWidth, imageHeight, detect);
        detects.push_back(std::move(detect));
    }

    return true;
}

}  // namespace AVSAnalyzer
