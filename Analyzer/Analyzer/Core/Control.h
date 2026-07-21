#ifndef ANALYZER_CONTROL_H
#define ANALYZER_CONTROL_H

#include <string>
#include <vector>
#include <cmath>
#include <opencv2/opencv.hpp>
#include "Utils/Common.h"
#include "RecognitionRegions.h"

namespace AVSAnalyzer {

	struct ControlStreamSettings {
		std::string code;       // 布控编号
		std::string streamCode; // 视频流编号
		std::string streamApp;  // 视频流app
		std::string streamName; // 视频流name
		std::string streamUrl;  // 拉流地址
		bool pushStream = false;     // 是否推流
		std::string pushStreamUrl;   // 推流地址
		bool enableHardwareDecode = false; // 启用时才占用 maxHardwareDecodeChannels
		bool enableHardwareEncode = false; // 启用且 pushStream=true 时才占用 maxHardwareEncodeChannels
	};

	struct ControlAlgorithmSettings {
		std::string algorithmCode;  // 算法编号
		std::string api_url;        // 算法api接口地址
		std::string object_str;     // 当前算法支持的所有目标分类
		bool forceInferenceDevice = false; // 强制推理设备：设备不支持时拒绝启动（默认 false=工业降级）
		std::string requestedInferenceDevice; // 请求的基础算法推理设备
		std::string effectiveInferenceDevice; // 基础算法实际使用的推理设备
		bool inferenceDeviceDegraded = false;  // 基础算法是否发生设备降级
		std::string inferenceDeviceReason;     // 基础算法设备降级原因
		std::string algorithmInstanceKey = ""; // 内部模型实例 Key（按布控参数复用）：algorithmCode + precision + inputWxH
		std::vector<std::string> objects_v1;
		int objects_v1_len = 0;
		std::string objectCode; // 目标监测分类编号
	};

	struct ControlLicenseSettings {
		std::string licenseLeaseId{}; // 租约ID：由 Admin(LM) 返回；Control 运行期间需要定期续租，停止时释放
		int64_t licenseLastRenewOkTimestamp = 0; // 上一次续租成功的时间戳（毫秒，13位）
		int64_t licenseGraceUntilTimestamp = 0;  // 宽限期截止时间戳（毫秒，13位）；0 表示未进入宽限期
		bool licenseThreadPriorityEnabled = false;
		int licenseThreadPriorityStreamRank = 0;
		int licenseThreadPriorityFirstNActiveStreams = 0;
		int licenseThreadPriorityNiceValue = 0;
	};

	struct ControlModelSettings {
		std::string modelPrecision = "FP32"; // 模型精度: FP32/FP16/INT8
		int inputWidth = 640;                // 模型输入宽度
		int inputHeight = 640;               // 模型输入高度
		int modelConcurrency = 1;            // 模型并发实例数（>=1）
		float nmsThresh = 0.45f;             // NMS 阈值
		float confThresh = 0.25f;            // 置信度阈值
		int basicAlgoDetectMode = 0;         // 0=自由竞争（默认）, 1=固定间隔帧, 2=固定间隔秒
		int basicAlgoDetectInterval = 1;     // 间隔值（帧数或秒数，根据 mode 决定）
		int decodeStride = 1;                // 仅控制“解码”频率（而非推理）
		bool ffmpegSkipLoopFilter = false;
		bool ffmpegSkipIdct = false;
		int pullFrequency = 0;               // 0=disabled; >0 => decode/process at most N FPS
		int psEffectMinFps = 0;              // pushStream enabled 时有效 pull FPS 下限
	};

	struct ControlRecognitionSettings {
		std::string recognitionRegion;    // 算法识别区域坐标点 x1, y1, x2, y2, x3, y3, x4, y4
		std::vector<double> recognitionRegion_d;
		std::vector<cv::Point> recognitionRegion_points;
		std::vector<std::vector<double>> recognitionRegions_d;      // 每个 region: [x1,y1,x2,y2,...] 像素坐标
		std::vector<std::vector<cv::Point>> recognitionRegions_points; // 每个 region: 点列表（用于绘制）
		int64_t minInterval = 180000; // 布控最小的报警间隔时间（单位毫秒）
		float classThresh = 0.5f;     // 分类阈值
		float overlapThresh = 0.5f;   // NMS IOU 阈值
	};

