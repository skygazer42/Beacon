from typing import Any, Dict, List, Optional


def _coco80_class_names() -> List[str]:
    # Keep in sync (best-effort) with Analyzer builtin COCO80 list in:
    # `Analyzer/Analyzer/Core/Scheduler.cpp` -> coco80ClassNames()
    """处理`coco80``class``names`。"""
    return [
        "person",
        "bicycle",
        "car",
        "motorcycle",
        "airplane",
        "bus",
        "train",
        "truck",
        "boat",
        "traffic light",
        "fire hydrant",
        "stop sign",
        "parking meter",
        "bench",
        "bird",
        "cat",
        "dog",
        "horse",
        "sheep",
        "cow",
        "elephant",
        "bear",
        "zebra",
        "giraffe",
        "backpack",
        "umbrella",
        "handbag",
        "tie",
        "suitcase",
        "frisbee",
        "skis",
        "snowboard",
        "sports ball",
        "kite",
        "baseball bat",
        "baseball glove",
        "skateboard",
        "surfboard",
        "tennis racket",
        "bottle",
        "wine glass",
        "cup",
        "fork",
        "knife",
        "spoon",
        "bowl",
        "banana",
        "apple",
        "sandwich",
        "orange",
        "broccoli",
        "carrot",
        "hot dog",
        "pizza",
        "donut",
        "cake",
        "chair",
        "couch",
        "potted plant",
        "bed",
        "dining table",
        "toilet",
        "tv",
        "laptop",
        "mouse",
        "remote",
        "keyboard",
        "cell phone",
        "microwave",
        "oven",
        "toaster",
        "sink",
        "refrigerator",
        "book",
        "clock",
        "vase",
        "scissors",
        "teddy bear",
        "hair drier",
        "toothbrush",
    ]


def list_builtin_algorithms() -> List[Dict[str, Any]]:
    """处理列表`builtin``algorithms`。
    
    Built-in algorithm catalog (best-effort) for:
        - SKU mapping (license_package)
        - Optional DB seeding (Admin AlgorithmModel templates)
    
        Note: Analyzer is the source-of-truth for what is actually loadable at runtime
        via `Scheduler::builtinMetas()`. This catalog is meant to reduce operational friction.
    """

    coco80 = _coco80_class_names()
    return [
        {
            "code": "on_yolov5s_80",
            "name": "YOLOv5s 通用检测（ONNX，80类）",
            "relative_model_path": "yolov5s.onnx",
            "object_names": coco80,
            "license_package": "core",
        },
        {
            "code": "ov_yolov5s_80",
            "name": "YOLOv5s 通用检测（OpenVINO，80类）",
            "relative_model_path": "yolov5s_ov_model/yolov5s.xml",
            "object_names": coco80,
            "license_package": "core",
        },
        {
            "code": "on_yolov8n_80",
            "name": "YOLOv8n 通用检测（ONNX，80类）",
            "relative_model_path": "yolov8n.onnx",
            "object_names": coco80,
            "license_package": "core",
        },
        {
            "code": "ov_yolov8n_80",
            "name": "YOLOv8n 通用检测（OpenVINO，80类）",
            "relative_model_path": "yolov8n_ov_model/yolov8n.xml",
            "object_names": coco80,
            "license_package": "core",
        },
        {
            "code": "on_yolov8s_80",
            "name": "YOLOv8s 通用检测（ONNX，80类）",
            "relative_model_path": "yolov8s.onnx",
            "object_names": coco80,
            "license_package": "core",
        },
        {
            "code": "ov_yolov8s_80",
            "name": "YOLOv8s 通用检测（OpenVINO，80类）",
            "relative_model_path": "yolov8s_ov_model/yolov8s.xml",
            "object_names": coco80,
            "license_package": "core",
        },
        {
            "code": "ov_yolov8n_fight_nofight",
            "name": "打架检测（OpenVINO）",
            "relative_model_path": "yolov8n_fight_nofight_ov_model/best.xml",
            "object_names": ["fight", "nofight"],
            "license_package": "behavior_pro",
        },
        {
            "code": "ov_yolov8n_fire_smoke",
            "name": "火焰烟雾检测（OpenVINO）",
            "relative_model_path": "yolov8n-fire-smoke_ov_model/yolov8n-fire-smoke.xml",
            "object_names": ["fire", "smoke"],
            "license_package": "core",
        },
        {
            "code": "ov_yolov8n_smoke",
            "name": "抽烟检测（OpenVINO）",
            "relative_model_path": "yolov8n-smoke_ov_model/best.xml",
            "object_names": ["smoke"],
            "license_package": "behavior_pro",
        },
        {
            "code": "ov_yolov11n_safehat",
            "name": "安全帽检测（OpenVINO）",
            "relative_model_path": "yolo11n_safehat_ov_model/best.xml",
            "object_names": ["head", "safehat"],
            "license_package": "ppe",
        },
        {
            "code": "ov_xcocr_plate",
            "name": "车牌识别（XcOCR，OpenVINO）",
            "relative_model_path": "xcocr_plate_ov_model/best.xml",
            # OCR 输出为“文本”，不适合把字符集塞进 object_str（会污染 UI）。
            # Admin 侧仅用一个逻辑目标占位；真实字符集由 Analyzer 内置/模型 labels 决定。
            "object_names": ["plate"],
            "algorithm_subtype": "ocr",
            "license_package": "traffic_lpr",
        },
        {
            "code": "on_xcocr_plate",
            "name": "车牌识别（XcOCR，ONNX/TensorRT）",
            "relative_model_path": "xcocr_plate.onnx",
            "object_names": ["plate"],
            "algorithm_subtype": "ocr",
            "license_package": "traffic_lpr",
        },
        {
            "code": "on_xcfacenet",
            "name": "人脸特征提取（XcFaceNet，ONNX）",
            "relative_model_path": "xcfacenet.onnx",
            "object_names": [],
            "algorithm_subtype": "tracking",
            "license_package": "core",
        },
        {
            "code": "ov_xcfacenet",
            "name": "人脸特征提取（XcFaceNet，OpenVINO）",
            "relative_model_path": "xcfacenet_ov_model/best.xml",
            "object_names": [],
            "algorithm_subtype": "tracking",
            "license_package": "core",
        },
    ]


def get_builtin_algorithm_meta(code: str) -> Optional[Dict[str, Any]]:
    """获取`builtin`算法元数据。"""
    target = str(code or "").strip()
    if not target:
        return None
    for meta in list_builtin_algorithms():
        if str(meta.get("code") or "").strip() == target:
            return meta
    return None


def get_builtin_algorithm_license_package(code: str) -> Optional[str]:
    """获取`builtin`算法授权打包。"""
    meta = get_builtin_algorithm_meta(code)
    if not meta:
        return None
    value = str(meta.get("license_package") or "").strip()
    return value or None
