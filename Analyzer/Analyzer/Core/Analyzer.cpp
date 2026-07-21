#include "Analyzer.h"
#include "Algorithm.h"
#include "ApiAlgorithmSupport.h"
#include "ByteTrack.h"
#include "DetectObjectGeometry.h"
#include "DetectObjectJson.h"
#include "ReidEmbedPolicy.h"
#include "ReidTracker.h"
#include <json/json.h>
#include <algorithm>
#include <cctype>
#include <exception>
#include <fstream>
#include <stdexcept>
#include <string_view>
#include <unordered_set>
#include "Scheduler.h"
#include "Config.h"
#include "Control.h"
#include "BehaviorApiPayload.h"
#include "BehaviorApiResponse.h"
#include "BehaviorMotion.h"
#include "BehaviorVideoQuality.h"
#include "PipelineModeAdvanced.h"
#include "LineCrossing.h"
#include "Tracker.h"
#include "Utils/Log.h"
#include "Utils/Request.h"
#include "Utils/Base64.h"
#include "Utils/CalcuIOU.h"

namespace {
    std::string to_lower_copy(std::string value) {
        std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
            return static_cast<char>(std::tolower(c));
        });
        return value;
    }

    bool parse_json_object(std::string_view text, Json::Value& out, std::string& err) {
        out = Json::Value(Json::objectValue);
        err.clear();
        if (text.empty()) {
            return true;
        }

        Json::CharReaderBuilder builder;
        builder["collectComments"] = false;
        std::unique_ptr<Json::CharReader> reader(builder.newCharReader());
        const char* begin = text.data();
        const char* end = text.data() + text.size();
        if (!reader->parse(begin, end, &out, &err)) {
            return false;
        }
        if (!out.isObject()) {
            err = "config must be a JSON object";
            return false;
        }
        return true;
    }

    int json_get_int(const Json::Value& root, const char* key, int default_value) {
        if (!root.isObject() || key == nullptr) {
            return default_value;
        }
        const Json::Value v = root.get(key, Json::Value());
        if (v.isInt()) return v.asInt();
        if (v.isUInt()) return static_cast<int>(v.asUInt());
        if (v.isString()) {
            try {
                return std::stoi(v.asString());
            } catch (const std::invalid_argument&) {
                return default_value;
            } catch (const std::out_of_range&) {
                return default_value;
            }
        }
        return default_value;
    }

    float json_get_float(const Json::Value& root, const char* key, float default_value) {
        if (!root.isObject() || key == nullptr) {
            return default_value;
        }
        const Json::Value v = root.get(key, Json::Value());
        if (v.isDouble()) return static_cast<float>(v.asDouble());
        if (v.isInt()) return static_cast<float>(v.asInt());
        if (v.isUInt()) return static_cast<float>(v.asUInt());
        if (v.isString()) {
            try {
                return std::stof(v.asString());
            } catch (const std::invalid_argument&) {
                return default_value;
            } catch (const std::out_of_range&) {
                return default_value;
            }
        }
        return default_value;
    }

    bool json_get_bool(const Json::Value& root, const char* key, bool default_value) {
        if (!root.isObject() || key == nullptr) {
            return default_value;
        }
        const Json::Value v = root.get(key, Json::Value());
        if (v.isBool()) return v.asBool();
        if (v.isInt()) return v.asInt() != 0;
        if (v.isString()) {
            const std::string s = to_lower_copy(v.asString());
            if (s == "1" || s == "true" || s == "yes" || s == "on") return true;
            if (s == "0" || s == "false" || s == "no" || s == "off") return false;
        }
        return default_value;
    }

    std::string json_get_string(const Json::Value& root, const char* key, const std::string& default_value) {
        if (!root.isObject() || key == nullptr) {
            return default_value;
        }
        const Json::Value v = root.get(key, Json::Value());
        if (v.isString()) {
            return v.asString();
        }
        if (v.isInt()) {
            return std::to_string(v.asInt());
        }
        if (v.isUInt()) {
            return std::to_string(static_cast<unsigned int>(v.asUInt()));
        }
        if (v.isDouble()) {
            return std::to_string(v.asDouble());
        }
        return default_value;
    }

    void drawRecognitionRegions(cv::Mat& image, const AVSAnalyzer::Control* control) {
        if (!control) {
            return;
        }
        if (!control->recognitionRegions_points.empty()) {
            cv::polylines(image, control->recognitionRegions_points, true, cv::Scalar(0, 0, 255), 4, 8);
            return;
        }
        if (!control->recognitionRegion_points.empty()) {
            cv::polylines(
                image,
                control->recognitionRegion_points,
                control->recognitionRegion_points.size(),
                cv::Scalar(0, 0, 255),
                4,
                8);
        }
    }

    double calcRecognitionCoverageRatio(const AVSAnalyzer::Control* control, const std::vector<double>& object_d) {
        if (!control) {
            return 0.0;
        }
        if (!control->recognitionRegions_d.empty()) {
            return AVSAnalyzer::calcMaxCoverageRatio(control->recognitionRegions_d, object_d);
        }
        return AVSAnalyzer::CalcuPolygonIOU(control->recognitionRegion_d, object_d);
    }

    double calcRecognitionCoverageRatio(const AVSAnalyzer::Control* control, const AVSAnalyzer::DetectObject& detect) {
        const std::vector<double> object_d = AVSAnalyzer::detectObjectToPolygonPixels(detect);
        return calcRecognitionCoverageRatio(control, object_d);
    }

    int findRecognitionRegionIndex(const AVSAnalyzer::Control* control, bool hasRegion, float px, float py) {
        if (!hasRegion || control == nullptr) {
            return -1;
        }
        const cv::Point2f point(px, py);
        if (!control->recognitionRegions_points.empty()) {
            for (size_t index = 0; index < control->recognitionRegions_points.size(); ++index) {
                const auto& polygon = control->recognitionRegions_points[index];
                if (polygon.size() < 3) {
                    continue;
                }
                if (cv::pointPolygonTest(polygon, point, false) >= 0) {
                    return static_cast<int>(index);
                }
            }
            return -1;
        }
        if (control->recognitionRegion_points.size() >= 3 &&
            cv::pointPolygonTest(control->recognitionRegion_points, point, false) >= 0) {
            return 0;
        }
        return -1;
    }
} // namespace

namespace AVSAnalyzer {

