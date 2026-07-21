#include "Core/Config.h"
#include "Core/Scheduler.h"
#include "Core/Server.h"
#include "Core/Version.h"
#include "Core/Algorithm.h"
#include "Core/AlgorithmOnYolo.h"
#include <opencv2/opencv.hpp>
#include <filesystem>
#include <algorithm>
#include <cctype>
#include <cstring>
#include <chrono>
#include <new>
#include <memory>
#include <string_view>
#include <stdexcept>
using namespace AVSAnalyzer;

// ========== TensorRT 模型验证工具 ==========
namespace {
	std::string toUpper(std::string v) {
		std::transform(v.begin(), v.end(), v.begin(),
			[](unsigned char c) { return static_cast<char>(std::toupper(c)); });
		return v;
	}

		bool startsWith(std::string_view value, std::string_view prefix) {
			return value.rfind(prefix, 0) == 0;
		}
	}

int verifyModel(const char* modelPath, const char* testImage, bool benchmark, const char* requestedDevice) {
	printf("\n========== TensorRT Model Verification Tool ==========\n");
	printf("Model Path: %s\n", modelPath);
	const std::string device = (requestedDevice && std::strlen(requestedDevice) > 0) ? std::string(requestedDevice) : "AUTO";
	printf("Requested Device: %s\n", device.c_str());
	if (testImage) {
		printf("Test Image: %s\n", testImage);
	}
	if (benchmark) {
		printf("Benchmark Mode: Enabled\n");
	}
	printf("======================================================\n\n");

	// 1. 检查模型文件是否存在
	std::string modelPathStr(modelPath);
	if (!std::filesystem::exists(modelPathStr)) {
		printf("[ERROR] Model file not found: %s\n", modelPath);
		return -1;
	}
	printf("[OK] Model file exists\n");

	// 2. 打印当前 onnxruntime providers（便于定位 TRT/CUDA 不可用原因）
		try {
			std::vector<std::string> providers = Ort::GetAvailableProviders();
			printf("\n[INFO] Available onnxruntime providers:\n");
			for (size_t i = 0; i < providers.size(); ++i) {
				printf("  - %s\n", providers[i].c_str());
			}
		} catch (const Ort::Exception&) {
			printf("\n[WARN] Failed to query onnxruntime providers\n");
		}

	// 2. 尝试加载模型
	printf("\n[STEP 1] Loading model...\n");
	std::vector<std::string> classNames = { "person", "bicycle", "car" }; // 示例类别（不影响模型加载/验证）
	std::unique_ptr<OnnxRuntimeEngine> engine;
	try {
		engine = std::make_unique<OnnxRuntimeEngine>(/*config=*/nullptr, modelPathStr, classNames, device);
	}
		catch (const Ort::Exception& e) {
			printf("[ERROR] Failed to load model: %s\n", e.what());
			return -1;
		}
		catch (const std::bad_alloc& e) {
			printf("[ERROR] Failed to load model: %s\n", e.what());
			return -1;
		}
	if (!engine || !engine->isReady()) {
		printf("[ERROR] Model init failed\n");
		if (engine) {
			printf("[INFO] requested=%s:%d selected=%s\n",
				engine->getRequestedDevice().c_str(),
				engine->getRequestedDeviceId(),
				engine->getSelectedProvider().c_str());
			if (!engine->getTensorRTInitError().empty()) {
				printf("[INFO] tensorrt_error=%s\n", engine->getTensorRTInitError().c_str());
			}
				if (!engine->getCudaInitError().empty()) {
					printf("[INFO] cuda_error=%s\n", engine->getCudaInitError().c_str());
				}
			}
			return -1;
		}

	printf("[OK] Model initialized successfully\n");
	printf("[INFO] requested=%s:%d selected=%s\n",
		engine->getRequestedDevice().c_str(),
		engine->getRequestedDeviceId(),
		engine->getSelectedProvider().c_str());
	printf("[INFO] %s\n", engine->getPreprocessReport().c_str());
	if (!engine->getTensorRTInitError().empty()) {
		printf("[INFO] tensorrt_error=%s\n", engine->getTensorRTInitError().c_str());
	}
	if (!engine->getCudaInitError().empty()) {
		printf("[INFO] cuda_error=%s\n", engine->getCudaInitError().c_str());
	}

	// 若用户强制验证 TRT，则必须实际选中 TENSORRT provider
	const std::string deviceUpper = toUpper(device);
	const bool strictTrt = startsWith(deviceUpper, "TRT") || startsWith(deviceUpper, "TENSORRT");
	if (strictTrt && engine->getSelectedProvider() != "TENSORRT") {
		printf("[ERROR] Requested TensorRT but selected provider is: %s\n", engine->getSelectedProvider().c_str());
		return -2;
	}

	// 3. 如果提供测试图片，进行推理测试
		if (testImage && std::filesystem::exists(testImage)) {
			printf("\n[STEP 2] Running inference test...\n");
			cv::Mat image = cv::imread(testImage);
			if (image.empty()) {
				printf("[ERROR] Failed to load test image: %s\n", testImage);
				return -1;
			}
		printf("[OK] Test image loaded: %dx%d\n", image.cols, image.rows);

		std::vector<DetectObject> results;
		const float confThresh = 0.25f;
		const float nmsThresh = 0.45f;
		bool success = engine->runInference(image, results, confThresh, nmsThresh);
		if (success) {
			printf("[OK] Inference successful\n");
			printf("[RESULT] Detected %zu objects:\n", results.size());
			for (size_t i = 0; i < std::min(results.size(), size_t(10)); i++) {
				printf("  - Object %zu: class=%d(%s), score=%.2f, box=[%d,%d,%d,%d]\n",
					i,
					results[i].class_id, results[i].class_name.c_str(),
					results[i].class_score,
					results[i].x1, results[i].y1, results[i].x2, results[i].y2);
			}
			if (results.size() > 10) {
				printf("  ... and %zu more objects\n", results.size() - 10);
			}
		}
			else {
				printf("[ERROR] Inference failed\n");
				return -1;
			}

		// 4. 性能基准测试
		if (benchmark) {
			printf("\n[STEP 3] Running performance benchmark...\n");
			const int iterations = 100;
			auto start = std::chrono::high_resolution_clock::now();

			for (int i = 0; i < iterations; i++) {
				engine->runInference(image, results, confThresh, nmsThresh);
			}

			auto end = std::chrono::high_resolution_clock::now();
			auto duration = std::chrono::duration_cast<std::chrono::milliseconds>(end - start).count();
			double avgTime = static_cast<double>(duration) / iterations;
			double fps = 1000.0 / avgTime;

			printf("[RESULT] Performance metrics:\n");
			printf("  - Total iterations: %d\n", iterations);
			printf("  - Total time: %lld ms\n", static_cast<long long>(duration));
			printf("  - Average inference time: %.2f ms\n", avgTime);
			printf("  - Throughput: %.2f FPS\n", fps);
		}
	}
	else {
		printf("\n[SKIP] No test image provided or image not found\n");
		printf("[INFO] Model loaded successfully but not tested\n");
		if (benchmark) {
			printf("[WARN] --benchmark requires --test-image\n");
		}
	}

	printf("\n========== Verification Complete ==========\n");
	return 0;
}
// ==========================================

