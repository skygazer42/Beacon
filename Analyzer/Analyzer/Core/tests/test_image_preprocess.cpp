#include "ImagePreprocess.h"

#include <cassert>
#include <cmath>
#include <string>
#include <vector>

#include <opencv2/dnn.hpp>
#include <opencv2/opencv.hpp>

using namespace AVSAnalyzer;

namespace {

void assert_close(float actual, float expected) {
    assert(std::fabs(actual - expected) < 1e-5f);
}

void assert_blob_matches_expected(const ImagePreprocessBlob& actual, const cv::Mat& expected) {
    assert(expected.total() == actual.values.size());
    const float* expected_data = expected.ptr<float>();
    for (size_t i = 0; i < actual.values.size(); ++i) {
        assert_close(actual.values[i], expected_data[i]);
    }
}

float blob_value(const ImagePreprocessBlob& blob, int channel, int x, int y) {
    const size_t plane = static_cast<size_t>(blob.inputWidth) * static_cast<size_t>(blob.inputHeight);
    const size_t index =
        static_cast<size_t>(channel) * plane +
        static_cast<size_t>(y) * static_cast<size_t>(blob.inputWidth) +
        static_cast<size_t>(x);
    return blob.values.at(index);
}

cv::Mat build_legacy_letterbox_canvas(const cv::Mat& image) {
    const int square_side = std::max(image.cols, image.rows);
    cv::Mat square = cv::Mat::zeros(square_side, square_side, CV_8UC3);
    image.copyTo(square(cv::Rect(0, 0, image.cols, image.rows)));
    return square;
}

void test_stretch_matches_blob_from_image() {
    cv::Mat img(2, 3, CV_8UC3);
    img.at<cv::Vec3b>(0, 0) = cv::Vec3b(10, 20, 30);
    img.at<cv::Vec3b>(0, 1) = cv::Vec3b(20, 30, 40);
    img.at<cv::Vec3b>(0, 2) = cv::Vec3b(30, 40, 50);
    img.at<cv::Vec3b>(1, 0) = cv::Vec3b(40, 50, 60);
    img.at<cv::Vec3b>(1, 1) = cv::Vec3b(50, 60, 70);
    img.at<cv::Vec3b>(1, 2) = cv::Vec3b(60, 70, 80);

    ImagePreprocessBlob blob;
    std::string err;
    const bool ok = preprocessImageToNchw(img, 4, 5, ImagePreprocessMode::Stretch, blob, err);
    assert(ok);
    assert(err.empty());
    assert(blob.batch == 1);
    assert(blob.inputWidth == 4);
    assert(blob.inputHeight == 5);
    assert(blob.values.size() == 3U * 4U * 5U);
    assert(blob.mappings.size() == 1);
    assert_close(blob.mappings[0].scaleX, 3.0f / 4.0f);
    assert_close(blob.mappings[0].scaleY, 2.0f / 5.0f);

    cv::Mat expected = cv::dnn::blobFromImage(
        img,
        1.0 / 255.0,
        cv::Size(4, 5),
        cv::Scalar(),
        true,
        false
    );
    assert_blob_matches_expected(blob, expected);
}

void test_letterbox_matches_legacy_square_pad_for_non_square_input() {
    cv::Mat img(50, 100, CV_8UC3, cv::Scalar(11, 77, 203));

    ImagePreprocessBlob blob;
    std::string err;
    const bool ok = preprocessImageToNchw(img, 100, 100, ImagePreprocessMode::Letterbox, blob, err);
    assert(ok);
    assert(err.empty());
    assert(blob.values.size() == 100U * 100U * 3U);
    assert(blob.mappings.size() == 1);

    const auto& mapping = blob.mappings[0];
    assert(mapping.enabled);
    assert(mapping.sourceWidth == 100);
    assert(mapping.sourceHeight == 50);
    assert_close(mapping.scaleX, 1.0f);
    assert_close(mapping.scaleY, 1.0f);
    assert_close(mapping.offsetX, 0.0f);
    assert_close(mapping.offsetY, 0.0f);
    assert(mapping.mapX(100) == 99);
    assert(mapping.mapY(100) == 49);
    assert_close(blob_value(blob, 0, 0, 0), 203.0f / 255.0f);
    assert_close(blob_value(blob, 1, 0, 0), 77.0f / 255.0f);
    assert_close(blob_value(blob, 2, 0, 0), 11.0f / 255.0f);
    assert_close(blob_value(blob, 0, 0, 99), 0.0f);
    assert_close(blob_value(blob, 1, 0, 99), 0.0f);
    assert_close(blob_value(blob, 2, 0, 99), 0.0f);

    cv::Mat expected = cv::dnn::blobFromImage(
        build_legacy_letterbox_canvas(img),
        1.0 / 255.0,
        cv::Size(100, 100),
        cv::Scalar(),
        true,
        false
    );
    assert_blob_matches_expected(blob, expected);
}

void test_batch_stretch_matches_blob_from_images() {
    cv::Mat img1(4, 8, CV_8UC3, cv::Scalar(1, 2, 3));
    cv::Mat img2(4, 8, CV_8UC3, cv::Scalar(4, 5, 6));

    ImagePreprocessBlob blob;
    std::string err;
    const bool ok = preprocessImagesToNchw({img1, img2}, 2, 2, ImagePreprocessMode::Stretch, blob, err);
    assert(ok);
    assert(err.empty());
    assert(blob.batch == 2);
    assert(blob.inputWidth == 2);
    assert(blob.inputHeight == 2);
    assert(blob.values.size() == 2U * 3U * 2U * 2U);
    assert(blob.mappings.size() == 2);
    assert(blob.mappings[0].mapX(1) == 4);
    assert(blob.mappings[0].mapY(1) == 2);
    assert(blob.mappings[1].mapX(2) == 7);
    assert(blob.mappings[1].mapY(2) == 3);

    cv::Mat expected = cv::dnn::blobFromImages(
        std::vector<cv::Mat>{img1, img2},
        1.0 / 255.0,
        cv::Size(2, 2),
        cv::Scalar(),
        true,
        false
    );
    assert_blob_matches_expected(blob, expected);
}

void test_invalid_input_rejected() {
    cv::Mat empty;

    ImagePreprocessBlob blob;
    std::string err;
    const bool ok = preprocessImageToNchw(empty, 16, 16, ImagePreprocessMode::Letterbox, blob, err);
    assert(!ok);
    assert(!err.empty());
}

}  // namespace

int main() {
    test_stretch_matches_blob_from_image();
    test_letterbox_matches_legacy_square_pad_for_non_square_input();
    test_batch_stretch_matches_blob_from_images();
    test_invalid_input_rejected();
    return 0;
}
