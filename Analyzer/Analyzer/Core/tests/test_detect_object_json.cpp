#include "DetectObjectJson.h"

#include <cassert>
#include <cmath>

namespace {

static bool nearly_equal(float a, float b, float eps = 1e-5f) {
    return std::fabs(a - b) <= eps;
}

static void test_serialize_without_pose() {
    AVSAnalyzer::DetectObject d{};
    d.x1 = 1;
    d.y1 = 2;
    d.x2 = 3;
    d.y2 = 4;
    d.class_id = 7;
    d.class_score = 0.9f;
    d.class_name = "person";

    Json::Value j = AVSAnalyzer::detectObjectToJson(d);
    assert(j.isObject());
    assert(j["x1"].asInt() == 1);
    assert(j["y1"].asInt() == 2);
    assert(j["x2"].asInt() == 3);
    assert(j["y2"].asInt() == 4);
    assert(j["class_id"].asInt() == 7);
    assert(nearly_equal(j["class_score"].asFloat(), 0.9f));
    assert(j["class_name"].asString() == "person");

    assert(!j.isMember("hasPose"));
    assert(!j.isMember("keypoints"));
}

static void test_serialize_with_pose_keypoints() {
    AVSAnalyzer::DetectObject d{};
    d.x1 = 10;
    d.y1 = 20;
    d.x2 = 30;
    d.y2 = 40;
    d.class_id = 0;
    d.class_score = 0.5f;
    d.class_name = "human";

    d.hasPose = true;
    d.keypoints.emplace_back(1.0f, 2.0f, 0.3f);
    d.keypoints.emplace_back(3.0f, 4.0f, 0.7f);

    Json::Value j = AVSAnalyzer::detectObjectToJson(d);
    assert(j.isObject());
    assert(j.isMember("hasPose"));
    assert(j["hasPose"].asBool() == true);
    assert(j.isMember("keypoints"));
    assert(j["keypoints"].isArray());
    assert(j["keypoints"].size() == 2);

    const Json::Value& kp0 = j["keypoints"][0];
    assert(kp0.isObject());
    assert(nearly_equal(kp0["x"].asFloat(), 1.0f));
    assert(nearly_equal(kp0["y"].asFloat(), 2.0f));
    assert(nearly_equal(kp0["confidence"].asFloat(), 0.3f));
}

static void test_parse_pose_keypoints_object_array() {
    Json::Value item;
    item["x1"] = 1;
    item["y1"] = 2;
    item["x2"] = 3;
    item["y2"] = 4;
    item["class_id"] = 5;
    item["class_score"] = 0.8;
    item["class_name"] = "person";

    Json::Value keypoints(Json::arrayValue);
    {
        Json::Value kp;
        kp["x"] = 11.0;
        kp["y"] = 22.0;
        kp["confidence"] = 0.9;
        keypoints.append(kp);
    }
    {
        Json::Value kp;
        kp["x"] = 33.0;
        kp["y"] = 44.0;
        kp["confidence"] = 0.1;
        keypoints.append(kp);
    }
    item["keypoints"] = keypoints;

    AVSAnalyzer::DetectObject d{};
    std::string err;
    const bool ok = AVSAnalyzer::parseDetectObjectFromJson(item, d, &err);
    assert(ok);
    assert(err.empty());
    assert(d.x1 == 1 && d.y1 == 2 && d.x2 == 3 && d.y2 == 4);
    assert(d.class_id == 5);
    assert(nearly_equal(d.class_score, 0.8f));
    assert(d.class_name == "person");
    assert(d.hasPose == true);
    assert(d.keypoints.size() == 2);
    assert(nearly_equal(d.keypoints[0].x, 11.0f));
    assert(nearly_equal(d.keypoints[0].y, 22.0f));
    assert(nearly_equal(d.keypoints[0].confidence, 0.9f));
}

static void test_parse_pose_keypoints_flat_array() {
    Json::Value item;
    item["x1"] = 0;
    item["y1"] = 0;
    item["x2"] = 10;
    item["y2"] = 10;
    item["class_id"] = 0;
    item["class_score"] = 0.99;
    item["class_name"] = "person";

    // Two keypoints, flat [x,y,conf,...]
    Json::Value keypoints(Json::arrayValue);
    keypoints.append(1.0);
    keypoints.append(2.0);
    keypoints.append(0.3);
    keypoints.append(3.0);
    keypoints.append(4.0);
    keypoints.append(0.7);
    item["keypoints"] = keypoints;

    AVSAnalyzer::DetectObject d{};
    std::string err;
    const bool ok = AVSAnalyzer::parseDetectObjectFromJson(item, d, &err);
    assert(ok);
    assert(err.empty());
    assert(d.hasPose == true);
    assert(d.keypoints.size() == 2);
    assert(nearly_equal(d.keypoints[1].x, 3.0f));
    assert(nearly_equal(d.keypoints[1].y, 4.0f));
    assert(nearly_equal(d.keypoints[1].confidence, 0.7f));
}

static void test_serialize_with_obb_flat_points() {
    AVSAnalyzer::DetectObject d{};
    d.x1 = 0;
    d.y1 = 0;
    d.x2 = 10;
    d.y2 = 20;
    d.class_id = 1;
    d.class_score = 0.88f;
    d.class_name = "car";

    d.hasObb = true;
    d.obb[0] = cv::Point2f(1.0f, 2.0f);
    d.obb[1] = cv::Point2f(3.0f, 4.0f);
    d.obb[2] = cv::Point2f(5.0f, 6.0f);
    d.obb[3] = cv::Point2f(7.0f, 8.0f);

    Json::Value j = AVSAnalyzer::detectObjectToJson(d);
    assert(j.isObject());
    assert(j.isMember("obb"));
    assert(j["obb"].isArray());
    assert(j["obb"].size() == 8);
    assert(nearly_equal(j["obb"][0].asFloat(), 1.0f));
    assert(nearly_equal(j["obb"][1].asFloat(), 2.0f));
    assert(nearly_equal(j["obb"][6].asFloat(), 7.0f));
    assert(nearly_equal(j["obb"][7].asFloat(), 8.0f));
}

static void test_parse_obb_flat_array() {
    Json::Value item;
    item["x1"] = 1;
    item["y1"] = 2;
    item["x2"] = 3;
    item["y2"] = 4;
    item["class_id"] = 0;
    item["class_score"] = 0.5;
    item["class_name"] = "person";

    Json::Value obb(Json::arrayValue);
    for (int i = 0; i < 8; ++i) {
        obb.append(static_cast<float>(i));
    }
    item["obb"] = obb;

    AVSAnalyzer::DetectObject d{};
    std::string err;
    const bool ok = AVSAnalyzer::parseDetectObjectFromJson(item, d, &err);
    assert(ok);
    assert(err.empty());
    assert(d.hasObb == true);
    assert(nearly_equal(d.obb[0].x, 0.0f));
    assert(nearly_equal(d.obb[0].y, 1.0f));
    assert(nearly_equal(d.obb[3].x, 6.0f));
    assert(nearly_equal(d.obb[3].y, 7.0f));
}

static void test_serialize_with_segmentation_polygon() {
    AVSAnalyzer::DetectObject d{};
    d.x1 = 5;
    d.y1 = 6;
    d.x2 = 30;
    d.y2 = 40;
    d.class_id = 2;
    d.class_score = 0.77f;
    d.class_name = "person";
    d.hasSegmentation = true;
    d.segmentation.emplace_back(5.0f, 6.0f);
    d.segmentation.emplace_back(28.0f, 7.0f);
    d.segmentation.emplace_back(30.0f, 40.0f);
    d.segmentation.emplace_back(8.0f, 38.0f);

    Json::Value j = AVSAnalyzer::detectObjectToJson(d);
    assert(j.isObject());
    assert(j.isMember("polygon"));
    assert(j["polygon"].isArray());
    assert(j["polygon"].size() == 4);
    assert(j["polygon"][0].isArray());
    assert(j["polygon"][0].size() == 2);
    assert(nearly_equal(j["polygon"][0][0].asFloat(), 5.0f));
    assert(nearly_equal(j["polygon"][0][1].asFloat(), 6.0f));
}

static void test_parse_segmentation_polygon_object_array() {
    Json::Value item;
    item["x1"] = 1;
    item["y1"] = 2;
    item["x2"] = 31;
    item["y2"] = 42;
    item["class_id"] = 6;
    item["class_score"] = 0.61;
    item["class_name"] = "car";

    Json::Value polygon(Json::arrayValue);
    {
        Json::Value p(Json::arrayValue);
        p.append(1.0);
        p.append(2.0);
        polygon.append(p);
    }
    {
        Json::Value p;
        p["x"] = 31.0;
        p["y"] = 2.0;
        polygon.append(p);
    }
    {
        Json::Value p(Json::arrayValue);
        p.append(30.0);
        p.append(42.0);
        polygon.append(p);
    }
    {
        Json::Value p;
        p["x"] = 3.0;
        p["y"] = 40.0;
        polygon.append(p);
    }
    item["polygon"] = polygon;

    AVSAnalyzer::DetectObject d{};
    std::string err;
    const bool ok = AVSAnalyzer::parseDetectObjectFromJson(item, d, &err);
    assert(ok);
    assert(err.empty());
    assert(d.hasSegmentation == true);
    assert(d.segmentation.size() == 4);
    assert(nearly_equal(d.segmentation[0].x, 1.0f));
    assert(nearly_equal(d.segmentation[1].y, 2.0f));
    assert(nearly_equal(d.segmentation[2].x, 30.0f));
    assert(nearly_equal(d.segmentation[3].y, 40.0f));
}

}  // namespace

int main() {
    test_serialize_without_pose();
    test_serialize_with_pose_keypoints();
    test_parse_pose_keypoints_object_array();
    test_parse_pose_keypoints_flat_array();
    test_serialize_with_obb_flat_points();
    test_parse_obb_flat_array();
    test_serialize_with_segmentation_polygon();
    test_parse_segmentation_polygon_object_array();
    return 0;
}
