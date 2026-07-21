#include "PipelineModeAdvanced.h"
#include "FaceDb.h"

#include <json/json.h>

#include <cmath>
#include <filesystem>
#include <string>
#include <vector>

namespace {

class DummyDetector final : public AVSAnalyzer::Algorithm {
public:
    explicit DummyDetector(std::vector<AVSAnalyzer::DetectObject> outputs)
        : AVSAnalyzer::Algorithm(nullptr), mOutputs(std::move(outputs)) {
        setCreateState(true);
    }

    bool objectDetect(cv::Mat& /*image*/, std::vector<AVSAnalyzer::DetectObject>& detects,
                      float /*scoreThreshold*/, float /*nmsThreshold*/) override {
        detects = mOutputs;
        return true;
    }

private:
    std::vector<AVSAnalyzer::DetectObject> mOutputs;
};

class DummyFeature final : public AVSAnalyzer::Algorithm {
public:
    explicit DummyFeature(std::vector<std::vector<float>> outputs = {})
        : AVSAnalyzer::Algorithm(nullptr), mOutputs(std::move(outputs)) {
        setCreateState(true);
    }

    bool objectDetect(cv::Mat& /*image*/, std::vector<AVSAnalyzer::DetectObject>& /*detects*/,
                      float /*scoreThreshold*/, float /*nmsThreshold*/) override {
        return false;
    }

    bool extractEmbeddings(const std::vector<cv::Mat>& images,
                           std::vector<std::vector<float>>& embeddings,
                           std::string& errMsg) override {
        called = true;
        errMsg.clear();
        embeddings.clear();
        embeddings.reserve(images.size());
        for (size_t i = 0; i < images.size(); ++i) {
            if (i < mOutputs.size()) {
                embeddings.push_back(mOutputs[i]);
            } else {
                embeddings.push_back({1.0f, 0.0f, 0.0f, 0.0f});
            }
        }
        return true;
    }

    int embeddingDim() const override { return 4; }

    bool called = false;

private:
    std::vector<std::vector<float>> mOutputs;
};

AVSAnalyzer::DetectObject makeDet(int x1, int y1, int x2, int y2, const std::string& cls, float score) {
    AVSAnalyzer::DetectObject d;
    d.x1 = x1;
    d.y1 = y1;
    d.x2 = x2;
    d.y2 = y2;
    d.class_id = 0;
    d.class_name = cls;
    d.class_score = score;
    return d;
}

}  // namespace

int main() {
    cv::Mat image(100, 100, CV_8UC3, cv::Scalar(0, 0, 0));

    // ========= mode 8 =========
    AVSAnalyzer::Control c8;
    c8.objectCode = "person";
    c8.confThresh = 0.1f;
    c8.nmsThresh = 0.45f;
    c8.secondaryConfThresh = 0.1f;
    c8.behaviorConfig =
        R"JSON({"pipeline":{"detect1Enabled":true,"detect2Enabled":true,"detectLogic":"and","detect2Input":"roi"}})JSON";

    DummyDetector det1({makeDet(10, 10, 60, 60, "person", 0.9f)});
    DummyDetector det2({makeDet(0, 0, 20, 20, "person", 0.8f)});

    std::vector<AVSAnalyzer::DetectObject> out;
    bool happen = false;
    float score = 0.0f;

    if (!AVSAnalyzer::runPipelineMode8(&c8, &det1, &det2, image, out, happen, score)) {
        return 10;  // should become true after implementation
    }
    if (!happen || out.empty() || score <= 0.0f) {
        return 11;
    }

    // mode8: detect2 full-image input
    AVSAnalyzer::Control c8full;
    c8full.objectCode = "person";
    c8full.confThresh = 0.1f;
    c8full.nmsThresh = 0.45f;
    c8full.secondaryConfThresh = 0.1f;
    c8full.behaviorConfig =
        R"JSON({"pipeline":{"detect1Enabled":true,"detect2Enabled":true,"detectLogic":"and","detect2Input":"full"}})JSON";

    out.clear();
    happen = false;
    score = 0.0f;
    if (!AVSAnalyzer::runPipelineMode8(&c8full, &det1, &det2, image, out, happen, score)) {
        return 12;
    }
    if (!happen || out.empty() || score <= 0.0f) {
        return 13;
    }

    // ========= mode 9 =========
    AVSAnalyzer::Control c9;
    c9.objectCode = "person";
    c9.confThresh = 0.1f;
    c9.nmsThresh = 0.45f;
    c9.secondaryConfThresh = 0.1f;
    c9.behaviorConfig =
        R"JSON({"pipeline":{"detect1Enabled":true,"detect2Enabled":true,"detectLogic":"and","detect2Input":"roi"}})JSON";

    DummyFeature feat;
    out.clear();
    happen = false;
    score = 0.0f;
    if (!AVSAnalyzer::runPipelineMode9(&c9, &det1, &feat, &det2, image, out, happen, score)) {
        return 20;  // should become true after implementation
    }
    if (!feat.called) {
        return 21;
    }
    if (!happen || out.empty() || score <= 0.0f) {
        return 22;
    }

    // ========= mode 9 stranger =========
    const auto faceDbPath = std::filesystem::temp_directory_path() / "beacon_test_pipeline_mode9_face_db.bin";
    AVSAnalyzer::FaceDb faceDb(faceDbPath.string());
    std::string faceErr;
    AVSAnalyzer::FaceItem known;
    known.id = "alice";
    known.name = "Alice";
    known.embedding = {1.0f, 0.0f, 0.0f, 0.0f};
    if (!faceDb.upsert(known, faceErr)) {
        return 30;
    }

    AVSAnalyzer::Control c9stranger;
    c9stranger.objectCode = "person";
    c9stranger.confThresh = 0.1f;
    c9stranger.nmsThresh = 0.45f;
    c9stranger.secondaryConfThresh = 0.1f;
    c9stranger.behaviorConfig =
        R"JSON({"builtinBehavior":"stranger","stranger":{"minScore":0.6},"pipeline":{"detect1Enabled":true,"detect2Enabled":true,"detectLogic":"and","detect2Input":"roi"}})JSON";

    DummyFeature strangerFeat({{0.0f, 1.0f, 0.0f, 0.0f}});
    Json::Value userData(Json::objectValue);
    out.clear();
    happen = false;
    score = 0.0f;
    if (!AVSAnalyzer::runPipelineMode9(&c9stranger, &det1, &strangerFeat, &det2, image, out, happen, score, &faceDb, &userData)) {
        return 31;
    }
    if (!happen || out.empty() || userData["event"].asString() != "STRANGER") {
        return 32;
    }
    if (out[0].attributes.count("face_stranger") == 0U || out[0].attributes["face_stranger"] < 0.5f) {
        return 33;
    }
    if (userData["matches"].size() != 1 || userData["matches"][0]["found"].asBool()) {
        return 34;
    }

    return 0;
}
