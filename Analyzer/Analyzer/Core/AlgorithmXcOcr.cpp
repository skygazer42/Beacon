#include "AlgorithmXcOcr.h"

#include <algorithm>
#include <cmath>

namespace AVSAnalyzer {

namespace {
struct CharItem {
    DetectObject det;
    float cx = 0.0f;
    float cy = 0.0f;
    float h = 0.0f;
};

struct LineCluster {
    std::vector<CharItem> items;
    float avgCy = 0.0f;
    float avgH = 0.0f;
};

static float center_x(const DetectObject& d) {
    return 0.5f * static_cast<float>(d.x1 + d.x2);
}

static float center_y(const DetectObject& d) {
    return 0.5f * static_cast<float>(d.y1 + d.y2);
}

static float height(const DetectObject& d) {
    return static_cast<float>(std::max(0, d.y2 - d.y1));
}
}  // namespace

AlgorithmXcOcr::AlgorithmXcOcr(Config* config, std::unique_ptr<Algorithm> inner)
    : Algorithm(config), mInner(std::move(inner)) {
    setCreateState((mInner != nullptr) && mInner->createState());
}

bool AlgorithmXcOcr::objectDetect(cv::Mat& image,
                                 std::vector<DetectObject>& detects,
                                 float scoreThreshold,
                                 float nmsThreshold) {
    detects.clear();
    if (!mInner) {
        return false;
    }

    std::vector<DetectObject> raw;
    if (!mInner->objectDetect(image, raw, scoreThreshold, nmsThreshold)) {
        return false;
    }

    std::vector<CharItem> chars;
    chars.reserve(raw.size());
    for (const auto& d : raw) {
        if (d.class_name.empty()) {
            continue;
        }
        CharItem item;
        item.det = d;
        item.cx = center_x(d);
        item.cy = center_y(d);
        item.h = std::max(1.0f, height(d));
        chars.push_back(std::move(item));
    }

    if (chars.empty()) {
        return true;
    }

    std::sort(chars.begin(), chars.end(), [](const CharItem& a, const CharItem& b) {
        if (a.cy == b.cy) {
            return a.cx < b.cx;
        }
        return a.cy < b.cy;
    });

    std::vector<LineCluster> clusters;
    clusters.reserve(4);
    for (const auto& c : chars) {
        if (clusters.empty()) {
            LineCluster cl;
            cl.items.push_back(c);
            cl.avgCy = c.cy;
            cl.avgH = c.h;
            clusters.push_back(std::move(cl));
            continue;
        }

        LineCluster& last = clusters.back();
        const float thr = std::max(8.0f, 0.6f * last.avgH);
        if (std::fabs(c.cy - last.avgCy) <= thr) {
            const size_t n = last.items.size();
            last.items.push_back(c);
            last.avgCy = (last.avgCy * static_cast<float>(n) + c.cy) / static_cast<float>(n + 1);
            last.avgH = (last.avgH * static_cast<float>(n) + c.h) / static_cast<float>(n + 1);
        }
        else {
            LineCluster cl;
            cl.items.push_back(c);
            cl.avgCy = c.cy;
            cl.avgH = c.h;
            clusters.push_back(std::move(cl));
        }
    }

    detects.reserve(clusters.size());
    for (auto& cl : clusters) {
        if (cl.items.empty()) {
            continue;
        }

        std::sort(cl.items.begin(), cl.items.end(), [](const CharItem& a, const CharItem& b) {
            return a.cx < b.cx;
        });

        int minX1 = cl.items[0].det.x1;
        int minY1 = cl.items[0].det.y1;
        int maxX2 = cl.items[0].det.x2;
        int maxY2 = cl.items[0].det.y2;
        double sumScore = 0.0;

        std::string text;
        text.reserve(cl.items.size() * 2);
        std::vector<DetectObject> sub;
        sub.reserve(cl.items.size());

        for (const auto& it : cl.items) {
            const auto& d = it.det;
            minX1 = std::min(minX1, d.x1);
            minY1 = std::min(minY1, d.y1);
            maxX2 = std::max(maxX2, d.x2);
            maxY2 = std::max(maxY2, d.y2);
            sumScore += static_cast<double>(d.class_score);
            text += d.class_name;
            sub.push_back(d);
        }

        DetectObject out;
        out.x1 = minX1;
        out.y1 = minY1;
        out.x2 = maxX2;
        out.y2 = maxY2;
        out.class_id = 0;
        out.class_name = text;
        out.class_score = static_cast<float>(sumScore / static_cast<double>(std::max<size_t>(1, cl.items.size())));
        out.subAlgorithmCode = "xcocr_chars";
        out.subObjects = std::move(sub);
        detects.push_back(std::move(out));
    }

    return true;
}

}  // namespace AVSAnalyzer
