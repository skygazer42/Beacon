#include "YoloDetectionPostprocess.h"

#include <cmath>
#include <string>
#include <vector>

static bool nearly_equal(float a, float b, float eps = 1.5f) {
    return std::fabs(a - b) <= eps;
}

int main() {
    {
        AVSAnalyzer::YoloDetectionFormat format =
            AVSAnalyzer::inferYoloDetectionFormat(6, 1, "/models/yolo11n-obb.xml");

        if (!format.hasAngle) return 10;
        if (format.hasObjectness) return 11;
        if (format.classOffset != 5) return 12;

        cv::Mat rows(1, 6, CV_32F, cv::Scalar(0));
        rows.at<float>(0, 0) = 50.0f;   // cx
        rows.at<float>(0, 1) = 40.0f;   // cy
        rows.at<float>(0, 2) = 20.0f;   // w
        rows.at<float>(0, 3) = 10.0f;   // h
        rows.at<float>(0, 4) = 0.0f;    // angle
        rows.at<float>(0, 5) = 0.95f;   // class score

	        std::vector<AVSAnalyzer::DetectObject> detects;
	        std::string err;
	        std::vector<std::string> classNames{"person"};
	        AVSAnalyzer::YoloDetectionDecodeOptions options;
	        options.classNames = &classNames;
	        options.scoreThreshold = 0.25f;
	        options.nmsThreshold = 0.5f;
	        options.xFactor = 1.0f;
	        options.yFactor = 1.0f;
	        AVSAnalyzer::YoloDetectionDecodeOutput output;
	        output.format = &format;
	        output.detects = &detects;
	        output.errMsg = &err;
	        if (!AVSAnalyzer::decodeYoloDetections(rows, options, output)) {
	            return 13;
	        }
        if (!err.empty()) return 14;
        if (detects.size() != 1) return 15;
        const auto& d = detects[0];
        if (!d.hasObb) return 16;
        if (d.class_name != "person") return 17;
        if (!nearly_equal(static_cast<float>(d.x1), 40.0f)) return 18;
        if (!nearly_equal(static_cast<float>(d.y1), 35.0f)) return 19;
        if (!nearly_equal(static_cast<float>(d.x2), 60.0f)) return 20;
        if (!nearly_equal(static_cast<float>(d.y2), 45.0f)) return 21;
    }

    {
        AVSAnalyzer::YoloDetectionFormat format =
            AVSAnalyzer::inferYoloDetectionFormat(6, 1, "/models/plain-yolo.xml");
        if (!format.index4ObjOrAngleAmbiguous) return 30;
        if (format.hasAngle) return 31;

        cv::Mat rows(1, 6, CV_32F, cv::Scalar(0));
        rows.at<float>(0, 4) = 1.57f;  // angle in radians, not objectness
        AVSAnalyzer::resolveAmbiguousYoloDetectionFormat(rows, format);

        if (!format.index4ObjOrAngleDecided) return 32;
        if (!format.hasAngle) return 33;
        if (format.hasObjectness) return 34;
        if (format.classOffset != 5) return 35;
    }

    return 0;
}
