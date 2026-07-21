#ifndef ANALYZER_IMAGE_PREPROCESS_H
#define ANALYZER_IMAGE_PREPROCESS_H

#include <string>
#include <vector>

#include <opencv2/opencv.hpp>

namespace AVSAnalyzer {

enum class ImagePreprocessMode {
    Letterbox = 1,
    Stretch = 2,
    Resize = Stretch,  // Alias: direct resize to model input.
};

struct ImageCoordinateMapping {
    bool enabled = false;
    int sourceWidth = 0;
    int sourceHeight = 0;
    int inputWidth = 0;
    int inputHeight = 0;
    float scaleX = 1.0f;
    float scaleY = 1.0f;
    float offsetX = 0.0f;
    float offsetY = 0.0f;

    float projectX(float value) const;
    float projectY(float value) const;
    int mapX(int value) const;
    int mapY(int value) const;
};

struct ImagePreprocessBlob {
    int batch = 0;
    int inputWidth = 0;
    int inputHeight = 0;
    std::vector<float> values;
    std::vector<ImageCoordinateMapping> mappings;

    bool empty() const;
    size_t elementCount() const;
    const float* data() const;
    float* data();
};

bool preprocessImageToNchw(
    const cv::Mat& image,
    int inputWidth,
    int inputHeight,
    ImagePreprocessMode mode,
    ImagePreprocessBlob& out,
    std::string& errMsg
);

bool preprocessImagesToNchw(
    const std::vector<cv::Mat>& images,
    int inputWidth,
    int inputHeight,
    ImagePreprocessMode mode,
    ImagePreprocessBlob& out,
    std::string& errMsg
);

}  // namespace AVSAnalyzer

#endif  // ANALYZER_IMAGE_PREPROCESS_H
