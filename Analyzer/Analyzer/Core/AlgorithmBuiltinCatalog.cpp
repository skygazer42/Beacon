#include "AlgorithmBuiltinCatalog.h"

namespace AVSAnalyzer {
namespace {

std::vector<std::string> coco80ClassNames() {
    return {
        "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light",
        "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
        "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
        "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard", "surfboard",
        "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
        "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
        "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard", "cell phone",
        "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
        "hair drier", "toothbrush"
    };
}

std::vector<std::string> xcocrPlateCharsetV1() {
    return {
        "京","津","沪","渝","冀","豫","云","辽","黑","湘","皖","鲁","新","苏","浙","赣","鄂","桂","甘","晋","蒙","陕","吉","闽","贵","粤","青","藏","川","宁","琼",
        "使","领","警","学","港","澳","挂","军","民","航","应","急",
        "·",
        "0","1","2","3","4","5","6","7","8","9",
        "A","B","C","D","E","F","G","H","J","K","L","M","N","P","Q","R","S","T","U","V","W","X","Y","Z",
    };
}

inline const std::vector<BuiltinAlgorithmMeta> kCatalog = {
    { "on_yolov5s_80", "yolov5s.onnx", coco80ClassNames(), BuiltinAlgorithmEngine::Onnx, "" },
    { "ov_yolov5s_80", "yolov5s_ov_model/yolov5s.xml", coco80ClassNames(), BuiltinAlgorithmEngine::OpenVino, "" },
    { "on_yolov8n_80", "yolov8n.onnx", coco80ClassNames(), BuiltinAlgorithmEngine::Onnx, "" },
    { "ov_yolov8n_80", "yolov8n_ov_model/yolov8n.xml", coco80ClassNames(), BuiltinAlgorithmEngine::OpenVino, "" },
    { "on_yolov8s_80", "yolov8s.onnx", coco80ClassNames(), BuiltinAlgorithmEngine::Onnx, "" },
    { "ov_yolov8s_80", "yolov8s_ov_model/yolov8s.xml", coco80ClassNames(), BuiltinAlgorithmEngine::OpenVino, "" },
    { "ov_yolov8n_fight_nofight", "yolov8n_fight_nofight_ov_model/best.xml", { "fight", "nofight" }, BuiltinAlgorithmEngine::OpenVino, "" },
    { "ov_yolov8n_fire_smoke", "yolov8n-fire-smoke_ov_model/yolov8n-fire-smoke.xml", { "fire", "smoke" }, BuiltinAlgorithmEngine::OpenVino, "" },
    { "ov_yolov8n_smoke", "yolov8n-smoke_ov_model/best.xml", { "smoke" }, BuiltinAlgorithmEngine::OpenVino, "" },
    { "ov_yolov11n_safehat", "yolo11n_safehat_ov_model/best.xml", { "head", "safehat" }, BuiltinAlgorithmEngine::OpenVino, "" },
    { "ov_xcocr_plate", "xcocr_plate_ov_model/best.xml", xcocrPlateCharsetV1(), BuiltinAlgorithmEngine::OpenVino, "ocr" },
    { "on_xcocr_plate", "xcocr_plate.onnx", xcocrPlateCharsetV1(), BuiltinAlgorithmEngine::Onnx, "ocr" },
    { "on_xcfacenet", "xcfacenet.onnx", {}, BuiltinAlgorithmEngine::Onnx, "tracking" },
    { "ov_xcfacenet", "xcfacenet_ov_model/best.xml", {}, BuiltinAlgorithmEngine::OpenVino, "tracking" },
};

} // namespace

const std::vector<BuiltinAlgorithmMeta>& builtin_algorithm_catalog() {
    return kCatalog;
}

const BuiltinAlgorithmMeta* find_builtin_algorithm_meta(std::string_view code) {
    for (const auto& meta : builtin_algorithm_catalog()) {
        if (std::string_view(meta.code) == code) {
            return &meta;
        }
    }
    return nullptr;
}

} // namespace AVSAnalyzer
