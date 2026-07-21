#include "YoloDetectionPostprocess.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cctype>
#include <sstream>
#include <string_view>

namespace AVSAnalyzer {
namespace {

static std::string to_lower_copy(const std::string& value) {
    std::string out = value;
    std::transform(out.begin(), out.end(), out.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });
    return out;
}

static void set_error(std::string* errMsg, std::string_view msg) {
    if (errMsg) {
        errMsg->assign(msg.data(), msg.size());
    }
}

}  // namespace

YoloDetectionFormat inferYoloDetectionFormat(
    int outputDim,
    int classCount,
    const std::string& modelPathHint
) {
    YoloDetectionFormat format;
    format.outputDim = outputDim;

    if (outputDim >= 6) {
        const int classCountV8 = outputDim - 4;
        const int classCountV5 = outputDim - 5;
        if (classCount > 0) {
            if (classCountV5 == classCount && classCountV8 != classCount) {
                format.hasObjectness = true;
            }
        } else if (outputDim == 85) {
            format.hasObjectness = true;
        }
    }

    if (format.hasObjectness) {
        format.classOffset = 5;
    }

    if (classCount > 0) {
        const std::string lowerPath = to_lower_copy(modelPathHint);
        const bool hintedObb = (lowerPath.find("obb") != std::string::npos);
        if (hintedObb) {
            if (outputDim >= (6 + classCount)) {
                format.hasAngle = true;
                format.hasObjectness = true;
                format.classOffset = 6;
            } else if (outputDim >= (5 + classCount)) {
                format.hasAngle = true;
                format.hasObjectness = false;
                format.classOffset = 5;
            }
        } else if (outputDim == (5 + classCount)) {
            format.index4ObjOrAngleAmbiguous = true;
            format.index4ObjOrAngleDecided = false;
            format.index4UseObjectness = true;
            format.hasObjectness = false;
            format.hasAngle = false;
            format.classOffset = 5;
        }
    }

    return format;
}

void resolveAmbiguousYoloDetectionFormat(
    const cv::Mat& detOutput,
    YoloDetectionFormat& format
) {
    if (!format.index4ObjOrAngleAmbiguous || format.index4ObjOrAngleDecided) {
        return;
    }
    if (detOutput.empty() || detOutput.cols <= 4) {
        return;
    }

    bool looksLikeAngle = false;
    const int sampleN = std::min(detOutput.rows, 32);
    for (int i = 0; i < sampleN; ++i) {
        const float value = detOutput.at<float>(i, 4);
        if (!std::isfinite(value)) {
            continue;
        }
        if (value < 0.0f || value > 1.0f) {
            looksLikeAngle = true;
            break;
        }
    }

    format.index4UseObjectness = !looksLikeAngle;
    format.index4ObjOrAngleDecided = true;
    if (format.index4UseObjectness) {
        format.hasObjectness = true;
        format.hasAngle = false;
    } else {
        format.hasObjectness = false;
        format.hasAngle = true;
    }
    format.classOffset = 4 + (format.hasAngle ? 1 : 0) + (format.hasObjectness ? 1 : 0);
}

