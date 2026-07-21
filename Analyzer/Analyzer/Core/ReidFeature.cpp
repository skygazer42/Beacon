#include "ReidFeature.h"

#include <cmath>

namespace AVSAnalyzer {

    void reid_l2_normalize(std::vector<float>& feature) {
        if (feature.empty()) {
            return;
        }

        double sum = 0.0;
        for (float v : feature) {
            if (!std::isfinite(v)) {
                continue;
            }
            sum += static_cast<double>(v) * static_cast<double>(v);
        }

        if (!(sum > 0.0)) {
            // Zero vector or invalid numbers only -> keep original values (usually zeros).
            return;
        }

        const double inv = 1.0 / std::sqrt(sum);
        for (float& v : feature) {
            if (!std::isfinite(v)) {
                v = 0.0f;
                continue;
            }
            v = static_cast<float>(static_cast<double>(v) * inv);
        }
    }

    float reid_cosine_similarity(const std::vector<float>& a, const std::vector<float>& b) {
        if (a.empty() || b.empty() || a.size() != b.size()) {
            return 0.0f;
        }

        double dot = 0.0;
        double na = 0.0;
        double nb = 0.0;

        for (size_t i = 0; i < a.size(); ++i) {
            const double va = std::isfinite(a[i]) ? static_cast<double>(a[i]) : 0.0;
            const double vb = std::isfinite(b[i]) ? static_cast<double>(b[i]) : 0.0;
            dot += va * vb;
            na += va * va;
            nb += vb * vb;
        }

        if (!(na > 0.0) || !(nb > 0.0)) {
            return 0.0f;
        }

        const double denom = std::sqrt(na) * std::sqrt(nb);
        if (!(denom > 0.0)) {
            return 0.0f;
        }

        double sim = dot / denom;
        if (sim > 1.0) sim = 1.0;
        if (sim < -1.0) sim = -1.0;
        return static_cast<float>(sim);
    }

} // namespace AVSAnalyzer

