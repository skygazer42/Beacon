#ifndef ANALYZER_ALGORITHM_H
#define ANALYZER_ALGORITHM_H

#include <string>
#include <vector>
#include <array>
#include <map>
#include <algorithm>
#include <functional>
#include <opencv2/opencv.hpp>    //opencv header file

	namespace AVSAnalyzer {
	    class Config;

	    cv::Mat static letterbox(const cv::Mat& source)
	    {
	        int col = source.cols;
	        int row = source.rows;
        int _max = std::max(col, row);
        cv::Mat result = cv::Mat::zeros(_max, _max, CV_8UC3);
        source.copyTo(result(cv::Rect(0, 0, col, row)));
        return result;
    };

	struct DetectObject
	{
		int x1;
		int y1;
		int x2;
		int y2;
		float class_score;
        int class_id;
		std::string class_name;
        bool happen = false;

        // ========== 旋转框/多边形 (OBB) 支持 ==========
        // 当模型输出为旋转框（例如 YOLO-OBB）时，best-effort 透传 4 个角点。
        // 同时 x1/y1/x2/y2 仍会填充为外接矩形，便于兼容旧链路。
        bool hasObb = false;
        std::array<cv::Point2f, 4> obb{};
        // ==========================================

        // ========== 分割轮廓支持 ==========
        // 对于 YOLO seg 等实例分割模型，保存像素空间轮廓点。
        // bbox 仍继续作为兼容字段保留，方便旧链路回退。
        bool hasSegmentation = false;
        std::vector<cv::Point2f> segmentation;
        // ==========================================

        // ========== 层级算法支持 ==========
        // 支持二级算法结果（例如：检测后分类）
        std::vector<DetectObject> subObjects;  // 子算法检测结果
        std::string subAlgorithmCode;          // 子算法编号
        std::map<std::string, float, std::less<>> attributes;  // 额外属性（例如：age, gender, color等）
        // ====================================

        // ========== 姿态估计支持 ==========
        // 关键点数据结构：每个关键点包含 (x, y, confidence)
        struct Keypoint {
            float x;
            float y;
            float confidence;  // 置信度或可见性 (0-1)

            Keypoint() : x(0), y(0), confidence(0) {}
            Keypoint(float _x, float _y, float _conf) : x(_x), y(_y), confidence(_conf) {}
        };

        std::vector<Keypoint> keypoints;  // 关键点列表（例如：17个关键点用于人体姿态）
        bool hasPose = false;             // 是否包含姿态数据
        // ====================================
	};

    using DetectObjects = std::vector<DetectObject>;

    // 算法类型枚举
    enum class AlgorithmType {
        Detector,       // 检测算法（输出边界框）
        Classifier,     // 分类算法（输出类别标签）
        Recognizer,     // 识别算法（输出特征向量或ID）
        Tracker,        // 跟踪算法（输出带跟踪ID的目标）
        Attribute       // 属性分析算法（输出属性值）
    };

	    class Algorithm
	    {
	    public:
	        Algorithm() = delete;
	        explicit Algorithm(const Config* config);
	        virtual ~Algorithm();
        // 主检测接口（所有算法都需要实现）
        virtual bool objectDetect(cv::Mat &image, std::vector<DetectObject>& detects,
                                  float scoreThreshold, float nmsThreshold) = 0;

        // ========== 层级算法支持 ==========
        // 对检测区域进行二级处理（可选实现）
        virtual bool processRegion(cv::Mat& image, DetectObject& object,
                                   float scoreThreshold) {
            return true;  // 默认实现：不做处理
        }

        // 获取算法类型
        virtual AlgorithmType getType() const {
            return AlgorithmType::Detector;  // 默认为检测算法
        }

        // 是否支持区域处理
        virtual bool supportsRegionProcessing() const {
            return false;  // 默认不支持
        }

        // ========== Embedding / ReID 支持 ==========
        // 可选：用于“模型型追踪（ReID）”或特征提取（非检测输出）。
        // 默认实现：不支持。
        virtual bool extractEmbeddings(
            const std::vector<cv::Mat>& images,
            std::vector<std::vector<float>>& embeddings,
            std::string& errMsg
        ) {
            errMsg = "not supported";
            (void)images;
            embeddings.clear();
            return false;
        }

        virtual int embeddingDim() const {
            return 0;
        }
        // ==========================================
        // ====================================

        bool createState() const;

	    protected:
	        const Config* config() const { return mConfig; }
	        void setCreateState(bool value) { mCreateState = value; }

	    private:
	        const Config* mConfig;
	        bool mCreateState = false;//创建状态，默认false

    };

}
#endif //ANALYZER_ALGORITHM_H
