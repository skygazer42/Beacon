#include "PipelineModeAdvanced.h"
#include "FaceDb.h"

#include <json/json.h>

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
                embeddings.push_back({1.0f, 0.0f});
            }
        }
        return true;
    }

    int embeddingDim() const override { return 2; }

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

    // ========= mode 6 =========
    AVSAnalyzer::Control c6;
    c6.objectCode = "person";
    c6.confThresh = 0.1f;
    c6.nmsThresh = 0.45f;

    DummyDetector classifier6({makeDet(0, 0, 0, 0, "person", 0.9f)});
    DummyDetector detector6({makeDet(10, 10, 60, 60, "person", 0.95f)});

    std::vector<AVSAnalyzer::DetectObject> out;
    bool happen = false;
    float score = 0.0f;
    if (!AVSAnalyzer::runPipelineMode6(&c6, &classifier6, &detector6, image, out, happen, score)) {
        return 10;
    }
    if (!happen || out.empty() || score <= 0.0f) {
        return 11;
    }

    // ========= mode 7 =========
    AVSAnalyzer::Control c7;
    c7.objectCode = "person";
    c7.confThresh = 0.1f;
    c7.nmsThresh = 0.45f;

    DummyDetector detector7({makeDet(10, 10, 60, 60, "person", 0.95f)});
    DummyDetector classifier7({makeDet(0, 0, 0, 0, "person", 0.8f)});
    DummyFeature feature7;

    out.clear();
    happen = false;
    score = 0.0f;
    if (!AVSAnalyzer::runPipelineMode7(&c7, &detector7, &classifier7, &feature7, image, out, happen, score)) {
        return 20;
    }
    if (!feature7.called) {
        return 21;
    }
    if (!happen || out.empty() || score <= 0.0f) {
        return 22;
    }
    if (out[0].attributes.count("feature_dim") == 0U) {
        return 23;
    }

    // ========= mode 7 stranger =========
    const auto faceDbPath = std::filesystem::temp_directory_path() / "beacon_test_pipeline_mode7_face_db.bin";
    AVSAnalyzer::FaceDb faceDb(faceDbPath.string());
    std::string faceErr;
    AVSAnalyzer::FaceItem known;
    known.id = "alice";
    known.name = "Alice";
    known.embedding = {1.0f, 0.0f};
    if (!faceDb.upsert(known, faceErr)) {
        return 30;
    }

    AVSAnalyzer::Control c7stranger;
    c7stranger.objectCode = "person";
    c7stranger.confThresh = 0.1f;
    c7stranger.nmsThresh = 0.45f;
    c7stranger.behaviorConfig = R"JSON({"builtinBehavior":"stranger","stranger":{"minScore":0.6}})JSON";

    DummyDetector detector7stranger({makeDet(10, 10, 60, 60, "person", 0.95f)});
    DummyDetector classifier7stranger({makeDet(0, 0, 0, 0, "person", 0.8f)});
    DummyFeature feature7stranger({{0.0f, 1.0f}});
    Json::Value userData(Json::objectValue);

    out.clear();
    happen = false;
    score = 0.0f;
    if (!AVSAnalyzer::runPipelineMode7(
            &c7stranger, &detector7stranger, &classifier7stranger, &feature7stranger,
            image, out, happen, score, &faceDb, &userData)) {
        return 31;
    }
    if (!happen || out.empty() || userData["event"].asString() != "STRANGER") {
        return 32;
    }
    if (out[0].attributes.count("face_stranger") == 0U || out[0].attributes["face_stranger"] < 0.5f) {
        return 33;
    }
    if (userData["matches"].size() != 1 || userData["matches"][0]["matchedId"].asString() != "alice") {
        return 34;
    }

    DummyFeature feature7known({{1.0f, 0.0f}});
    Json::Value knownUserData(Json::objectValue);
    out.clear();
    happen = false;
    score = 0.0f;
    if (!AVSAnalyzer::runPipelineMode7(
            &c7stranger, &detector7stranger, &classifier7stranger, &feature7known,
            image, out, happen, score, &faceDb, &knownUserData)) {
        return 35;
    }
    if (happen) {
        return 36;
    }
    if (!knownUserData.empty() && knownUserData.isMember("event")) {
        return 37;
    }

    return 0;
}