	struct ControlAlarmSettings {
		std::string alarmVideoType = "mp4";       // 报警视频类型: mp4/ts/flv/none
		int alarmImageCount = 3;                  // 报警图片数量
		std::string alarmCoverPosition = "front"; // 报警封面(main.jpg)位置: front/middle/back/custom
		int alarmCoverCustomIndex = 0;            // 自定义封面帧序号（custom 时生效；0=默认策略）
		std::string alarmImageDrawMode = "boxed"; // 报警图片画框模式: boxed/clean/both
		bool forceFrameAlarm = false;             // 强制逐帧发送报警
	};

	struct ControlPushVideoSettings {
		std::string pushVideoCodec = "h264"; // 推流编码器: h264/h265/vp8/vp9
		int pushVideoBitrate = 2000;         // 推流码率 (kbps)
		int pushVideoFps = 25;               // 推流帧率 (fps)
		int pushVideoWidth = 1280;           // 推流宽度
		int pushVideoHeight = 720;           // 推流高度
		int pushVideoGop = 50;               // 关键帧间隔 (GOP)
	};

	struct ControlOsdSettings {
		bool osdEnabled = false;                  // 启用 OSD
		std::string osdText = "";                 // OSD 文字内容（支持中文、变量）
		std::string osdPosition = "top-left";     // OSD 位置
		int osdX = 10;                            // 自定义 X 坐标
		int osdY = 30;                            // 自定义 Y 坐标
		int osdFontSize = 24;                     // 字体大小
		std::string osdFontColor = "255,255,255"; // RGB 颜色
		bool osdBgEnabled = true;                 // 启用半透明背景
		int osdFontThickness = 2;                 // 字体厚度（OpenCV putText thickness）
		std::string osdImagePath = "";            // 贴图路径（png/jpg）；为空表示不贴图
		int osdImageX = 10;                       // 贴图左上角 X（像素）
		int osdImageY = 10;                       // 贴图左上角 Y（像素）
		float osdImageScale = 1.0f;               // 缩放倍数（>0）
		float osdImageAlpha = 1.0f;               // 全局透明度（0~1）
		int osdAlgoX = 20;                        // 算法名起点 X
		int osdAlgoY = 80;                        // 算法名起点 Y
		int osdFpsX = 20;                         // FPS 起点 X
		int osdFpsY = 140;                        // FPS 起点 Y
	};

	struct ControlOverlaySettings {
		std::string secondaryAlgorithmCode = "";   // 二级算法编号（可选）
		std::string secondaryApi_url = "";         // 二级算法 API 地址（可选）
		float secondaryConfThresh = 0.25f;         // 二级算法置信度阈值
		bool enableHierarchicalAlgorithm = false;  // 是否启用层级算法
		std::string drawType = "polygon";          // 绘制类型: polygon=多边形区域, line=越线检测
		std::string overlayRegionColor = "255,0,0";
		int overlayRegionThickness = 4;
		std::string overlayLineColor = "255,0,0";
		int overlayLineThickness = 4;
		std::string overlayDetectColor = "255,0,0";
		int overlayDetectThickness = 2;
		int overlayDetectFontSize = 48;            // 基准 24 => 48 ~ 2.0 scale
		std::string lineCoordinates = "";          // 越线检测线段坐标（格式：x1,y1,x2,y2，归一化坐标0-1）
		std::string lineViolationDirection = "both"; // 违规方向: both=双向, forward=正向, backward=反向
		bool enableTracking = false;               // 启用目标追踪（越线检测需要）
	};