	    Analyzer::Analyzer(Scheduler* scheduler, Control* control) :
	        mScheduler(scheduler),
	        mControl(control)
		    {
        std::string primaryAlgorithmCode;
        if (control) {
            primaryAlgorithmCode = !control->algorithmInstanceKey.empty()
                ? control->algorithmInstanceKey
                : control->algorithmCode;
	        }
	        mAlgorithms.primaryCode = std::move(primaryAlgorithmCode);
	        if (control == nullptr) {
	            return;
	        }
		        // v4.20.1: 离岗/无人值守类事件后处理（持续时间门控），默认仅对 objectCode=absence/unattended 生效；
	        // 也支持 behaviorConfig.postprocess 显式启用。
		        try {
		            BehaviorEventPostprocessConfig cfg = parseBehaviorEventPostprocessConfig(control->behaviorConfig, control->objectCode);
		            mPostprocessState.behaviorEventPostprocess.setConfig(cfg);

	            // Multi-region absence/unattended: gate each region independently and report region_index.
	            if (mPostprocessState.behaviorEventPostprocess.enabled() &&
	                (cfg.mode == BehaviorEventPostprocessMode::Absence || cfg.mode == BehaviorEventPostprocessMode::Unattended) &&
	                control && control->usePipelineMode && control->algorithmPipelineMode == 5 &&
	                control->recognitionRegions_d.size() > 1) {
	                mPostprocessState.perRegionBehaviorEventPostprocess.setConfig(cfg, control->recognitionRegions_d.size());
		                mPostprocessState.usePerRegionBehaviorEventPostprocess = true;
		            }
		        }
			        catch (const std::exception&) { // NOSONAR
			            // keep disabled on error
			        }

	        // v4.722: AREA/区域类行为支持目标尺寸过滤（可选；behaviorConfig 中配置）
	        try {
	            mPostprocessState.targetSizeFilterConfig = parseTargetSizeFilterConfig(control->behaviorConfig);
		        } catch (const std::exception&) { // NOSONAR
		            // keep disabled on error
		        }

	        // v4.726: 行为 API 配置预解析（模式5使用，避免每帧 JSON/字符串匹配）
	        try {
	            (void)mTrackingState.behaviorApiConfigCache.get(control->behaviorConfig, control->behaviorAlgorithmCode, control->objectCode);
		        } catch (const std::exception&) { // NOSONAR
		            // keep defaults on error
		        }

	        // 预分配 JPEG 编码缓冲区与 JSON 写入器，减少每帧的临时分配
        mApiState.jpegParams = { cv::IMWRITE_JPEG_QUALITY, 90 };
        mApiState.jsonWriter["indentation"] = "";
        mApiState.jsonWriter["emitUTF8"] = true;
        // 典型 1080p JPEG 体积约 150-300KB，预留一定空间避免扩容
        mApiState.jpegBuffer.reserve(512 * 1024);
        mApiState.imageBase64.reserve(700 * 1024);

	        // ========== 算法流程模式：加载算法实例 ==========
	        if (control->usePipelineMode) {
	            int mode = control->algorithmPipelineMode;
	            const bool useBasicApiInference = shouldUseBasicApiInference(true, mode, control->api_url);

	            // 模式 1、2、3、8、9 需要加载检测算法
	            if (((mode >= 1 && mode <= 3) || mode == 8 || mode == 9) && !control->algorithmCode.empty()) {
	                if (!useBasicApiInference && control->algorithmCode != "wensou" && control->algorithmCode != "api") {
	                    mAlgorithms.primary = mScheduler->getAlgorithm(mAlgorithms.primaryCode);
	                    if (!mAlgorithms.primary) {
	                        LOGE("Detection algorithm not loaded, code=%s", control->algorithmCode.data());
	                    } else {
	                        LOGI("Pipeline mode %d: Detection algorithm loaded: %s", mode, control->algorithmCode.data());
	                    }
	                } else if (useBasicApiInference) {
	                    LOGI("Pipeline mode %d: Basic algorithm uses API inference (skip local model load)", mode);
	                }
	            }

            // 模式 2 需要加载追踪算法
            if (mode == 2) {
                const std::string trackingCodeLower = to_lower_copy(control->trackingAlgorithmCode);

                // 内置 ByteTrack（不依赖模型文件）
                if (trackingCodeLower.empty() || trackingCodeLower == "bytetrack") {
                    int frameRate = (control->videoFps > 0) ? control->videoFps : 30;
                    int trackBuffer = 30;
                    float trackThresh = 0.5f;
                    float highThresh = 0.6f;
                    float matchThresh = 0.8f;
                    float assignIouThresh = 0.3f;
                    bool debugDrawTrackId = false;

                    Json::Value cfg;
                    std::string err;
                    if (!control->trackingConfig.empty() && control->trackingConfig != "{}") {
                        if (parse_json_object(control->trackingConfig, cfg, err)) {
                            frameRate = json_get_int(cfg, "frameRate", frameRate);
                            trackBuffer = json_get_int(cfg, "trackBuffer", trackBuffer);
                            trackThresh = json_get_float(cfg, "trackThresh", trackThresh);
                            highThresh = json_get_float(cfg, "highThresh", highThresh);
                            matchThresh = json_get_float(cfg, "matchThresh", matchThresh);
                            assignIouThresh = json_get_float(cfg, "assignIouThresh", assignIouThresh);
                            debugDrawTrackId = json_get_bool(cfg, "debugDrawTrackId", debugDrawTrackId);
                        } else {
                            LOGW("Pipeline mode 2: invalid trackingConfig JSON, fallback to defaults, err=%s", err.data());
                        }
                    }

                    if (frameRate <= 0) frameRate = 30;
                    if (trackBuffer < 1) trackBuffer = 1;
                    if (trackThresh < 0.0f) trackThresh = 0.0f;
                    if (trackThresh > 1.0f) trackThresh = 1.0f;
                    if (highThresh < 0.0f) highThresh = 0.0f;
                    if (highThresh > 1.0f) highThresh = 1.0f;
                    if (matchThresh < 0.0f) matchThresh = 0.0f;
                    if (matchThresh > 1.0f) matchThresh = 1.0f;
                    if (assignIouThresh < 0.0f) assignIouThresh = 0.0f;
                    if (assignIouThresh > 1.0f) assignIouThresh = 1.0f;

                    mTrackingState.debugDrawTrackId = debugDrawTrackId;
                    mTrackingState.trackAssignIouThresh = assignIouThresh;
                    mTrackingState.byteTracker = std::make_unique<ByteTracker>(frameRate, trackBuffer, trackThresh, highThresh, matchThresh);

                    LOGI(
                        "Pipeline mode %d: internal ByteTrack enabled fps=%d trackBuffer=%d trackThresh=%.2f highThresh=%.2f matchThresh=%.2f assignIou=%.2f debugDraw=%d",
                        mode,
                        frameRate,
                        trackBuffer,
                        trackThresh,
                        highThresh,
                        matchThresh,
                        assignIouThresh,
                        debugDrawTrackId ? 1 : 0
                    );
                }
                // 未来扩展：可加载模型型追踪算法
                else {
                    mAlgorithms.tracking = mScheduler->getAlgorithm(control->trackingAlgorithmCode);
                    if (!mAlgorithms.tracking) {
                        LOGE("Tracking algorithm not loaded, code=%s", control->trackingAlgorithmCode.data());
                    } else {
                        LOGI("Pipeline mode %d: Tracking algorithm loaded: %s", mode, control->trackingAlgorithmCode.data());

                        float assignIouThresh = 0.3f;
                        float reidCosineThresh = 0.5f;
                        int reidMaxAge = 30;
                        float reidFeatureMomentum = 0.9f;
                        bool debugDrawTrackId = false;
                        int reidEmbedEveryNFrames = 1;
                        int reidMaxRoiPerFrame = 0;
                        bool reidEmbedTargetOnly = false;

                        Json::Value cfg;
                        std::string err;
                        if (!control->trackingConfig.empty() && control->trackingConfig != "{}") {
                            if (parse_json_object(control->trackingConfig, cfg, err)) {
                                assignIouThresh = json_get_float(cfg, "assignIouThresh", assignIouThresh);
                                debugDrawTrackId = json_get_bool(cfg, "debugDrawTrackId", debugDrawTrackId);
                                reidCosineThresh = json_get_float(cfg, "reidCosineThresh", reidCosineThresh);
                                reidMaxAge = json_get_int(cfg, "reidMaxAge", reidMaxAge);
                                reidFeatureMomentum = json_get_float(cfg, "reidFeatureMomentum", reidFeatureMomentum);
                                reidEmbedEveryNFrames = json_get_int(cfg, "reidEmbedEveryNFrames", reidEmbedEveryNFrames);
                                reidMaxRoiPerFrame = json_get_int(cfg, "reidMaxRoiPerFrame", reidMaxRoiPerFrame);
                                reidEmbedTargetOnly = json_get_bool(cfg, "reidEmbedTargetOnly", reidEmbedTargetOnly);
                            } else {
                                LOGW("Pipeline mode 2: invalid trackingConfig JSON, fallback to defaults, err=%s", err.data());
                            }
                        }

                        if (assignIouThresh < 0.0f) assignIouThresh = 0.0f;
                        if (assignIouThresh > 1.0f) assignIouThresh = 1.0f;
                        if (reidCosineThresh < -1.0f) reidCosineThresh = -1.0f;
                        if (reidCosineThresh > 1.0f) reidCosineThresh = 1.0f;
                        if (reidMaxAge < 1) reidMaxAge = 1;
                        if (reidFeatureMomentum < 0.0f) reidFeatureMomentum = 0.0f;
                        if (reidFeatureMomentum > 1.0f) reidFeatureMomentum = 1.0f;
                        if (reidEmbedEveryNFrames < 1) reidEmbedEveryNFrames = 1;
                        if (reidEmbedEveryNFrames > 120) reidEmbedEveryNFrames = 120;
                        if (reidMaxRoiPerFrame < 0) reidMaxRoiPerFrame = 0;
                        if (reidMaxRoiPerFrame > 500) reidMaxRoiPerFrame = 500;

                        mTrackingState.debugDrawTrackId = debugDrawTrackId;
                        mTrackingState.trackAssignIouThresh = assignIouThresh;
                        mTrackingState.reidEmbedEveryNFrames = reidEmbedEveryNFrames;
                        mTrackingState.reidMaxRoiPerFrame = reidMaxRoiPerFrame;
                        mTrackingState.reidEmbedTargetOnly = reidEmbedTargetOnly;

                        ReidTrackerConfig tcfg;
                        tcfg.iouThresh = assignIouThresh;
                        tcfg.cosineThresh = reidCosineThresh;
                        tcfg.maxAge = reidMaxAge;
                        tcfg.featureMomentum = reidFeatureMomentum;
                        mTrackingState.reidTracker = std::make_unique<ReidTracker>(tcfg);

                        LOGI(
                            "Pipeline mode %d: ReID tracker enabled iouThresh=%.2f cosineThresh=%.2f maxAge=%d momentum=%.2f embedEveryN=%d maxRoi=%d targetOnly=%d debugDraw=%d",
                            mode,
                            tcfg.iouThresh,
                            tcfg.cosineThresh,
                            tcfg.maxAge,
                            tcfg.featureMomentum,
                            mTrackingState.reidEmbedEveryNFrames,
                            mTrackingState.reidMaxRoiPerFrame,
                            mTrackingState.reidEmbedTargetOnly ? 1 : 0,
                            debugDrawTrackId ? 1 : 0
                        );
                    }
                }
            }

            // 模式 3/4/6/7 需要加载分类算法
            if ((mode == 3 || mode == 4 || mode == 6 || mode == 7) && !control->classificationAlgorithmCode.empty()) {
                mAlgorithms.classification = mScheduler->getAlgorithm(control->classificationAlgorithmCode);
                if (!mAlgorithms.classification) {
                    LOGE("Classification algorithm not loaded, code=%s", control->classificationAlgorithmCode.data());
                } else {
                    LOGI("Pipeline mode %d: Classification algorithm loaded: %s", mode, control->classificationAlgorithmCode.data());
                }
            }

            // 模式 7/9 需要加载特征算法（extractEmbeddings）
            if ((mode == 7 || mode == 9) && !control->featureAlgorithmCode.empty()) {
                mAlgorithms.feature = mScheduler->getAlgorithm(control->featureAlgorithmCode);
                if (!mAlgorithms.feature) {
                    LOGE("Pipeline mode %d: Feature algorithm not loaded, code=%s", mode, control->featureAlgorithmCode.data());
                } else {
                    LOGI("Pipeline mode %d: Feature algorithm loaded: %s", mode, control->featureAlgorithmCode.data());
                }
            }

            // 所有模式（除了模式 5 使用 API）可能需要加载行为算法
            if (mode >= 1 && mode <= 4 && !control->behaviorAlgorithmCode.empty()) {
                mAlgorithms.behavior = mScheduler->getAlgorithm(control->behaviorAlgorithmCode);
                if (!mAlgorithms.behavior) {
                    LOGE("Behavior algorithm not loaded, code=%s", control->behaviorAlgorithmCode.data());
                } else {
                    LOGI("Pipeline mode %d: Behavior algorithm loaded: %s", mode, control->behaviorAlgorithmCode.data());
                }
            }

            LOGI("Pipeline mode %d initialized successfully", mode);
        }
	        else {
	            // ========== 兼容旧版：非流程模式 ==========
	            // 仅当算法需要本地模型时才尝试获取实例
	            const bool useBasicApiInference = shouldUseBasicApiInference(false, 1, control->api_url);
	            if (!useBasicApiInference && mAlgorithms.primaryCode != "wensou" && mAlgorithms.primaryCode != "api") {
	                mAlgorithms.primary = mScheduler->getAlgorithm(mAlgorithms.primaryCode);
	                if (!mAlgorithms.primary) {
	                    LOGE("Algorithm instance not loaded for code=%s", mAlgorithms.primaryCode.data());
	                }
	            }
	        }
        // =============================================

        // ========== 层级算法支持：加载二级算法 ==========
        if (control->enableHierarchicalAlgorithm && !control->secondaryAlgorithmCode.empty()) {
            mAlgorithms.secondaryCode = control->secondaryAlgorithmCode;
            // 仅当二级算法需要本地模型时才尝试获取实例
            if (control->secondaryApi_url.empty() && mAlgorithms.secondaryCode != "wensou") {
                mAlgorithms.secondary = mScheduler->getAlgorithm(mAlgorithms.secondaryCode);
                if (!mAlgorithms.secondary) {
                    LOGE("Secondary algorithm instance not loaded for code=%s", mAlgorithms.secondaryCode.data());
                } else {
                    LOGI("Secondary algorithm loaded: %s", mAlgorithms.secondaryCode.data());
                }
            }
        }
        // ================================================

    }

    Analyzer::~Analyzer()
    {
        mAlgorithms.primary = nullptr; // 生命周期由 Scheduler 管理，引用计数由 bind/unbind 控制
        mAlgorithms.secondary = nullptr; // 生命周期由 Scheduler 管理

        // ========== 算法流程模式：清理算法指针 ==========
        mAlgorithms.tracking = nullptr;       // 生命周期由 Scheduler 管理
        mAlgorithms.classification = nullptr; // 生命周期由 Scheduler 管理
        mAlgorithms.behavior = nullptr;       // 生命周期由 Scheduler 管理
        mAlgorithms.feature = nullptr;        // 生命周期由 Scheduler 管理
        // ==============================================

    }

	    std::string Analyzer::getLastUserDataJson() const {
	        try {
	            if (!mPostprocessState.lastUserData.isObject()) {
	                return "";
            }
            if (mPostprocessState.lastUserData.getMemberNames().empty()) {
                return "";
            }
            Json::StreamWriterBuilder wbuilder;
	            wbuilder["indentation"] = "";
	            wbuilder["emitUTF8"] = true;
	            return Json::writeString(wbuilder, mPostprocessState.lastUserData);
	        } catch (const std::exception&) { // NOSONAR
	            return "";
	        }
	    }