bool decodeYoloDetections(
    const cv::Mat& detOutput,
    const YoloDetectionDecodeOptions& options,
    YoloDetectionDecodeOutput& output
) {
    if (options.classNames == nullptr || output.format == nullptr || output.detects == nullptr) {
        set_error(output.errMsg, "invalid decode configuration");
        return false;
    }

    const auto& classNames = *options.classNames;
    auto& format = *output.format;
    auto& detects = *output.detects;
    std::string* errMsg = output.errMsg;
    const float xFactor = options.xFactor;
    const float yFactor = options.yFactor;

    detects.clear();
    set_error(errMsg, "");

    if (detOutput.empty()) {
        set_error(errMsg, "det_output is empty");
        return false;
    }
    if (detOutput.cols <= 0) {
        set_error(errMsg, "det_output has invalid cols");
        return false;
    }
    if (format.outputDim <= 0) {
        format.outputDim = detOutput.cols;
    }

    float score_threshold = options.scoreThreshold;
    float nms_threshold = options.nmsThreshold;
    if (!std::isfinite(score_threshold) || score_threshold < 0.0f || score_threshold > 1.0f) {
        score_threshold = 0.25f;
    }
    if (!std::isfinite(nms_threshold) || nms_threshold < 0.0f || nms_threshold > 1.0f) {
        nms_threshold = 0.5f;
    }

    resolveAmbiguousYoloDetectionFormat(detOutput, format);

    const int base = 4 + (format.hasAngle ? 1 : 0) + (format.hasObjectness ? 1 : 0);
    const int modelClasses = format.outputDim - base;
    if (modelClasses <= 0) {
        set_error(errMsg, "invalid output dim");
        return false;
    }

    int classBegin = base;
    int classRange = modelClasses;
    if (!classNames.empty()) {
        classRange = std::min(modelClasses, static_cast<int>(classNames.size()));
    }
    if (classRange <= 0) {
        set_error(errMsg, "class range is empty");
        return false;
    }
    const int classEnd = classBegin + classRange;

    std::vector<cv::Rect> boxes;
    std::vector<int> classIds;
    std::vector<float> confidences;
    std::vector<std::array<cv::Point2f, 4>> obbCorners;
    if (format.hasAngle) {
        obbCorners.reserve(static_cast<size_t>(detOutput.rows));
    }

    const float kPi = 3.14159265358979323846f;

    for (int i = 0; i < detOutput.rows; ++i) {
        cv::Mat classesScores = detOutput.row(i).colRange(classBegin, classEnd);
        cv::Point classIdPoint;
        double score = 0.0;
        cv::minMaxLoc(classesScores, nullptr, &score, nullptr, &classIdPoint);

        float objectness = 1.0f;
        if (format.hasObjectness) {
            const int objIndex = base - 1;
            objectness = detOutput.at<float>(i, objIndex);
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

        if (format.hasAngle) {
            float angle = detOutput.at<float>(i, 4);
            if (!std::isfinite(angle)) {
                angle = 0.0f;
            }

            float angleDeg = angle;
            if (std::fabs(angle) <= 3.2f) {
                angleDeg = angle * 180.0f / kPi;
            }

            const float cxp = cx * xFactor;
            const float cyp = cy * yFactor;
            const float wp = ow * xFactor;
            const float hp = oh * yFactor;

            cv::RotatedRect rr(cv::Point2f(cxp, cyp), cv::Size2f(wp, hp), angleDeg);
            cv::Point2f pts[4];
            rr.points(pts);

            std::array<cv::Point2f, 4> corners;
            for (int k = 0; k < 4; ++k) {
                corners[k] = pts[k];
            }

            boxes.push_back(rr.boundingRect());
            classIds.push_back(classIdPoint.x);
            confidences.push_back(static_cast<float>(score));
            obbCorners.push_back(corners);
        } else {
            const auto x = static_cast<int>((cx - 0.5f * ow) * xFactor);
            const auto y = static_cast<int>((cy - 0.5f * oh) * yFactor);
            const auto width = static_cast<int>(ow * xFactor);
            const auto height = static_cast<int>(oh * yFactor);
            boxes.push_back(cv::Rect(x, y, width, height));
            classIds.push_back(classIdPoint.x);
            confidences.push_back(static_cast<float>(score));
        }
    }

    std::vector<int> indexes;
    cv::dnn::NMSBoxes(boxes, confidences, score_threshold, nms_threshold, indexes);
    detects.reserve(indexes.size());

    for (size_t i = 0; i < indexes.size(); ++i) {
        const int index = indexes[i];
        if (index < 0 || index >= static_cast<int>(boxes.size())) {
            continue;
        }

        DetectObject detect;
        const cv::Rect box = boxes[static_cast<size_t>(index)];
        detect.x1 = box.x;
        detect.y1 = box.y;
        detect.x2 = box.x + box.width;
        detect.y2 = box.y + box.height;
        detect.class_id = classIds[static_cast<size_t>(index)];
        detect.class_score = confidences[static_cast<size_t>(index)];

        if (detect.class_id >= 0 && detect.class_id < static_cast<int>(classNames.size())) {
            detect.class_name = classNames[static_cast<size_t>(detect.class_id)];
        } else {
            std::ostringstream oss;
            oss << "class_" << detect.class_id;
            detect.class_name = oss.str();
        }

        if (format.hasAngle && index < static_cast<int>(obbCorners.size())) {
            detect.hasObb = true;
            detect.obb = obbCorners[static_cast<size_t>(index)];
        }

        detects.push_back(detect);
    }

    return true;
}

}  // namespace AVSAnalyzer