	struct ControlPipelineSettings {
		bool usePipelineMode = false;               // 是否启用算法流程模式
		int algorithmPipelineMode = 1;              // 算法流程模式: 1-9
		std::string trackingAlgorithmCode = "";     // 追踪算法编号（模式 2）
		std::string classificationAlgorithmCode = ""; // 分类算法编号（模式 3、4）
		std::string featureAlgorithmCode = "";      // 特征算法编号（模式 9）
		std::string behaviorAlgorithmCode = "";     // 行为算法编号（所有模式）
		std::string behaviorApiUrl = "";            // 行为算法 API 地址（模式 5）
		std::string trackingConfig = "{}";          // 追踪算法配置（JSON 格式）
		std::string classificationConfig = "{}";    // 分类算法配置（JSON 格式）
		std::string featureConfig = "{}";           // 特征算法配置（JSON 格式，可选）
		std::string behaviorConfig = "{}";          // 行为算法配置（JSON 格式）
	};

	struct ControlRuntimeState {
		int64_t startTimestamp = 0; // 执行器启动时毫秒级时间戳（13位）
		float checkFps = 0;         // 算法检测的帧率（每秒检测的次数）
		int videoWidth = 0;         // 布控视频流的像素宽
		int videoHeight = 0;        // 布控视频流的像素高
		int videoChannel = 0;
		int videoIndex = -1;
		int videoFps = 0;
	};

	struct Control
		: public ControlStreamSettings,
		  public ControlAlgorithmSettings,
		  public ControlLicenseSettings,
		  public ControlModelSettings,
		  public ControlRecognitionSettings,
		  public ControlAlarmSettings,
		  public ControlPushVideoSettings,
		  public ControlOsdSettings,
		  public ControlOverlaySettings,
		  public ControlPipelineSettings,
		  public ControlRuntimeState
	{
		bool parseRecognitionRegion() {
			bool res = false;
			if (!recognitionRegions_points.empty()) {
				return true;
			}
			if (videoWidth <= 0 || videoHeight <= 0) {
				return false;
			}

			std::vector<std::vector<double>> regionsPixels;
			if (std::string err;
			    !parseRecognitionRegionsPixels(recognitionRegion, videoWidth, videoHeight, regionsPixels, err)) {
				return false;
			}

			recognitionRegions_d.clear();
			recognitionRegions_points.clear();
			recognitionRegion_d.clear();
			recognitionRegion_points.clear();

			for (const auto& region : regionsPixels) {
				if (region.size() < 6 || (region.size() % 2) != 0) {
					continue;
				}
				recognitionRegions_d.push_back(region);

				std::vector<cv::Point> pts;
				pts.reserve(region.size() / 2);
				for (size_t i = 0; i + 1 < region.size(); i += 2) {
					const auto x = static_cast<int>(std::lround(region[i]));
					const auto y = static_cast<int>(std::lround(region[i + 1]));
					pts.emplace_back(x, y);
				}
				if (pts.size() >= 3) {
					recognitionRegions_points.push_back(std::move(pts));
				}
			}

			if (!recognitionRegions_d.empty()) {
				recognitionRegion_d = recognitionRegions_d[0];
			}
			if (!recognitionRegions_points.empty()) {
				recognitionRegion_points = recognitionRegions_points[0];
			}

			res = !recognitionRegions_points.empty();
			return res;
		}

		bool validateAdd(std::string& result_msg) const {
			const bool isLineDraw = (drawType == "line");
			if (code.empty() || streamUrl.empty() || algorithmCode.empty() || objectCode.empty()) {
				result_msg = "validate parameter error";
				return false;
			}
			if (!isLineDraw && recognitionRegion.empty()) {
				result_msg = "validate parameter recognitionRegion is error";
				return false;
			}
			if (isLineDraw && lineCoordinates.empty()) {
				result_msg = "validate parameter lineCoordinates is error";
				return false;
			}
			if (pushStream && pushStreamUrl.empty()) {
				result_msg = "validate parameter pushStreamUrl is error: " + pushStreamUrl;
				return false;
			}
			result_msg = "validate success";
			return true;
		}

		bool validateCancel(std::string& result_msg) const {
			if (code.empty()) {
				result_msg = "validate parameter error";
				return false;
			}
			result_msg = "validate success";
			return true;
		}
	};
}
#endif //ANALYZER_CONTROL_H