    bool Analyzer::handleVideoFrame(int64_t frameCount, cv::Mat& image, std::vector<DetectObject>& happenDetects, bool& happen, float& happenScore) {
        // Region index is best-effort metadata for multi-region builtin behaviors.
        mPostprocessState.lastRegionIndex = -1;
        // Clear per-frame user_data to avoid stale values.
        mPostprocessState.lastUserData = Json::Value(Json::objectValue);

        int64_t behaviorPostprocessNowMs = 0;
        auto applyBehaviorEventPostprocess = [&]() {
            if (mPostprocessState.usePerRegionBehaviorEventPostprocess) {
                return; // per-region gate is handled inside builtin behavior logic
            }
            if (!mPostprocessState.behaviorEventPostprocess.enabled()) {
                return;
            }
            const int64_t nowMs = getCurTime();
            behaviorPostprocessNowMs = nowMs;
            const bool raw = happen;
            const bool gated = mPostprocessState.behaviorEventPostprocess.update(raw, nowMs);
            happen = gated;
            if (!happen) {
                happenScore = 0.0f;
                mPostprocessState.lastRegionIndex = -1;
            } else if (happenScore <= 0.0f) {
                happenScore = 1.0f;
            }
        };

        // ========== 算法流程模式：分发到对应的流程处理方法 ==========
        if (mControl->usePipelineMode) {
            int mode = mControl->algorithmPipelineMode;
            bool ok = false;
            switch (mode) {
                case 1:
                    ok = executePipelineMode1(frameCount, image, happenDetects, happen, happenScore);
                    break;
                case 2:
                    ok = executePipelineMode2(frameCount, image, happenDetects, happen, happenScore);
                    break;
                case 3:
                    ok = executePipelineMode3(frameCount, image, happenDetects, happen, happenScore);
                    break;
                case 4:
                    ok = executePipelineMode4(frameCount, image, happenDetects, happen, happenScore);
                    break;
                case 5:
                    ok = executePipelineMode5(frameCount, image, happenDetects, happen, happenScore);
                    break;
                case 6:
                    ok = executePipelineMode6(frameCount, image, happenDetects, happen, happenScore);
                    break;
                case 7:
                    ok = executePipelineMode7(frameCount, image, happenDetects, happen, happenScore);
                    break;
                case 8:
                    ok = executePipelineMode8(frameCount, image, happenDetects, happen, happenScore);
                    break;
                case 9:
                    ok = executePipelineMode9(frameCount, image, happenDetects, happen, happenScore);
                    break;
                default:
                    LOGE("Unknown pipeline mode: %d, falling back to legacy mode", mode);
                    ok = false;
                    break;
            }

            if (ok) {
                applyBehaviorEventPostprocess();

                // v4.643: behavior user_data for absence/unattended after gating (single-region / non-per-region mode).
                // For per-region mode, executePipelineMode5 sets user_data directly.
                if (!mPostprocessState.usePerRegionBehaviorEventPostprocess &&
                    mode == 5 &&
                    happen &&
                    (mPostprocessState.lastMode5BuiltinBehavior == BuiltinBehaviorType::Absence ||
                     mPostprocessState.lastMode5BuiltinBehavior == BuiltinBehaviorType::Unattended) &&
                    mPostprocessState.lastUserData.getMemberNames().empty()) {
                    int64_t nowMs = behaviorPostprocessNowMs > 0 ? behaviorPostprocessNowMs : getCurTime();
                    const int64_t durMs = mPostprocessState.behaviorEventPostprocess.activeDurationMs(nowMs);

                    Json::Value ud(Json::objectValue);
                    ud["behavior"] = builtinBehaviorTypeToString(mPostprocessState.lastMode5BuiltinBehavior);
                    ud["event"] = (mPostprocessState.lastMode5BuiltinBehavior == BuiltinBehaviorType::Unattended) ? "LEAVE" : "NOONE";
                    if (mPostprocessState.lastRegionIndex >= 0) {
                        ud["region_index"] = mPostprocessState.lastRegionIndex;
                    }
                    ud["trigger_duration_ms"] = (Json::Int64)std::max<int64_t>(0, durMs);
	                    ud["trigger_duration_seconds"] = durMs > 0 ? (static_cast<double>(durMs) / 1000.0) : 0.0;
                    mPostprocessState.lastUserData = ud;
                }
            }
            return ok;
        }
        // ==========================================================

        // ========== 兼容旧版：非流程模式 ==========
        // 优先走外部 API 推理：凡是布控携带 api_url 即调用外部服务（支持基础算法 API 化）
        if (!mControl->api_url.empty())
        {
            // API 类型算法：调用外部 API 服务
            this->postImage2Server(frameCount, image, happenDetects, happen, happenScore);
        }
        else if (mControl->algorithmCode == "wensou")
        {

            //v3.52新增，调用文搜API算法服务
            int len = mControl->videoFps * 2;
            if (frameCount % len == 0) {
                this->postImage2Server(frameCount, image, happenDetects, happen, happenScore);
            }

        }
        else {
            // 本地模型推理走统一逻辑
            happenDetects.clear();
            happen = false;
            happenScore = 0;

            if (!mAlgorithms.primary) {
                LOGE("Algorithm not loaded, code=%s", mAlgorithms.primaryCode.data());
                return false;
            }

            // ========== 使用配置的算法参数 ==========
            // 使用新的标准参数名称：confThresh (置信度阈值), nmsThresh (NMS阈值)
            mAlgorithms.primary->objectDetect(image, happenDetects, mControl->confThresh, mControl->nmsThresh);
            // ========================================

            // ========== 层级算法：对主检测结果应用二级算法 ==========
            if (mControl->enableHierarchicalAlgorithm && !happenDetects.empty()) {
                processSecondaryAlgorithm(image, happenDetects);
            }
            // =======================================================

            if (!happenDetects.empty()) {

                drawRecognitionRegions(image, mControl);
                int matchCount = 0;
                for (size_t i = 0; i < happenDetects.size(); i++)
                {
                    double iou = calcRecognitionCoverageRatio(mControl, happenDetects[i]);

                    if (iou >= 0.5) {
                        int class_id = happenDetects[i].class_id;
                        std::string class_name;
                        if (class_id < mControl->objects_v1_len) {
                            class_name = mControl->objects_v1[class_id];
                        }
                        else {
                            LOGE("class error,class_id=%d,objects_v1_len=%d", class_id, mControl->objects_v1_len);
                        }

                        happenDetects[i].class_name = class_name;

                        if (class_name == mControl->objectCode) {
                            happenDetects[i].happen = true;
                            ++matchCount;
                        }
                    }
                }
                if (matchCount > 0) {//匹配数据大于0，则认为发生了报警事件
                    happen = true;
                    happenScore = 1.0;
                }

            }
        }
        applyBehaviorEventPostprocess();
        return true;

    }
    bool Analyzer::postImage2Server(int64_t frameCount, const cv::Mat& image, std::vector<DetectObject>& happenDetects, bool& happen, float& happenScore) {

        happenDetects.clear();
        happen = false;
        happenScore = 0.0f;

        if (mControl == nullptr || mControl->api_url.empty()) {
            return true;
        }

	        const Config* config = mScheduler ? mScheduler->getConfig() : nullptr;
        if (config) {
            ApiInferGuardConfig guardCfg;
            guardCfg.minIntervalMs = std::max<int64_t>(0, (int64_t)config->apiInferMinIntervalMs);
            guardCfg.circuitBreakerFails = std::max(0, config->apiInferCircuitBreakerFails);
            guardCfg.circuitBreakerOpenSeconds = std::max(0, config->apiInferCircuitBreakerOpenSeconds);
            mApiState.inferGuard.setConfig(guardCfg);

            mApiState.inferConnectTimeoutSeconds = std::max(1, config->apiInferConnectTimeoutSeconds);
            mApiState.inferTimeoutSeconds = std::max(1, config->apiInferTimeoutSeconds);
            mApiState.inferRetryMax = std::max(0, config->apiInferRetryMax);
        }

        const int64_t startMonoMs = getCurTime();
        std::string guardReason;
        if (!mApiState.inferGuard.tryAcquire(startMonoMs, &guardReason)) {
            if (mScheduler) {
                if (guardReason == "min_interval") {
                    mScheduler->statsIncApiInferSkippedMinInterval();
                }
                else if (guardReason == "circuit_open") {
                    mScheduler->statsIncApiInferSkippedCircuitOpen();
                }
            }
            return true;
        }
        if (mScheduler) {
            mScheduler->statsIncApiInferAllowed();
        }

        // 复用缓冲区，避免频繁分配/释放
        mApiState.jpegBuffer.clear();
        cv::imencode(".jpg", image, mApiState.jpegBuffer, mApiState.jpegParams);
        const auto JPGBufSize = static_cast<int>(mApiState.jpegBuffer.size());

        bool ok = false;
        if (JPGBufSize > 0) {
            Base64 base64;
            mApiState.imageBase64.clear();
            base64.encode(mApiState.jpegBuffer.data(), JPGBufSize, mApiState.imageBase64);

            Json::Value param;
            param["image_base64"] = mApiState.imageBase64;//当前帧
            param["nodeCode"] = config ? config->code : "";
            param["controlCode"] = mControl->code;//布控编号
            param["streamCode"] = mControl->streamCode;//视频流编号
            param["streamApp"] = mControl->streamApp;//视频app
            param["streamName"] = mControl->streamName;//视频name
            param["flowCode"] = mControl->algorithmCode;//算法编号
            param["algorithmCode"] = mControl->algorithmCode;//算法编号（别名）
            param["modelClassNames"] = mControl->object_str;//算法模型支持的所有目标
            param["detectClassNames"] = mControl->objectCode;//当前布控选中的算法目标
            param["polygonType"] = 3;//3表示绘制的算法识别区域是多边形
            param["polygon"] = mControl->recognitionRegion;//绘制的多边形识别区域
            param["classThresh"] = mControl->classThresh;
            param["overlapThresh"] = mControl->overlapThresh;

            // ========== 扩展字段：OSD配置 ==========
            Json::Value osdConfig;
            osdConfig["enabled"] = mControl->osdEnabled;
            osdConfig["text"] = mControl->osdText;
            osdConfig["position"] = mControl->osdPosition;
            osdConfig["x"] = mControl->osdX;
            osdConfig["y"] = mControl->osdY;
            osdConfig["fontSize"] = mControl->osdFontSize;
            osdConfig["fontColor"] = mControl->osdFontColor;
            osdConfig["bgEnabled"] = mControl->osdBgEnabled;
            param["osdConfig"] = osdConfig;
            // =========================================

            // ========== 扩展字段：视频流信息 ==========
            Json::Value videoInfo;
            videoInfo["width"] = mControl->videoWidth;
            videoInfo["height"] = mControl->videoHeight;
            videoInfo["fps"] = mControl->videoFps;
            param["videoInfo"] = videoInfo;
            // =========================================

            // ========== 扩展字段：推流配置 ==========
            Json::Value pushStreamConfig;
            pushStreamConfig["enabled"] = mControl->pushStream;
            pushStreamConfig["url"] = mControl->pushStreamUrl;
            pushStreamConfig["codec"] = mControl->pushVideoCodec;
            pushStreamConfig["bitrate"] = mControl->pushVideoBitrate;
            pushStreamConfig["fps"] = mControl->pushVideoFps;
            pushStreamConfig["width"] = mControl->pushVideoWidth;
            pushStreamConfig["height"] = mControl->pushVideoHeight;
            pushStreamConfig["gop"] = mControl->pushVideoGop;
            param["pushStreamConfig"] = pushStreamConfig;
            // =========================================

            // ========== 扩展字段：算法模型参数 ==========
            Json::Value algorithmParams;
            algorithmParams["confThresh"] = mControl->confThresh;
            algorithmParams["nmsThresh"] = mControl->nmsThresh;
            algorithmParams["modelConcurrency"] = mControl->modelConcurrency;
            algorithmParams["inputWidth"] = mControl->inputWidth;
            algorithmParams["inputHeight"] = mControl->inputHeight;
            algorithmParams["modelPrecision"] = mControl->modelPrecision;
            param["algorithmParams"] = algorithmParams;
            // =========================================

            // ========== 扩展字段：层级算法配置 ==========
            if (mControl->enableHierarchicalAlgorithm) {
                Json::Value hierarchicalConfig;
                hierarchicalConfig["enabled"] = true;
                hierarchicalConfig["secondaryAlgorithmCode"] = mControl->secondaryAlgorithmCode;
                hierarchicalConfig["secondaryApiUrl"] = mControl->secondaryApi_url;
                hierarchicalConfig["secondaryConfThresh"] = mControl->secondaryConfThresh;
                param["hierarchicalConfig"] = hierarchicalConfig;
            }
            // =========================================

            // ========== 扩展字段：越线检测配置 ==========
            if (mControl->enableTracking && !mControl->lineCoordinates.empty()) {
                Json::Value lineCrossingConfig;
                lineCrossingConfig["enabled"] = true;
                lineCrossingConfig["lineCoordinates"] = mControl->lineCoordinates;
                lineCrossingConfig["violationDirection"] = mControl->lineViolationDirection;
                param["lineCrossingConfig"] = lineCrossingConfig;
            }
            // =========================================

            // ========== 扩展字段：通用扩展字段 ==========
            Json::Value extensions;
            extensions["frameId"] = static_cast<Json::Int64>(frameCount);
            extensions["timestamp"] = static_cast<Json::Int64>(getCurTime());
            extensions["drawType"] = mControl->drawType;
            param["extensions"] = extensions;
            // =========================================

            const std::string data = Json::writeString(mApiState.jsonWriter, param);

            Request request;
            std::string response;
            const int maxAttempts = 1 + std::max(0, mApiState.inferRetryMax);
            for (int attempt = 0; attempt < maxAttempts; ++attempt) {
                if (attempt > 0 && mScheduler) {
                    mScheduler->statsIncApiInferRetried();
                }

                response.clear();
                const bool posted = request.post(
                    mControl->api_url.c_str(),
                    data,
                    response,
                    "",
                    mApiState.inferConnectTimeoutSeconds,
                    mApiState.inferTimeoutSeconds
                );
                if (!posted) {
                    continue;
                }

                Json::CharReaderBuilder builder;
                const std::unique_ptr<Json::CharReader> reader(builder.newCharReader());

                Json::Value root;
                JSONCPP_STRING errs;
                if (!reader->parse(response.data(), response.data() + response.size(), &root, &errs) || !errs.empty()) {
                    LOGE("api infer parse error: %s", errs.c_str());
                    continue;
                }

                if (!root["code"].isInt() || !root["msg"].isString()) {
                    LOGE("api infer incorrect return parameter format");
                    continue;
                }

                const int code = root["code"].asInt();
                const std::string msg = root["msg"].asCString();
                if (code != 1000) {
                    LOGE("api infer code=%d,msg=%s", code, msg.c_str());
                    continue;
                }

                Json::Value result = root["result"];
                if (!result.isObject()) {
                    LOGE("api infer missing result object");
                    continue;
                }

                if (result["happen"].isBool()) {
                    happen = result["happen"].asBool();
                }
                if (result["happenScore"].isNumeric()) {
                    happenScore = result["happenScore"].asFloat();
                }

                Json::Value result_detects = result["detects"];
                if (result_detects.isArray()) {
                    for (const auto& i : result_detects) {
                        DetectObject detect;
                        std::string parseErr;
                        if (!parseDetectObjectFromJson(i, detect, &parseErr)) {
                            continue;
                        }
                        happenDetects.push_back(std::move(detect));
                    }
                }

                ok = true;
                break;
            }
        }

        const int64_t endMonoMs = getCurTime();
        if (mScheduler && endMonoMs >= startMonoMs) {
            mScheduler->statsObserveApiInferLatencyMs((uint64_t)(endMonoMs - startMonoMs));
        }

        if (mScheduler) {
            if (ok) {
                mScheduler->statsIncApiInferSuccess();
            }
            else {
                mScheduler->statsIncApiInferFailure();
            }
        }

        bool circuitOpened = false;
        mApiState.inferGuard.recordResult(ok, endMonoMs, &circuitOpened);
        if (circuitOpened && mScheduler) {
            mScheduler->statsIncApiInferCircuitOpened();
        }

        if (!ok) {
            happenDetects.clear();
            happen = false;
            happenScore = 0.0f;
        }

        return true;
    }

