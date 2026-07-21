#ifndef ANALYZER_REID_EMBED_POLICY_H
#define ANALYZER_REID_EMBED_POLICY_H

#include <algorithm>
#include <cstddef>
#include <string>
#include <tuple>
#include <vector>

namespace AVSAnalyzer {

    inline bool should_run_reid_embedding(int frameId, int everyNFrames) {
        if (everyNFrames <= 1) {
            return true;
        }
        if (frameId < 1) {
            return true;
        }
        return ((frameId - 1) % everyNFrames) == 0;
    }

    // Note: This policy intentionally avoids depending on OpenCV or Analyzer data structures.
    // It works with any detection type that provides:
    //   - int x1,y1,x2,y2
    //   - std::string class_name
    template <typename DetectionT>
    inline std::vector<size_t> select_reid_embedding_indices(
        const std::vector<DetectionT>& detections,
        int maxRoiPerFrame,
        bool targetOnly,
        const std::string& targetName
    ) {
        std::vector<size_t> result;
        if (detections.empty()) {
            return result;
        }

        const bool filterTarget = targetOnly && !targetName.empty();
        if (maxRoiPerFrame < 0) {
            maxRoiPerFrame = 0;
        }

        std::vector<std::tuple<long long, size_t>> scored;
        scored.reserve(detections.size());

        for (size_t i = 0; i < detections.size(); ++i) {
            const auto& d = detections[i];
            if (filterTarget && d.class_name != targetName) {
                continue;
            }
            const int w = d.x2 - d.x1;
            const int h = d.y2 - d.y1;
            if (w <= 0 || h <= 0) {
                continue;
            }
            const long long area = static_cast<long long>(w) * static_cast<long long>(h);
            scored.emplace_back(area, i);
        }

        std::sort(scored.begin(), scored.end(), [](const auto& a, const auto& b) {
            // area desc, index asc
            if (std::get<0>(a) != std::get<0>(b)) {
                return std::get<0>(a) > std::get<0>(b);
            }
            return std::get<1>(a) < std::get<1>(b);
        });

        const size_t limit = (maxRoiPerFrame > 0) ? static_cast<size_t>(maxRoiPerFrame) : scored.size();
        result.reserve(std::min(limit, scored.size()));
        for (size_t i = 0; i < scored.size() && i < limit; ++i) {
            result.push_back(std::get<1>(scored[i]));
        }

        return result;
    }

} // namespace AVSAnalyzer

#endif // ANALYZER_REID_EMBED_POLICY_H
