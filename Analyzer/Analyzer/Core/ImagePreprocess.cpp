#include "ImagePreprocess.h"

#include <algorithm>
#include <array>
#include <cmath>

namespace AVSAnalyzer {
namespace {

int clampInt(int value, int lo, int hi) {
    if (value < lo) {
        return lo;
    }
    if (value > hi) {
        return hi;
    }
    return value;
}

bool prepareImage(
    const cv::Mat& image,
    int inputWidth,
    int inputHeight,
    ImagePreprocessMode mode,
    cv::Mat& prepared,
    ImageCoordinateMapping& mapping,
    std::string& errMsg
) {
    prepared.release();
    mapping = ImageCoordinateMapping{};
    errMsg.clear();

    if (image.empty() || image.cols <= 0 || image.rows <= 0) {
        errMsg = "image is empty";
        return false;
    }
    if (inputWidth <= 0 || inputHeight <= 0) {
        errMsg = "invalid input size";
        return false;
    }

    cv::Mat source;
    if (image.channels() == 3) {
        source = image;
    } else if (image.channels() == 1) {
        cv::cvtColor(image, source, cv::COLOR_GRAY2BGR);
    } else if (image.channels() == 4) {
        cv::cvtColor(image, source, cv::COLOR_BGRA2BGR);
    } else {
        errMsg = "unsupported image channels";
        return false;
    }

    mapping.enabled = true;
    mapping.sourceWidth = source.cols;
    mapping.sourceHeight = source.rows;
    mapping.inputWidth = inputWidth;
    mapping.inputHeight = inputHeight;

    if (mode == ImagePreprocessMode::Letterbox) {
        const int squareSide = std::max(source.cols, source.rows);
        if (squareSide <= 0) {
            errMsg = "invalid letterbox size";
            return false;
        }

        cv::Mat squareCanvas = cv::Mat::zeros(cv::Size(squareSide, squareSide), CV_8UC3);
        source.copyTo(squareCanvas(cv::Rect(0, 0, source.cols, source.rows)));
        cv::resize(squareCanvas, prepared, cv::Size(inputWidth, inputHeight), 0, 0, cv::INTER_LINEAR);

        mapping.scaleX = static_cast<float>(squareSide) / static_cast<float>(inputWidth);
        mapping.scaleY = static_cast<float>(squareSide) / static_cast<float>(inputHeight);
        mapping.offsetX = 0.0f;
        mapping.offsetY = 0.0f;
        return true;
    }

    cv::resize(source, prepared, cv::Size(inputWidth, inputHeight), 0, 0, cv::INTER_LINEAR);
    mapping.scaleX = static_cast<float>(source.cols) / static_cast<float>(inputWidth);
    mapping.scaleY = static_cast<float>(source.rows) / static_cast<float>(inputHeight);
    mapping.offsetX = 0.0f;
    mapping.offsetY = 0.0f;
    return true;
}

void writePreparedToNchw(
    const cv::Mat& prepared,
    size_t batchIndex,
    ImagePreprocessBlob& out
) {
    cv::Mat rgb;
    cv::cvtColor(prepared, rgb, cv::COLOR_BGR2RGB);

    cv::Mat rgbFloat;
    rgb.convertTo(rgbFloat, CV_32FC3, 1.0 / 255.0);

    const size_t plane = static_cast<size_t>(out.inputWidth) * static_cast<size_t>(out.inputHeight);
    const size_t imageOffset = batchIndex * plane * 3U;
    std::vector<cv::Mat> channels;
    channels.reserve(3);
    channels.emplace_back(out.inputHeight, out.inputWidth, CV_32F, out.values.data() + imageOffset + plane * 0U);
    channels.emplace_back(out.inputHeight, out.inputWidth, CV_32F, out.values.data() + imageOffset + plane * 1U);
    channels.emplace_back(out.inputHeight, out.inputWidth, CV_32F, out.values.data() + imageOffset + plane * 2U);
    cv::split(rgbFloat, channels);
}

}  // namespace

int ImageCoordinateMapping::mapX(int value) const {
    if (!enabled || sourceWidth <= 0) {
        return value;
    }
    return clampInt(static_cast<int>(std::lround(projectX(static_cast<float>(value)))), 0, sourceWidth - 1);
}

int ImageCoordinateMapping::mapY(int value) const {
    if (!enabled || sourceHeight <= 0) {
        return value;
    }
    return clampInt(static_cast<int>(std::lround(projectY(static_cast<float>(value)))), 0, sourceHeight - 1);
}

float ImageCoordinateMapping::projectX(float value) const {
    if (!enabled) {
        return value;
    }
    return (value - offsetX) * scaleX;
}

float ImageCoordinateMapping::projectY(float value) const {
    if (!enabled) {
        return value;
    }
    return (value - offsetY) * scaleY;
}

bool ImagePreprocessBlob::empty() const {
    return values.empty();
}

size_t ImagePreprocessBlob::elementCount() const {
    return values.size();
}

const float* ImagePreprocessBlob::data() const {
    return values.empty() ? nullptr : values.data();
}

float* ImagePreprocessBlob::data() {
    return values.empty() ? nullptr : values.data();
}

bool preprocessImageToNchw(
    const cv::Mat& image,
    int inputWidth,
    int inputHeight,
    ImagePreprocessMode mode,
    ImagePreprocessBlob& out,
    std::string& errMsg
) {
    return preprocessImagesToNchw(std::vector<cv::Mat>{image}, inputWidth, inputHeight, mode, out, errMsg);
}

bool preprocessImagesToNchw(
    const std::vector<cv::Mat>& images,
    int inputWidth,
    int inputHeight,
    ImagePreprocessMode mode,
    ImagePreprocessBlob& out,
    std::string& errMsg
) {
    out = ImagePreprocessBlob{};
    errMsg.clear();

    if (images.empty()) {
        errMsg = "images are empty";
        return false;
    }
    if (inputWidth <= 0 || inputHeight <= 0) {
        errMsg = "invalid input size";
        return false;
    }

    out.batch = static_cast<int>(images.size());
    out.inputWidth = inputWidth;
    out.inputHeight = inputHeight;
    out.values.assign(static_cast<size_t>(out.batch) * 3U * static_cast<size_t>(inputWidth) * static_cast<size_t>(inputHeight), 0.0f);
    out.mappings.resize(static_cast<size_t>(out.batch));

    for (size_t i = 0; i < images.size(); ++i) {
        cv::Mat prepared;
        ImageCoordinateMapping mapping;
        if (!prepareImage(images[i], inputWidth, inputHeight, mode, prepared, mapping, errMsg)) {
            out = ImagePreprocessBlob{};
            return false;
        }
        writePreparedToNchw(prepared, i, out);
        out.mappings[i] = mapping;
    }

    return true;
}

}  // namespace AVSAnalyzer