    // ========== 层级算法实现 ==========
    bool Analyzer::processSecondaryAlgorithm(const cv::Mat& image, std::vector<DetectObject>& detects) {
        if (!mControl->enableHierarchicalAlgorithm || !mAlgorithms.secondary) {
            return true;  // 未启用或未加载二级算法，直接返回成功
        }

        LOGI("Processing secondary algorithm for %zu objects", detects.size());

        for (auto& detect : detects) {
            // 提取检测区域
            int x1 = std::max(0, detect.x1);
            int y1 = std::max(0, detect.y1);
            int x2 = std::min(image.cols, detect.x2);
            int y2 = std::min(image.rows, detect.y2);

            if (x2 <= x1 || y2 <= y1) {
                LOGE("Invalid detection bbox: (%d,%d,%d,%d)", x1, y1, x2, y2);
                continue;
            }

            // 裁剪 ROI
            cv::Rect roi(x1, y1, x2 - x1, y2 - y1);
            cv::Mat roiImage = image(roi);

            // 对 ROI 应用二级算法
            std::vector<DetectObject> subDetects;
            if (mAlgorithms.secondary->objectDetect(roiImage, subDetects,
                                                   mControl->secondaryConfThresh,
                                                   mControl->nmsThresh)) {
                // 将子检测结果坐标转换到原图坐标系
                for (auto& subDetect : subDetects) {
                    subDetect.x1 += x1;
                    subDetect.y1 += y1;
                    subDetect.x2 += x1;
                    subDetect.y2 += y1;
                }

                detect.subObjects = subDetects;
                detect.subAlgorithmCode = mAlgorithms.secondaryCode;
                LOGI("Secondary algorithm detected %zu sub-objects for object %s",
                     subDetects.size(), detect.class_name.c_str());
            }
        }

        return true;
    }
    // ====================================

    // ========== 算法流程模式实现 ==========

	    // 模式 1：检测 >> 行为
	    bool Analyzer::executePipelineMode1(int64_t frameCount, cv::Mat& image, std::vector<DetectObject>& happenDetects, bool& happen, float& happenScore) {
	        happenDetects.clear();
	        happen = false;
	        happenScore = 0.0;

	        const bool useBasicApiInference = shouldUseBasicApiInference(true, 1, mControl->api_url);
	        if (!useBasicApiInference && !mAlgorithms.primary) {
	            LOGE("Pipeline Mode 1: Detection algorithm not loaded");
	            return false;
	        }

	        // Step 1: 检测算法
	        std::vector<DetectObject> detectionResults;
	        if (useBasicApiInference) {
	            bool apiHappen = false;
	            float apiHappenScore = 0.0f;
	            this->postImage2Server(frameCount, image, detectionResults, apiHappen, apiHappenScore);
	        } else {
	            mAlgorithms.primary->objectDetect(image, detectionResults, mControl->confThresh, mControl->nmsThresh);
	        }

	        if (detectionResults.empty()) {
	            return true;  // 无检测结果
	        }

        // Step 2: 行为算法（区域匹配 + 目标过滤）
        drawRecognitionRegions(image, mControl);

        int matchCount = 0;
        for (auto& detect : detectionResults) {
            int x1 = detect.x1;
	            int y1 = detect.y1;
	            int x2 = detect.x2;
	            int y2 = detect.y2;

		            double iou = calcRecognitionCoverageRatio(mControl, detect);

		            if (iou >= 0.5) {
                    const int width = x2 - x1;
                    const int height = y2 - y1;
                    if (!passTargetSizeFilter(mPostprocessState.targetSizeFilterConfig, width, height, image.cols, image.rows)) {
                        continue;
                    }

	                if (detect.class_name.empty()) {
	                    int class_id = detect.class_id;
	                    std::string class_name;
	                    if (class_id < mControl->objects_v1_len) {
	                        class_name = mControl->objects_v1[class_id];
	                    } else {
	                        LOGE("class error, class_id=%d, objects_v1_len=%d", class_id, mControl->objects_v1_len);
	                    }
	                    detect.class_name = class_name;
	                }

	                if (!detect.class_name.empty() && detect.class_name == mControl->objectCode) {
	                    detect.happen = true;
	                    ++matchCount;
	                }

	                happenDetects.push_back(detect);
            }
        }

        if (matchCount > 0) {
            happen = true;
            happenScore = 1.0;
        }

        return true;
    }

