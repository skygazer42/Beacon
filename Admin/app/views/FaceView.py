from app.views.ViewsBase import g_config
from django.shortcuts import render

from app.models import AlgorithmModel
from app.utils.SystemConfigHelper import get_value


def index(request):
    """
    人脸管理页面

    - 人脸数据存储在 Analyzer（FaceDb）中，本页通过 OpenAPI 代理接口进行管理。
    - 本页仅提供 UI（交互/运维），不在 Admin DB 中持久化人脸库。
    """
    context = {}

    # 追踪/特征算法列表（用于从图片提取 embedding）
    try:
        tracking_algorithms = AlgorithmModel.objects.filter(
            state__gte=0,
            algorithm_subtype="tracking",
        ).order_by("sort", "id")
    except Exception:
        tracking_algorithms = []

    context["tracking_algorithms"] = tracking_algorithms
    default_feature_algorithm_code = str(
        get_value(
            "faceDefaultFeatureAlgorithmCode",
            getattr(g_config, "faceDefaultFeatureAlgorithmCode", ""),
        )
        or ""
    ).strip()
    default_feature_algorithm_label = default_feature_algorithm_code
    for algorithm in tracking_algorithms:
        algorithm_code = str(getattr(algorithm, "code", "") or "").strip()
        if algorithm_code != default_feature_algorithm_code:
            continue
        algorithm_name = str(getattr(algorithm, "name", "") or "").strip()
        if algorithm_name:
            default_feature_algorithm_label = "%s - %s" % (algorithm_code, algorithm_name)
        break
    context["default_feature_algorithm_code"] = default_feature_algorithm_code
    context["default_feature_algorithm_label"] = default_feature_algorithm_label
    context["has_default_feature_algorithm"] = bool(default_feature_algorithm_code)
    return render(request, "app/face/index.html", context)
