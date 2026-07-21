#ifndef ANALYZER_CONFIG_H
#define ANALYZER_CONFIG_H

#include <string>
#include <vector>

namespace AVSAnalyzer {

	struct ConfigRuntimeState {
		bool mState = false;
		const char* file = nullptr;
	};

	struct ConfigEndpointSettings {
		std::string code{};          // v3.52新增，编号
		std::string host{};          // 主机IP地址 127.0.0.1
		std::string adminHost{};
		std::string licenseType{};   // community/machine/dongle/pool(manager)
		std::string licenseKey{};    // local machine license key
		std::string licenseDongleCmd{};   // local dongle probe command
		std::string licenseDongleFile{};  // local dongle sentinel file
		std::string openApiToken{};       // X-Beacon-Token for Analyzer open APIs (empty => localhost only)
		int adminPort = 0;
		int analyzerPort = 0;
		int mediaHttpPort = 0;
		int mediaRtspPort = 0;
	};

	struct ConfigStorageSettings {
		std::string uploadDir{};
		std::string modelDir{};
		std::string faceDefaultFeatureAlgorithmCode{}; // 人脸图片提特征时的默认算法编号（空=必须显式传入）
		bool modelEncrypt = false;                     // 模型是否加密
		std::string modelEncryptKey{};                 // 模型解密密钥（简单异或）
		std::string modelEncryptSuffix{ ".enc" };      // 加密文件后缀
		std::string modelDecryptDir{};                 // 解密缓存目录
		int modelCacheSeconds = 0;                     // 模型空闲缓存时长（秒）；0=引用为0时立刻卸载（非内置模型）
		int modelConcurrency = 1;                      // 基础算法模型并发实例数（>=1）
		std::string tensorrtEnginePluginPath{};        // TensorRT Engine 插件动态库路径（用于 .engine/.plan，空=禁用）
		std::string compatLibPath{};                   // 兼容算法动态库路径（国产硬件等），支持相对 config.json 目录或环境变量覆盖
		int rknpuPreprocessMode = 0;                   // 0=disabled, 1=adaptive, 2=stretch, 3=rga_stretch
	};

	struct ConfigAlarmSettings {
		int alarmQueueMaxSize = 5;
		int alarmPrefixFrames = 30;
		int alarmTotalFrames = 60;
		int alarmVideoSeconds = 0;          // 0=按帧数配置
		int alarmMergeWindowSeconds = 10;   // 连续触发合并窗口（秒）
		int alarmSegmentMaxSeconds = 60;    // 单段报警视频最大时长（秒）
		int alarmPushDelayMs = 0;           // 推送前延迟毫秒
		std::string alarmEncodeProfile{ "balanced" }; // 报警视频编码质量档位：balanced/high_quality/low_cpu
	};

	struct ConfigCapacitySettings {
		int maxHardwareDecodeChannels = 0;  // 最大硬件解码路数（0=不限制）
		int maxHardwareEncodeChannels = 0;  // 最大硬件编码路数（0=不限制）
		int maxControls = 20;               // 布控数量上限（资源自动调节的上限）
		int maxPendingControls = 2;         // 并发启动布控数量上限（防止批量启动时资源尖峰导致崩溃）
		int ffmpegDecodeThreadCount = 1;    // FFmpeg 解码线程数（0=使用默认值；大规模布控建议 1）
		int ffmpegEncodeThreadCount = 1;    // FFmpeg 编码线程数（0=使用默认值；大规模布控建议 1）
	};

	struct ConfigLicenseSettings {
		int licenseLeaseTtlSeconds = 120; // 租约 TTL（秒）；续租间隔由实现决定（通常 ttl/2）
		int licenseGraceSeconds = 600;    // LM 不可用时宽限期（秒）；0=无宽限（续租失败立即停止，不推荐）
	};

	struct ConfigHardwareCodecSettings {
		std::string hardwareDecoderType = "auto"; // 硬件解码器类型: auto/nvdec/qsv/videotoolbox/vaapi/none
		std::string hardwareEncoderType = "auto"; // 硬件编码器类型: auto/nvenc/qsv/videotoolbox/vaapi/none
		bool forceHardwareCodec = false;          // 强制使用硬件编解码（失败时不回退到软件）
		int hardwareCodecDeviceId = 0;            // 硬件设备ID（多GPU时使用，默认0）
	};

	struct ConfigApiInferSettings {
		int apiInferConnectTimeoutSeconds = 2;      // 连接超时（秒）
		int apiInferTimeoutSeconds = 5;             // 请求总超时（秒）
		int apiInferRetryMax = 0;                   // 失败重试次数（0=不重试）
		int apiInferCircuitBreakerFails = 5;        // 熔断阈值：连续失败次数（0=禁用）
		int apiInferCircuitBreakerOpenSeconds = 10; // 熔断打开时长（秒）
		int apiInferMinIntervalMs = 0;              // 最小调用间隔（ms，0=禁用）
	};

	class Config
		: public ConfigRuntimeState,
		  public ConfigEndpointSettings,
		  public ConfigStorageSettings,
		  public ConfigAlarmSettings,
		  public ConfigCapacitySettings,
		  public ConfigLicenseSettings,
		  public ConfigHardwareCodecSettings,
		  public ConfigApiInferSettings
	{
	public:
		explicit Config(const char* file);
		~Config();

		void show();
		std::string resolveFaceFeatureAlgorithmCode(const std::string& requestedCode) const;
	};
}
#endif //ANALYZER_CONFIG_H