	    // 模式 2：检测 >> 追踪 >> 行为
	    bool Analyzer::executePipelineMode2(int64_t frameCount, cv::Mat& image, std::vector<DetectObject>& happenDetects, bool& happen, float& happenScore) {
	        happenDetects.clear();
	        happen = false;
	        happenScore = 0.0;

	        const bool useBasicApiInference = shouldUseBasicApiInference(true, 2, mControl->api_url);
	        if (!useBasicApiInference && !mAlgorithms.primary) {
	            LOGE("Pipeline Mode 2: Detection algorithm not loaded");
	            return false;
	        }

	        // Step 1: 检测算法
	        std::vector<DetectObject> detectionResults;
	        if (useBasicApiInference) {
	            bool apiHappen = false;
	            float apiHappenScore = 0.0f;
	            this->postImage2Server(frameCount, image, detectionResults, apiHappen, apiHappenScore);
	        } else {
	            mAlgorithms.primary->objectDetect(image, detectionResults, mControl->confThresh, mControl->nmsThresh);
	        }

	        if (detectionResults.empty()) {
	            return true;  // 无检测结果
	        }

        // Step 2: 追踪（内置 ByteTrack 优先；否则降级为“无追踪”）
        std::vector<DetectObject> trackingResults = detectionResults;
        if (mTrackingState.byteTracker) {
            mTrackingState.byteTrackFrameId++;
            std::vector<STrack*> tracks = mTrackingState.byteTracker->update(trackingResults, mTrackingState.byteTrackFrameId);

            for (auto& det : trackingResults) {
                const int w = det.x2 - det.x1;
                const int h = det.y2 - det.y1;
                if (w <= 0 || h <= 0) {
                    continue;
                }
                const cv::Rect detRect(det.x1, det.y1, w, h);

                int bestTrackId = -1;
                int bestTrackLen = 0;
                float bestIou = 0.0f;
                for (const auto* t : tracks) {
                    if (!t) continue;
                    const float v = ByteTracker::iou(detRect, t->bbox);
                    if (v > bestIou) {
                        bestIou = v;
                        bestTrackId = t->trackId;
                        bestTrackLen = t->trackletLen;
                    }
                }

                if (bestTrackId > 0 && bestIou >= mTrackingState.trackAssignIouThresh) {
                    det.attributes["track_id"] = static_cast<float>(bestTrackId);
                    det.attributes["track_len"] = static_cast<float>(bestTrackLen);
                }
            }

            if (mTrackingState.debugDrawTrackId) {
                for (const auto& det : trackingResults) {
                    auto it = det.attributes.find("track_id");
                    if (it == det.attributes.end()) continue;
                    const auto trackId = static_cast<int>(it->second);
                    if (trackId <= 0) continue;
                    const int x = std::max(0, det.x1);
                    const int y = std::max(0, det.y1 - 5);
                    const std::string text = "T" + std::to_string(trackId);
                    cv::putText(image, text, cv::Point(x, y), cv::FONT_HERSHEY_SIMPLEX, 0.6, cv::Scalar(0, 255, 255), 2);
                }
            }
        } else if (mAlgorithms.tracking && mTrackingState.reidTracker) {
            // 模式型追踪：ReID embedding + 关联（TrackID 写入 DetectObject.attributes）
                mTrackingState.reidFrameId++;

                const bool shouldEmbed = should_run_reid_embedding(mTrackingState.reidFrameId, mTrackingState.reidEmbedEveryNFrames);
                std::string targetName;
                if (mControl && mTrackingState.reidEmbedTargetOnly) {
                    targetName = mControl->objectCode;
                    if (!targetName.empty()) {
                        // Ensure class_name is filled for targetOnly filtering.
                        for (auto& det : trackingResults) {
                            if (!det.class_name.empty()) {
                                continue;
                            }
                            const int class_id = det.class_id;
                            if (class_id >= 0 && class_id < mControl->objects_v1_len) {
                                det.class_name = mControl->objects_v1[class_id];
                            }
                        }
                    }
                }

                std::vector<std::vector<float>> roiEmbeddings;
                std::string embErr;
                bool embOk = true;

                std::vector<size_t> roiToDet;
                std::vector<cv::Mat> roiImages;
                if (shouldEmbed) {
                    const auto embedIndices = select_reid_embedding_indices(
                        trackingResults,
                        mTrackingState.reidMaxRoiPerFrame,
                        mTrackingState.reidEmbedTargetOnly,
                        targetName
                    );
                    roiImages.reserve(embedIndices.size());
                    roiToDet.reserve(embedIndices.size());

                    for (size_t i : embedIndices) {
                        if (i >= trackingResults.size()) {
                            continue;
                        }
                        const auto& det = trackingResults[i];
                        int x1 = std::max(0, det.x1);
                        int y1 = std::max(0, det.y1);
                        int x2 = std::min(image.cols, det.x2);
                        int y2 = std::min(image.rows, det.y2);
                        if (x2 <= x1 || y2 <= y1) {
                            continue;
                        }
                        cv::Rect roi(x1, y1, x2 - x1, y2 - y1);
                        roiImages.push_back(image(roi));
                        roiToDet.push_back(i);
                    }

                    if (!roiImages.empty()) {
                        embOk = mAlgorithms.tracking->extractEmbeddings(roiImages, roiEmbeddings, embErr);
                        if (!embOk) {
                            LOGW("Pipeline mode 2: ReID extractEmbeddings failed: %s", embErr.c_str());
                            roiEmbeddings.clear();
                        }
                    }
                }

                // Align embeddings to detection indices (missing => empty feature).
                std::vector<std::vector<float>> detEmbeddings;
                if (shouldEmbed && embOk && roiEmbeddings.size() == roiImages.size()) {
                    detEmbeddings.assign(trackingResults.size(), std::vector<float>());
                    for (size_t k = 0; k < roiToDet.size(); ++k) {
                        const size_t di = roiToDet[k];
                        if (di >= detEmbeddings.size()) {
                            continue;
                        }
                        detEmbeddings[di] = roiEmbeddings[k];
                    }
                }

                std::vector<ReidDetection> detBoxes;
                detBoxes.reserve(trackingResults.size());
                for (const auto& det : trackingResults) {
                    ReidDetection b;
                    b.x1 = det.x1;
                    b.y1 = det.y1;
                    b.x2 = det.x2;
                    b.y2 = det.y2;
                    detBoxes.push_back(b);
                }

                std::vector<int> trackIds;
                std::vector<int> trackLens;
                if (std::string trErr;
                    mTrackingState.reidTracker->update(detBoxes, detEmbeddings, mTrackingState.reidFrameId, trackIds, trackLens, trErr)) {
                    for (size_t i = 0; i < trackingResults.size() && i < trackIds.size(); ++i) {
                        const int tid = trackIds[i];
                        if (tid > 0) {
                            trackingResults[i].attributes["track_id"] = static_cast<float>(tid);
                            if (i < trackLens.size()) {
                                trackingResults[i].attributes["track_len"] = static_cast<float>(trackLens[i]);
                            }
                        }
                    }
                }
                else {
                    LOGW("Pipeline mode 2: ReID tracker update failed: %s", trErr.c_str());
                }

                if (mTrackingState.debugDrawTrackId) {
                    for (const auto& det : trackingResults) {
                        auto it = det.attributes.find("track_id");
                        if (it == det.attributes.end()) continue;
                        const auto trackId = static_cast<int>(it->second);
                        if (trackId <= 0) continue;
                        const int x = std::max(0, det.x1);
                        const int y = std::max(0, det.y1 - 5);
                        const std::string text = "T" + std::to_string(trackId);
                        cv::putText(image, text, cv::Point(x, y), cv::FONT_HERSHEY_SIMPLEX, 0.6, cv::Scalar(0, 255, 255), 2);
                    }
                }
        }

        // Step 3: 行为算法（区域匹配 + 目标过滤）
        drawRecognitionRegions(image, mControl);

        int matchCount = 0;
        for (auto& detect : trackingResults) {
	            double iou = calcRecognitionCoverageRatio(mControl, detect);

	            if (iou >= 0.5) {
	                if (detect.class_name.empty()) {
	                    int class_id = detect.class_id;
	                    std::string class_name;
	                    if (class_id < mControl->objects_v1_len) {
	                        class_name = mControl->objects_v1[class_id];
	                    } else {
	                        LOGE("class error, class_id=%d, objects_v1_len=%d", class_id, mControl->objects_v1_len);
	                    }
	                    detect.class_name = class_name;
	                }

	                if (!detect.class_name.empty() && detect.class_name == mControl->objectCode) {
	                    detect.happen = true;
	                    ++matchCount;
	                }

	                happenDetects.push_back(detect);
            }
        }

        if (matchCount > 0) {
            happen = true;
            happenScore = 1.0;
        }

        return true;
    }

	    // 模式 3：检测 >> 分类 >> 行为
	    bool Analyzer::executePipelineMode3(int64_t frameCount, cv::Mat& image, std::vector<DetectObject>& happenDetects, bool& happen, float& happenScore) {
	        happenDetects.clear();
	        happen = false;
	        happenScore = 0.0;

	        const bool useBasicApiInference = shouldUseBasicApiInference(true, 3, mControl->api_url);
	        if (!useBasicApiInference && !mAlgorithms.primary) {
	            LOGE("Pipeline Mode 3: Detection algorithm not loaded");
	            return false;
	        }

	        // Step 1: 检测算法
	        std::vector<DetectObject> detectionResults;
	        if (useBasicApiInference) {
	            bool apiHappen = false;
	            float apiHappenScore = 0.0f;
	            this->postImage2Server(frameCount, image, detectionResults, apiHappen, apiHappenScore);
	        } else {
	            mAlgorithms.primary->objectDetect(image, detectionResults, mControl->confThresh, mControl->nmsThresh);
	        }

	        if (detectionResults.empty()) {
	            return true;  // 无检测结果
	        }

	        // 对检测结果补全 class_name（避免算法未填充 class_name 时导致后续过滤失败）
	        for (auto& detect : detectionResults) {
	            fillPipelineClassNameFromControl(mControl, detect);
	        }

	        // Step 2: 分类算法（对每个检测目标进行二次分类）
	        if (mAlgorithms.classification) {
	            for (auto& detect : detectionResults) {
	                // 提取检测区域
                int x1 = std::max(0, detect.x1);
                int y1 = std::max(0, detect.y1);
                int x2 = std::min(image.cols, detect.x2);
                int y2 = std::min(image.rows, detect.y2);

                if (x2 <= x1 || y2 <= y1) {
                    continue;
                }

                // 裁剪 ROI
                cv::Rect roi(x1, y1, x2 - x1, y2 - y1);
                cv::Mat roiImage = image(roi);

                // 对 ROI 应用分类算法
                std::vector<DetectObject> classResults;
                mAlgorithms.classification->objectDetect(roiImage, classResults, mControl->confThresh, mControl->nmsThresh);

                // 更新检测目标的分类结果（使用分类结果的 class_name；兼容仅返回 class_id 的分类器）
                if (!classResults.empty()) {
                    applyPipelineClassificationResult(mControl, classResults[0], detect);

                    LOGI("Pipeline Mode 3: Object reclassified as: %s (%.2f)",
                         detect.class_name.c_str(), detect.class_score);
                }
            }
        } else {
            LOGW("Pipeline Mode 3: Classification algorithm not loaded, using detection results directly");
        }

        // Step 3: 行为算法（区域匹配 + 目标过滤）
        drawRecognitionRegions(image, mControl);

        int matchCount = 0;
        for (auto& detect : detectionResults) {
            double iou = calcRecognitionCoverageRatio(mControl, detect);

            if (iou >= 0.5) {
                if (pipelineDetectMatchesObjectCode(mControl, detect)) {
                    detect.happen = true;
                    ++matchCount;
                }

                happenDetects.push_back(detect);
            }
        }

        if (matchCount > 0) {
            happen = true;
            happenScore = 1.0;
        }

        return true;
    }

    // 模式 4：分类 >> 行为
    bool Analyzer::executePipelineMode4(int64_t /*frameCount*/, cv::Mat& image, std::vector<DetectObject>& happenDetects, bool& happen, float& happenScore) {
        happenDetects.clear();
        happen = false;
        happenScore = 0.0;

        if (!mAlgorithms.classification) {
            LOGE("Pipeline Mode 4: Classification algorithm not loaded");
            return false;
        }

        // Step 1: 分类算法（对整图进行分类）
        std::vector<DetectObject> classResults;
        mAlgorithms.classification->objectDetect(image, classResults, mControl->confThresh, mControl->nmsThresh);

        if (classResults.empty()) {
            return true;  // 无分类结果
        }

        // Step 2: 行为算法（判断分类结果是否匹配目标）
        for (auto& detect : classResults) {
            if (pipelineDetectMatchesObjectCode(mControl, detect)) {
                detect.happen = true;
                happen = true;
                happenScore = detect.class_score;
                happenDetects.push_back(detect);
                LOGI("Pipeline Mode 4: Image classified as: %s (%.2f)",
                     detect.class_name.c_str(), detect.class_score);
            }
        }

        return true;
    }