int main(int argc, char** argv)
{
#ifdef WIN32
	srand(time(nullptr));//时间初始化
#endif // WIN32

	const char* file = nullptr;
	const char* verifyModelPath = nullptr;
	const char* testImagePath = nullptr;
	const char* verifyDevice = nullptr;
	bool benchmarkMode = false;

	for (int i = 1; i < argc;)
	{
		if (argv[i][0] != '-')
		{
			printf("parameter error:%s\n", argv[i]);
			return -1;
		}

		std::string arg(argv[i++]);
		auto readNextValue = [&](const char** out) {
			if (i >= argc) {
				printf("parameter error: missing value for %s\n", arg.c_str());
				return false;
			}
			*out = argv[i++];
			return true;
		};
		if (arg == "-h" || arg == "--help") {
			//打印help信息
			printf("Analyzer %s - Video Analysis System\n\n", PROJECT_VERSION);
			printf("Usage:\n");
			printf("  Normal Mode:\n");
			printf("    -f <config_file>        配置文件路径\n");
			printf("\n");
			printf("  Verification Mode:\n");
			printf("    --verify-model <path>   验证 TensorRT 模型\n");
			printf("    --test-image <path>     测试图片路径（可选）\n");
			printf("    --device <device>       推理设备（可选）：AUTO/TRT/TRT:1/CUDA/CUDA:1/CPU\n");
			printf("    --benchmark             性能基准测试（需要 --test-image）\n");
			printf("\n");
			printf("Examples:\n");
			printf("  ./Analyzer -f config.json\n");
			printf("  ./Analyzer --verify-model model.onnx\n");
			printf("  ./Analyzer --verify-model model.onnx --test-image test.jpg\n");
			printf("  ./Analyzer --verify-model model.onnx --device TRT\n");
			printf("  ./Analyzer --verify-model model.onnx --test-image test.jpg --benchmark\n");
			return 0;
		}
		else if (arg == "-f") {
			if (!readNextValue(&file)) {
				return -1;
			}
		}
		else if (arg == "--verify-model") {
			if (!readNextValue(&verifyModelPath)) {
				return -1;
			}
		}
		else if (arg == "--test-image") {
			if (!readNextValue(&testImagePath)) {
				return -1;
			}
		}
		else if (arg == "--device") {
			if (!readNextValue(&verifyDevice)) {
				return -1;
			}
		}
		else if (arg == "--benchmark") {
			benchmarkMode = true;
		}
		else {
			printf("Unknown parameter: %s\n", arg.c_str());
			printf("Use -h or --help for usage information\n");
			return -1;
		}
	}

	// ========== 模型验证模式 ==========
	if (verifyModelPath) {
		return verifyModel(verifyModelPath, testImagePath, benchmarkMode, verifyDevice);
	}
	// ==================================

	if (file == nullptr) {
		printf("failed to read config file\n");
		printf("Use -h or --help for usage information\n");
		return -1;
	}

	Config config(file);
	if (!config.mState) {
		printf("failed to read config file: %s\n", file);
		return -1;
	}
	printf("Analyzer %s \n", PROJECT_VERSION);

	printf("\n");
	printf("请注意! config.json有涉及路径的字段，一定要在启动前修改成自己电脑的路径，否则程序一定会报错的，如果不知道config.json各个参数代表什么意思，请参考对应视频\n");
	printf("\n");

	Scheduler scheduler(&config);
	if (!scheduler.initAlgorithm()) {
		return -1;
	}
	Server server;
	server.start(&scheduler);
	scheduler.loop();

	return 0;
}
