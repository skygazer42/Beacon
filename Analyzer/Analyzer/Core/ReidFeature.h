#ifndef ANALYZER_REID_FEATURE_H
#define ANALYZER_REID_FEATURE_H

#include <vector>

namespace AVSAnalyzer {

    // L2-normalize a feature vector in-place.
    // - For zero vectors, it is a no-op (keeps zeros).
    // - Never produces NaN/Inf.
    void reid_l2_normalize(std::vector<float>& feature);

    // Cosine similarity in [-1, 1]. Returns 0 if dims mismatch or any vector is empty.
    float reid_cosine_similarity(const std::vector<float>& a, const std::vector<float>& b);

} // namespace AVSAnalyzer

#endif // ANALYZER_REID_FEATURE_H