    // 模式 5：行为（直接 API）
    bool Analyzer::executePipelineMode5(int64_t frameCount, const cv::Mat& image, std::vector<DetectObject>& happenDetects, bool& happen, float& happenScore) {
        happenDetects.clear();
        happen = false;
        happenScore = 0.0;

        // v4.21: 行为算法 APIv2（混合模式）
        // - APIv1: API 直接输出 happen/happenScore + detects
        // - APIv2: API 输出 detects（原始检测结果），Analyzer 使用内置行为规则计算 happen（例如 intrusion/crowd/crossing/loitering）
        const BehaviorApiConfig& behaviorApiCfg =
            mTrackingState.behaviorApiConfigCache.get(mControl->behaviorConfig, mControl->behaviorAlgorithmCode, mControl->objectCode);
        int apiVersion = behaviorApiCfg.apiVersion;

        const BuiltinBehaviorType builtinBehaviorType = behaviorApiCfg.builtinBehavior;
        const std::string builtinBehaviorName = builtinBehaviorTypeToString(builtinBehaviorType);
        const float regionIouThresh = behaviorApiCfg.regionIouThresh;
        const int crowdMinCount = behaviorApiCfg.crowdMinCount;
        const CountTriggerOp crowdTriggerOp = behaviorApiCfg.crowdTriggerOp;
        const int crowdMaxCount = behaviorApiCfg.crowdMaxCount;
        const int loiteringSeconds = behaviorApiCfg.loiteringSeconds;
        const bool debug = behaviorApiCfg.debug;

        // v4.643: record last behavior type for postprocess user_data.
        mPostprocessState.lastMode5ApiVersion = apiVersion;
        mPostprocessState.lastMode5BuiltinBehavior = builtinBehaviorType;

        if (builtinBehaviorType == BuiltinBehaviorType::Occlusion ||
            builtinBehaviorType == BuiltinBehaviorType::GrayScreen ||
            builtinBehaviorType == BuiltinBehaviorType::CorruptScreen) {
            Json::Value userData;
            happen = evaluateVideoQualityBehavior(image, builtinBehaviorName, happenDetects, userData);
            happenScore = happen ? 1.0f : 0.0f;
            mPostprocessState.lastUserData = userData;
            LOGI("Pipeline Mode 5(local:%s): happen=%d detects=%zu",
                 builtinBehaviorName.c_str(),
                 happen,
                 happenDetects.size());
            return true;
        }

        // 模式 5：行为算法（直接 API）
        if (mControl->behaviorApiUrl.empty()) {
            LOGE("Pipeline Mode 5: Behavior API URL not configured");
            return false;
        }

        // 准备请求数据（复用缓冲区）
        mApiState.jpegBuffer.clear();
        cv::imencode(".jpg", image, mApiState.jpegBuffer, mApiState.jpegParams);

        if (mApiState.jpegBuffer.empty()) {
            LOGE("Pipeline Mode 5: Failed to encode image");
            return false;
        }

        Base64 base64;
        mApiState.imageBase64.clear();
        base64.encode(mApiState.jpegBuffer.data(), mApiState.jpegBuffer.size(), mApiState.imageBase64);

        BehaviorApiPayloadInput payloadInput;
        payloadInput.imageBase64 = mApiState.imageBase64;
	        const Config* config = mScheduler ? mScheduler->getConfig() : nullptr;
        payloadInput.stream.nodeCode = config ? config->code : "";
        payloadInput.stream.controlCode = mControl->code;
        payloadInput.stream.streamCode = mControl->streamCode;
        payloadInput.stream.streamApp = mControl->streamApp;
        payloadInput.stream.streamName = mControl->streamName;
        payloadInput.stream.pipelineMode = 5;

        payloadInput.behavior.algorithmCode = mControl->behaviorAlgorithmCode;
        payloadInput.behavior.config = mControl->behaviorConfig;
        payloadInput.behavior.recognitionRegion = mControl->recognitionRegion;
        payloadInput.behavior.detectClassNames = mControl->objectCode;

        payloadInput.video.width = mControl->videoWidth;
        payloadInput.video.height = mControl->videoHeight;
        payloadInput.video.fps = mControl->videoFps;

        payloadInput.osd.enabled = mControl->osdEnabled;
        payloadInput.osd.text = mControl->osdText;
        payloadInput.osd.position = mControl->osdPosition;
        payloadInput.osd.x = mControl->osdX;
        payloadInput.osd.y = mControl->osdY;
        payloadInput.osd.fontSize = mControl->osdFontSize;
        payloadInput.osd.fontColor = mControl->osdFontColor;
        payloadInput.osd.bgEnabled = mControl->osdBgEnabled;

        payloadInput.extensions.drawType = mControl->drawType;
        payloadInput.extensions.frameId = frameCount;
        payloadInput.extensions.timestampMs = getCurTime();

        // v4.726: APIv3 supports uploading both full image and an ROI crop image (best-effort).
        payloadInput.roi.imageBase64 = "";
        payloadInput.roi.x1 = 0;
        payloadInput.roi.y1 = 0;
        payloadInput.roi.x2 = 0;
        payloadInput.roi.y2 = 0;
        if (apiVersion == 3) {
            int minX = image.cols;
            int minY = image.rows;
            int maxX = -1;
            int maxY = -1;
            bool hasPts = false;
            auto considerPts = [&](const std::vector<cv::Point>& pts) {
                for (const auto& p : pts) {
                    minX = std::min(minX, p.x);
                    minY = std::min(minY, p.y);
                    maxX = std::max(maxX, p.x);
                    maxY = std::max(maxY, p.y);
                    hasPts = true;
                }
            };
            if (mControl) {
                if (!mControl->recognitionRegions_points.empty()) {
                    for (const auto& pts : mControl->recognitionRegions_points) {
                        considerPts(pts);
                    }
                } else if (!mControl->recognitionRegion_points.empty()) {
                    considerPts(mControl->recognitionRegion_points);
                }
            }

            if (hasPts && image.cols > 0 && image.rows > 0) {
                int x1 = std::max(0, std::min(minX, image.cols - 1));
                int y1 = std::max(0, std::min(minY, image.rows - 1));
                int x2 = std::max(x1 + 1, std::min(image.cols, maxX + 1));
                int y2 = std::max(y1 + 1, std::min(image.rows, maxY + 1));

                cv::Rect roi(x1, y1, x2 - x1, y2 - y1);
                if (roi.width > 0 && roi.height > 0 &&
                    roi.x >= 0 && roi.y >= 0 &&
                    roi.x + roi.width <= image.cols &&
                    roi.y + roi.height <= image.rows) {
                    payloadInput.roi.x1 = x1;
                    payloadInput.roi.y1 = y1;
                    payloadInput.roi.x2 = x2;
                    payloadInput.roi.y2 = y2;

                    // Reuse JPEG buffer for ROI encoding.
                    mApiState.jpegBuffer.clear();
                    cv::imencode(".jpg", image(roi), mApiState.jpegBuffer, mApiState.jpegParams);
                    mApiState.roiImageBase64.clear();
                    if (!mApiState.jpegBuffer.empty()) {
                        base64.encode(mApiState.jpegBuffer.data(), mApiState.jpegBuffer.size(), mApiState.roiImageBase64);
                    }
                    payloadInput.roi.imageBase64 = mApiState.roiImageBase64;
                }
            }
        }

        std::string data;
        if (apiVersion == 3) {
            data = buildBehaviorApiPayloadV3JsonString(payloadInput);
        } else {
            data = buildBehaviorApiPayloadV2JsonString(payloadInput);
        }

        // 发送 HTTP POST 请求
        Request request;
        std::string response;
        bool apiOk = false;
        bool apiHappen = false;
        float apiHappenScore = 0.0f;
        bool apiHasHappen = false;
        std::vector<DetectObject> apiDetects;

        if (debug) {
            LOGI("Pipeline Mode 5(debug:%s): apiVersion=%d url=%s payloadBytes=%zu roi=%s",
                 builtinBehaviorName.c_str(),
                 apiVersion,
                 mControl->behaviorApiUrl.c_str(),
                 data.size(),
                 payloadInput.roi.imageBase64.empty() ? "no" : "yes");
        }
        const int64_t httpStartMs = getCurTime();
        if (!request.post(mControl->behaviorApiUrl.c_str(), data, response)) {
            if (debug) {
                const int64_t httpEndMs = getCurTime();
                LOGW("Pipeline Mode 5(debug:%s): HTTP POST failed latency=%lldms", builtinBehaviorName.c_str(), (long long)(httpEndMs - httpStartMs));
            }
            LOGE("Pipeline Mode 5: HTTP POST request failed");
            return true;  // best-effort: keep control running
        }
        if (debug) {
            const int64_t httpEndMs = getCurTime();
            LOGI("Pipeline Mode 5(debug:%s): HTTP OK latency=%lldms responseBytes=%zu", builtinBehaviorName.c_str(), (long long)(httpEndMs - httpStartMs), response.size());
        }

        Json::CharReaderBuilder builder;
        const std::unique_ptr<Json::CharReader> reader(builder.newCharReader());
        Json::Value root;
        JSONCPP_STRING errs;

        if (!reader->parse(response.data(), response.data() + response.size(), &root, &errs) || !errs.empty()) {
            LOGE("Pipeline Mode 5: Failed to parse API response JSON");
            return true;
        }

        if (!root["code"].isInt() || !root["msg"].isString()) {
            LOGE("Pipeline Mode 5: Incorrect API response format");
            return true;
        }

        const int code = root["code"].asInt();
        const std::string msg = root["msg"].asCString();
        if (code != 1000) {
            LOGE("Pipeline Mode 5: API error - code=%d, msg=%s", code, msg.data());
            return true;
        }

        const Json::Value result = root["result"];
        if (!result.isObject()) {
            LOGE("Pipeline Mode 5: Missing result object");
            return true;
        }

        // v4.7xx: optional user_data passthrough for alarm metadata/UI debug.
        // Example:
        //   {"code":1000,"msg":"ok","result":{"happen":true,"user_data":{"k":"v"}}}
        // Stored as Admin Alarm.metadata.user_data via Worker -> /alarm/openAdd.
        {
            Json::Value userData(Json::objectValue);
            if (extractBehaviorUserData(result, userData)) {
                mPostprocessState.lastUserData = userData;
            }
        }

        if (result["happen"].isBool()) {
            apiHappen = result["happen"].asBool();
            apiHasHappen = true;
        }
        if (result["happenScore"].isNumeric()) {
            apiHappenScore = result["happenScore"].asFloat();
        }

        const Json::Value result_detects = result["detects"];
        if (result_detects.isArray()) {
            apiDetects.reserve(result_detects.size());
            for (const auto& i : result_detects) {
                DetectObject detect;
                detect.x1 = i.get("x1", 0).asInt();
                detect.y1 = i.get("y1", 0).asInt();
                detect.x2 = i.get("x2", 0).asInt();
                detect.y2 = i.get("y2", 0).asInt();
                detect.class_score = i.get("class_score", 0.0).asFloat();
                detect.class_id = i.get("class_id", 0).asInt();
                detect.class_name = i.get("class_name", "").asString();
                detect.happen = i.get("happen", false).asBool();
                apiDetects.push_back(detect);
            }
        }

        apiOk = true;
        if (!apiOk) {
            return true;
        }

        // APIv1: API 直接返回 happen
        if (apiVersion != 2) {
            happenDetects = apiDetects;
            happen = apiHasHappen ? apiHappen : false;
            happenScore = apiHappenScore;
            LOGI("Pipeline Mode 5(v1): happen=%d score=%.2f detects=%zu", happen, happenScore, happenDetects.size());
            return true;
        }

        // APIv2: API 返回 detects，Analyzer 做内置行为判定
        const std::vector<std::string>& targetsLower = behaviorApiCfg.targetsLower;
        auto match_target = [&](const std::string& className) {
            if (targetsLower.empty()) {
                return true;
            }
            const std::string v = to_lower_copy(className);
            for (const auto& t : targetsLower) {
                if (!t.empty() && v == t) {
                    return true;
                }
            }
            return false;
        };

        const bool hasRegion = (!mControl->recognitionRegions_d.empty()) || (mControl->recognitionRegion_d.size() >= 6);
        const bool isSuper = (builtinBehaviorType == BuiltinBehaviorType::Super);
        const float superCenterX = behaviorApiCfg.centerPointX;
        const float superCenterY = behaviorApiCfg.centerPointY;

        auto is_in_region_iou = [&](const DetectObject& detect) {
            if (!hasRegion) {
                return true;
            }
            const double iou = calcRecognitionCoverageRatio(mControl, detect);
            return iou >= static_cast<double>(regionIouThresh);
        };

        // Common filter: class + region
        std::vector<DetectObject> filtered;
        filtered.reserve(apiDetects.size());
        for (auto d : apiDetects) {
            if (!match_target(d.class_name)) {
                continue;
            }

            if (hasRegion) {
                if (isSuper) {
                    const auto bx = static_cast<float>(d.x1);
                    const auto by = static_cast<float>(d.y1);
                    const auto bw = static_cast<float>(d.x2 - d.x1);
                    const auto bh = static_cast<float>(d.y2 - d.y1);
                    const float px = bx + bw * superCenterX;
                    const float py = by + bh * superCenterY;
                    const int ridx = findRecognitionRegionIndex(mControl, hasRegion, px, py);
                    if (ridx < 0) {
                        continue;
                    }
                    d.attributes["center_x"] = px;
                    d.attributes["center_y"] = py;
                    d.attributes["region_index"] = static_cast<float>(ridx);
                } else {
                    if (!is_in_region_iou(d)) {
                        continue;
                    }
                }
            }

            const int w = d.x2 - d.x1;
            const int h = d.y2 - d.y1;
            if (!passTargetSizeFilter(mPostprocessState.targetSizeFilterConfig, w, h, image.cols, image.rows)) {
                continue;
            }
            d.happen = true;
            filtered.push_back(d);
        }

        happenDetects.clear();
        happen = false;
        happenScore = 0.0f;

        if (builtinBehaviorType == BuiltinBehaviorType::Absence || builtinBehaviorType == BuiltinBehaviorType::Unattended) {
            // Absence/unattended: treat "no target detected" as raw happen.
            // Multi-region: gate each region independently and output region_index (0-based).
            if (mPostprocessState.usePerRegionBehaviorEventPostprocess && mControl && mControl->recognitionRegions_d.size() > 1) {
                const int64_t nowMs = getCurTime();
                const auto& regions = mControl->recognitionRegions_d;

                std::vector<bool> regionEmpty(regions.size(), true);

                for (const auto& d : apiDetects) {
                    if (!match_target(d.class_name)) {
                        continue;
                    }
                    const std::vector<double> object_d = detectObjectToPolygonPixels(d);

                    for (size_t i = 0; i < regions.size(); ++i) {
                        if (!regionEmpty[i]) {
                            continue;
                        }
                        const double ratio = CalcuPolygonIOU(regions[i], object_d);
                        if (ratio >= static_cast<double>(regionIouThresh)) {
                            regionEmpty[i] = false;
                        }
                    }

                    bool anyEmpty = false;
                    for (bool e : regionEmpty) {
                        if (e) {
                            anyEmpty = true;
                            break;
                        }
                    }
                    if (!anyEmpty) {
                        break;
                    }
                }

                const int idx = mPostprocessState.perRegionBehaviorEventPostprocess.update(regionEmpty, nowMs);
                happen = (idx >= 0);
                happenScore = happen ? 1.0f : 0.0f;
                mPostprocessState.lastRegionIndex = idx;
                happenDetects.clear(); // no bbox to report when absent

                if (happen) {
                    const int64_t durMs = mPostprocessState.perRegionBehaviorEventPostprocess.activeDurationMs(static_cast<size_t>(idx), nowMs);
                    Json::Value ud(Json::objectValue);
                    ud["behavior"] = builtinBehaviorName;
                    ud["event"] = (builtinBehaviorType == BuiltinBehaviorType::Unattended) ? "LEAVE" : "NOONE";
                    ud["region_index"] = idx;
                    ud["trigger_duration_ms"] = (Json::Int64)std::max<int64_t>(0, durMs);
	                    ud["trigger_duration_seconds"] = durMs > 0 ? (static_cast<double>(durMs) / 1000.0) : 0.0;
                    mPostprocessState.lastUserData = ud;
                }

                LOGI("Pipeline Mode 5(v2:%s): happen=%d region_index=%d regions=%zu targets=%zu",
                     builtinBehaviorName.c_str(), happen, idx, regions.size(), targetsLower.size());
                return true;
            }

            happen = filtered.empty();
            happenScore = happen ? 1.0f : 0.0f;
            // No bbox to report when absent.
            happenDetects.clear();
            if (hasRegion) {
                mPostprocessState.lastRegionIndex = happen ? 0 : -1;
            }
            LOGI("Pipeline Mode 5(v2:%s): happen=%d targets=%zu", builtinBehaviorName.c_str(), happen, targetsLower.size());
            return true;
        }

        if (builtinBehaviorType == BuiltinBehaviorType::Crowd) {
            happenDetects = filtered;
            const auto count = static_cast<int>(filtered.size());
            if (crowdTriggerOp == CountTriggerOp::LE) {
                const int maxCount = std::max(0, crowdMaxCount);
                happen = count <= maxCount;
                happenScore = happen ? 1.0f : 0.0f;
                LOGI("Pipeline Mode 5(v2:crowd<=): happen=%d count=%d max=%d", happen, count, maxCount);
                return true;
            }

            int minCount = crowdMinCount;
            if (minCount < 1) minCount = 1;
            happen = count >= minCount;
            happenScore = happen ? 1.0f : 0.0f;
            LOGI("Pipeline Mode 5(v2:crowd>=): happen=%d count=%d min=%d", happen, count, minCount);
            return true;
        }

        if (builtinBehaviorType == BuiltinBehaviorType::CrossCount) {
            // CrossCount: line crossing events (counted per unique track_id; best-effort filter duplicates).
            // This is similar to Crossing but uses a stricter per-frame de-dup to avoid repeated warnings.
            if (mControl->lineCoordinates.empty() || mControl->videoWidth <= 0 || mControl->videoHeight <= 0) {
                LOGE("Pipeline Mode 5(v2:crosscount): lineCoordinates/video size not configured");
                return true;
            }

            if (!mTrackingState.behaviorApiV2Tracker) {
                mTrackingState.behaviorApiV2Tracker = std::make_unique<SimpleTracker>(0.3f, 30, 50);
            }
            if (!mTrackingState.behaviorApiV2LineCrossing) {
                mTrackingState.behaviorApiV2LineCrossing = std::make_unique<LineCrossingDetector>();
                mTrackingState.behaviorApiV2LineInited = false;
            }

            if (!mTrackingState.behaviorApiV2LineInited) {
                Line line = Line::fromString(mControl->lineCoordinates, mControl->videoWidth, mControl->videoHeight);
                std::vector<Line> lines;
                lines.push_back(line);
                mTrackingState.behaviorApiV2LineCrossing->setLines(lines);

                const std::string dir = to_lower_copy(mControl->lineViolationDirection);
                if (dir == "forward") {
                    mTrackingState.behaviorApiV2LineCrossing->setViolationDirection(line.name.empty() ? "line" : line.name, CrossDirection::Forward);
                } else if (dir == "backward") {
                    mTrackingState.behaviorApiV2LineCrossing->setViolationDirection(line.name.empty() ? "line" : line.name, CrossDirection::Backward);
                }
                mTrackingState.behaviorApiV2LineInited = true;
            }

            const int64_t nowMs = getCurTime();
            const std::vector<TrackedObject> tracks = mTrackingState.behaviorApiV2Tracker->update(filtered, nowMs);
            const std::vector<LineCrossingEvent> events = mTrackingState.behaviorApiV2LineCrossing->detectCrossing(tracks, nowMs);

            const std::string vdir = to_lower_copy(mControl->lineViolationDirection);
            const bool requireViolation = (vdir == "forward" || vdir == "backward");

            happenDetects.clear();
            std::unordered_set<int> seenTrackIds;
            seenTrackIds.reserve(events.size());

            for (const auto& ev : events) {
                if (requireViolation && !ev.isViolation) {
                    continue;
                }
                if (ev.trackId <= 0) {
                    continue;
                }
                if (seenTrackIds.count(ev.trackId) > 0) {
                    continue;  // filter duplicates by track_id
                }
                seenTrackIds.insert(ev.trackId);

                DetectObject d = ev.object;
                d.happen = true;
                d.attributes["track_id"] = static_cast<float>(ev.trackId);
                happenDetects.push_back(d);
            }

            happen = !happenDetects.empty();
            happenScore = happen ? 1.0f : 0.0f;

            if (happen) {
                Json::Value internal(Json::arrayValue);
                for (const auto& d : happenDetects) {
                    int tid = 0;
                    auto itTid = d.attributes.find("track_id");
                    if (itTid != d.attributes.end()) {
                        tid = static_cast<int>(itTid->second);
                    }
                    Json::Value item(Json::objectValue);
                    item["track_id"] = tid;
                    internal.append(item);
                }

                Json::Value ud(Json::objectValue);
                ud["behavior"] = builtinBehaviorName;
                ud["event"] = "CROSSCOUNT";
                ud["cross_count"] = static_cast<int>(happenDetects.size());
                ud["internal_targets"] = internal;
                mPostprocessState.lastUserData = ud;
            }

            LOGI("Pipeline Mode 5(v2:crosscount): happen=%d events=%zu unique=%zu",
                 happen, events.size(), happenDetects.size());
            return true;
        }

        if (builtinBehaviorType == BuiltinBehaviorType::Crossing) {
            // Line crossing needs tracking + lineCoordinates.
            if (mControl->lineCoordinates.empty() || mControl->videoWidth <= 0 || mControl->videoHeight <= 0) {
                LOGE("Pipeline Mode 5(v2:crossing): lineCoordinates/video size not configured");
                return true;
            }

            if (!mTrackingState.behaviorApiV2Tracker) {
                mTrackingState.behaviorApiV2Tracker = std::make_unique<SimpleTracker>(0.3f, 30, 50);
            }
            if (!mTrackingState.behaviorApiV2LineCrossing) {
                mTrackingState.behaviorApiV2LineCrossing = std::make_unique<LineCrossingDetector>();
                mTrackingState.behaviorApiV2LineInited = false;
            }

            if (!mTrackingState.behaviorApiV2LineInited) {
                Line line = Line::fromString(mControl->lineCoordinates, mControl->videoWidth, mControl->videoHeight);
                std::vector<Line> lines;
                lines.push_back(line);
                mTrackingState.behaviorApiV2LineCrossing->setLines(lines);

                const std::string dir = to_lower_copy(mControl->lineViolationDirection);
                if (dir == "forward") {
                    mTrackingState.behaviorApiV2LineCrossing->setViolationDirection(line.name.empty() ? "line" : line.name, CrossDirection::Forward);
                } else if (dir == "backward") {
                    mTrackingState.behaviorApiV2LineCrossing->setViolationDirection(line.name.empty() ? "line" : line.name, CrossDirection::Backward);
                }
                mTrackingState.behaviorApiV2LineInited = true;
            }

            const int64_t nowMs = getCurTime();
            const std::vector<TrackedObject> tracks = mTrackingState.behaviorApiV2Tracker->update(filtered, nowMs);
            const std::vector<LineCrossingEvent> events = mTrackingState.behaviorApiV2LineCrossing->detectCrossing(tracks, nowMs);

            const std::string vdir = to_lower_copy(mControl->lineViolationDirection);
            const bool requireViolation = (vdir == "forward" || vdir == "backward");

            happenDetects.clear();
            for (const auto& ev : events) {
                if (requireViolation && !ev.isViolation) {
                    continue;
                }
                DetectObject d = ev.object;
                d.happen = true;
                d.attributes["track_id"] = static_cast<float>(ev.trackId);
                happenDetects.push_back(d);
            }
            happen = !happenDetects.empty();
            happenScore = happen ? 1.0f : 0.0f;
            LOGI("Pipeline Mode 5(v2:crossing): happen=%d events=%zu", happen, happenDetects.size());
            return true;
        }

        if (builtinBehaviorType == BuiltinBehaviorType::Motion) {
            if (!mTrackingState.behaviorApiV2Tracker) {
                mTrackingState.behaviorApiV2Tracker = std::make_unique<SimpleTracker>(0.3f, 30, 50);
            }

            const int64_t nowMs = getCurTime();
            const std::vector<TrackedObject> tracks = mTrackingState.behaviorApiV2Tracker->update(filtered, nowMs);
            happen = evaluateMotionBehavior(
                tracks,
                static_cast<float>(behaviorApiCfg.motionMinDisplacement),
                behaviorApiCfg.motionEventName,
                happenDetects,
                mPostprocessState.lastUserData);
            happenScore = happen ? 1.0f : 0.0f;
            LOGI("Pipeline Mode 5(v2:motion): happen=%d tracks=%zu thresholdPx=%d",
                 happen,
                 happenDetects.size(),
                 behaviorApiCfg.motionMinDisplacement);
            return true;
        }

        if (builtinBehaviorType == BuiltinBehaviorType::Loitering) {
            if (!mTrackingState.behaviorApiV2Tracker) {
                mTrackingState.behaviorApiV2Tracker = std::make_unique<SimpleTracker>(0.3f, 30, 50);
            }

            int seconds = loiteringSeconds;
            if (seconds < 1) seconds = 1;
            if (seconds > 3600) seconds = 3600;
            const int fps = (mControl->videoFps > 0) ? mControl->videoFps : 25;
            const int thresholdFrames = std::max(1, seconds * std::max(1, fps));

            const int64_t nowMs = getCurTime();
            const std::vector<TrackedObject> tracks = mTrackingState.behaviorApiV2Tracker->update(filtered, nowMs);

            std::unordered_set<int> seen;
            for (const auto& tr : tracks) {
                const int tid = tr.trackId;
                if (tid <= 0) {
                    continue;
                }
                seen.insert(tid);
                bool inRegion = true;
                if (hasRegion) {
                    inRegion = is_in_region_iou(tr.detection);
                }
                if (inRegion) {
                    mTrackingState.behaviorApiV2LoiteringFrames[tid] += 1;
                } else {
                    mTrackingState.behaviorApiV2LoiteringFrames[tid] = 0;
                }
            }
            // Drop stale track ids to keep memory bounded.
            for (auto it = mTrackingState.behaviorApiV2LoiteringFrames.begin(); it != mTrackingState.behaviorApiV2LoiteringFrames.end(); ) {
                if (seen.count(it->first) == 0) {
                    it = mTrackingState.behaviorApiV2LoiteringFrames.erase(it);
                } else {
                    ++it;
                }
            }

            happenDetects.clear();
            for (const auto& tr : tracks) {
                const int tid = tr.trackId;
                if (tid <= 0) continue;
                const auto it = mTrackingState.behaviorApiV2LoiteringFrames.find(tid);
                const int frames = (it == mTrackingState.behaviorApiV2LoiteringFrames.end()) ? 0 : it->second;
                if (frames >= thresholdFrames) {
                    DetectObject d = tr.detection;
                    d.happen = true;
                    d.attributes["track_id"] = static_cast<float>(tid);
                    d.attributes["loiter_frames"] = static_cast<float>(frames);
                    happenDetects.push_back(d);
                }
            }

            happen = !happenDetects.empty();
            happenScore = happen ? 1.0f : 0.0f;

            if (happen) {
                const int outputFps = (mControl->videoFps > 0) ? mControl->videoFps : 25;
                int bestTid = 0;
                int bestFrames = 0;
                Json::Value internal(Json::arrayValue);

                for (const auto& d : happenDetects) {
                    int tid = 0;
                    int frames = 0;
                    auto itTid = d.attributes.find("track_id");
                    if (itTid != d.attributes.end()) {
                        tid = static_cast<int>(itTid->second);
                    }
                    auto itFrames = d.attributes.find("loiter_frames");
                    if (itFrames != d.attributes.end()) {
                        frames = static_cast<int>(itFrames->second);
                    }

                    Json::Value item(Json::objectValue);
                    item["track_id"] = tid;
                    item["duration_frames"] = frames;
                    internal.append(item);

                    if (frames > bestFrames) {
                        bestFrames = frames;
                        bestTid = tid;
                    }
                }

                Json::Value ud(Json::objectValue);
                ud["behavior"] = builtinBehaviorName;
                ud["event"] = "STAY";
                ud["track_id"] = bestTid;
                ud["trigger_duration_frames"] = bestFrames;
                ud["trigger_duration_seconds"] = (outputFps > 0) ? (bestFrames / static_cast<double>(outputFps)) : 0.0;
                ud["internal_targets"] = internal;
                mPostprocessState.lastUserData = ud;
            }

            LOGI("Pipeline Mode 5(v2:loitering): happen=%d tracks=%zu thresholdFrames=%d", happen, happenDetects.size(), thresholdFrames);
            return true;
        }

        // Default: intrusion-like (targets inside region)
        happenDetects = filtered;
        happen = !happenDetects.empty();
        if (happen) {
            float best = 0.0f;
            for (const auto& d : happenDetects) {
                if (d.class_score > best) best = d.class_score;
            }
            happenScore = (best > 0.0f) ? best : 1.0f;

            if (isSuper) {
                // Extend user_data for SUPER to help downstream debugging / auditing.
                // - center_point_ratio_*: how the "center point" is selected inside bbox
                // - center_x/center_y: selected point in pixels (best-scoring target)
                // - region_index: which configured region was hit (0-based; -1 when unknown)
                int bestRegionIndex = -1;
                float bestCx = 0.0f;
                float bestCy = 0.0f;
                float bestScore = -1.0f;
                for (const auto& d : happenDetects) {
                    if (d.class_score >= bestScore) {
                        bestScore = d.class_score;
                        auto itRx = d.attributes.find("region_index");
                        if (itRx != d.attributes.end()) {
                            bestRegionIndex = static_cast<int>(itRx->second);
                        }
                        auto itCx = d.attributes.find("center_x");
                        if (itCx != d.attributes.end()) {
                            bestCx = itCx->second;
                        }
                        auto itCy = d.attributes.find("center_y");
                        if (itCy != d.attributes.end()) {
                            bestCy = itCy->second;
                        }
                    }
                }

                Json::Value ud = mPostprocessState.lastUserData;
                if (!ud.isObject()) {
                    ud = Json::Value(Json::objectValue);
                }
                ud["behavior"] = builtinBehaviorName;
                ud["event"] = "SUPER";
                ud["center_point_ratio_x"] = superCenterX;
                ud["center_point_ratio_y"] = superCenterY;
                ud["center_x"] = bestCx;
                ud["center_y"] = bestCy;
                ud["region_index"] = bestRegionIndex;
                ud["count"] = static_cast<int>(happenDetects.size());
                mPostprocessState.lastUserData = ud;

                if (bestRegionIndex >= 0) {
                    mPostprocessState.lastRegionIndex = bestRegionIndex;
                }
            }
        }
	        LOGI("Pipeline Mode 5(v2:%s): happen=%d detects=%zu", builtinBehaviorName.c_str(), happen, happenDetects.size());
	        return true;
	    }

	    // 模式 6：分类 >> 检测 >> 行为
	    bool Analyzer::executePipelineMode6(int64_t /*frameCount*/, cv::Mat& image, std::vector<DetectObject>& happenDetects, bool& happen, float& happenScore) {
	        return runPipelineMode6(mControl, mAlgorithms.classification, mAlgorithms.primary, image, happenDetects, happen, happenScore);
	    }

	    // 模式 7：检测 >> 分类 >> 特征 >> 行为
	    bool Analyzer::executePipelineMode7(int64_t /*frameCount*/, cv::Mat& image, std::vector<DetectObject>& happenDetects, bool& happen, float& happenScore) {
	        Json::Value userData(Json::objectValue);
	        const bool ok = runPipelineMode7(
	            mControl,
	            mAlgorithms.primary,
	            mAlgorithms.classification,
	            mAlgorithms.feature,
	            image,
	            happenDetects,
	            happen,
	            happenScore,
	            mScheduler ? mScheduler->getFaceDb() : nullptr,
	            &userData);
	        if (ok) {
	            mPostprocessState.lastUserData = userData;
	        }
	        return ok;
	    }

	    // 模式 8：检测 >> 检测 >> 行为
	    bool Analyzer::executePipelineMode8(int64_t /*frameCount*/, cv::Mat& image, std::vector<DetectObject>& happenDetects, bool& happen, float& happenScore) {
	        // v4.724/v4.725: mode8 支持：
	        // - 可配置 detect1Enabled/detect2Enabled + AND/OR
	        // - 第二步检测可配置输入 ROI 或 full-image
        //
        // 工业降级：特征/第二步检测不可用时，不崩溃，尽量回退到可用链路。
        return runPipelineMode8(mControl, mAlgorithms.primary, mAlgorithms.secondary, image, happenDetects, happen, happenScore);
    }

    // 模式 9：检测 >> 特征 >> 检测 >> 行为
    bool Analyzer::executePipelineMode9(int64_t /*frameCount*/, cv::Mat& image, std::vector<DetectObject>& happenDetects, bool& happen, float& happenScore) {
        Json::Value userData(Json::objectValue);
        const bool ok = runPipelineMode9(
            mControl,
            mAlgorithms.primary,
            mAlgorithms.feature,
            mAlgorithms.secondary,
            image,
            happenDetects,
            happen,
            happenScore,
            mScheduler ? mScheduler->getFaceDb() : nullptr,
            &userData);
        if (ok) {
            mPostprocessState.lastUserData = userData;
        }
        return ok;
    }

    // ======================================

}
