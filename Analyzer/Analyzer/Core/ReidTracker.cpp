#include "ReidTracker.h"

#include "ReidFeature.h"

#include <algorithm>
#include <cmath>
#include <tuple>

namespace AVSAnalyzer {

    ReidTracker::ReidTracker(const ReidTrackerConfig& cfg) : mCfg(cfg) {
        if (mCfg.iouThresh < 0.0f) mCfg.iouThresh = 0.0f;
        if (mCfg.iouThresh > 1.0f) mCfg.iouThresh = 1.0f;
        if (mCfg.cosineThresh < -1.0f) mCfg.cosineThresh = -1.0f;
        if (mCfg.cosineThresh > 1.0f) mCfg.cosineThresh = 1.0f;
        if (mCfg.maxAge < 1) mCfg.maxAge = 1;
        if (mCfg.featureMomentum < 0.0f) mCfg.featureMomentum = 0.0f;
        if (mCfg.featureMomentum > 1.0f) mCfg.featureMomentum = 1.0f;
    }

    ReidTracker::~ReidTracker() = default;

    void ReidTracker::reset() {
        mTracks.clear();
        mNextId = 1;
    }

    float ReidTracker::iou(const ReidDetection& a, const ReidDetection& b) {
        const int x1 = std::max(a.x1, b.x1);
        const int y1 = std::max(a.y1, b.y1);
        const int x2 = std::min(a.x2, b.x2);
        const int y2 = std::min(a.y2, b.y2);
        const int w = x2 - x1;
        const int h = y2 - y1;
        if (w <= 0 || h <= 0) {
            return 0.0f;
        }
        const double inter = static_cast<double>(w) * static_cast<double>(h);
        const int aw = std::max(0, a.x2 - a.x1);
        const int ah = std::max(0, a.y2 - a.y1);
        const int bw = std::max(0, b.x2 - b.x1);
        const int bh = std::max(0, b.y2 - b.y1);
        const double ua = static_cast<double>(aw) * static_cast<double>(ah);
        const double ub = static_cast<double>(bw) * static_cast<double>(bh);
        const double uni = ua + ub - inter;
        if (!(uni > 0.0)) {
            return 0.0f;
        }
        return static_cast<float>(inter / uni);
    }

    bool ReidTracker::update(
        const std::vector<ReidDetection>& detections,
        const std::vector<std::vector<float>>& embeddings,
        int frameId,
        std::vector<int>& outTrackIds,
        std::vector<int>& outTrackLens,
        std::string& errMsg
    ) {
        outTrackIds.assign(detections.size(), -1);
        outTrackLens.assign(detections.size(), 0);

        if (detections.empty()) {
            // Age tracks only.
            for (auto& t : mTracks) {
                t.missed += 1;
            }
            mTracks.erase(std::remove_if(mTracks.begin(), mTracks.end(),
                [&](const Track& t) { return t.missed > mCfg.maxAge; }), mTracks.end());
            errMsg.clear();
            return true;
        }

        if (!embeddings.empty() && embeddings.size() != detections.size()) {
            errMsg = "embeddings size mismatch";
            return false;
        }

        // Normalize detection boxes (ensure x1<=x2, y1<=y2).
        std::vector<ReidDetection> detBoxes;
        detBoxes.reserve(detections.size());
        for (const auto& d : detections) {
            ReidDetection b = d;
            if (b.x2 < b.x1) std::swap(b.x1, b.x2);
            if (b.y2 < b.y1) std::swap(b.y1, b.y2);
            detBoxes.push_back(b);
        }

        const float kInf = 1e9f;
        const size_t T = mTracks.size();
        const size_t D = detections.size();

        // Greedy assignment: collect all valid pairs and assign lowest cost first.
        std::vector<std::tuple<float, size_t, size_t>> pairs;
        pairs.reserve(T * D);

        for (size_t ti = 0; ti < T; ++ti) {
            const Track& tr = mTracks[ti];
            for (size_t di = 0; di < D; ++di) {
                const float iouVal = iou(tr.bbox, detBoxes[di]);
                if (iouVal < mCfg.iouThresh) {
                    continue;
                }

                // Cost:
                // - Prefer embedding match when both track and detection have features.
                // - Otherwise fall back to IOU-only association to keep TrackID stable when embeddings are missing.
                float cost = 1.0f - iouVal;
                if (!embeddings.empty() && !tr.feature.empty() && !embeddings[di].empty()) {
                    const float sim = reid_cosine_similarity(tr.feature, embeddings[di]);
                    if (sim < mCfg.cosineThresh) {
                        continue;
                    }
                    cost = 1.0f - sim;
                }
                pairs.emplace_back(cost, ti, di);
            }
        }

        std::sort(pairs.begin(), pairs.end(),
            [](const auto& a, const auto& b) { return std::get<0>(a) < std::get<0>(b); });

        std::vector<int> trackToDet(T, -1);
        std::vector<bool> detUsed(D, false);

        for (const auto& p : pairs) {
            const float cost = std::get<0>(p);
            const size_t ti = std::get<1>(p);
            const size_t di = std::get<2>(p);
            if (cost >= kInf) {
                continue;
            }
            if (ti >= T || di >= D) {
                continue;
            }
            if (trackToDet[ti] != -1) {
                continue;
            }
            if (detUsed[di]) {
                continue;
            }
            trackToDet[ti] = static_cast<int>(di);
            detUsed[di] = true;
        }

        // Update matched tracks.
        for (size_t ti = 0; ti < T; ++ti) {
            Track& tr = mTracks[ti];
            const int di = trackToDet[ti];
            if (di >= 0) {
                tr.bbox = detBoxes[static_cast<size_t>(di)];
                tr.missed = 0;
                tr.hits += 1;
                tr.lastFrameId = frameId;

                if (!embeddings.empty() && !embeddings[static_cast<size_t>(di)].empty()) {
                    const auto& obs = embeddings[static_cast<size_t>(di)];
                    if (tr.feature.empty()) {
                        tr.feature = obs;
                    }
                    else if (tr.feature.size() == obs.size()) {
                        const float m = mCfg.featureMomentum;
                        for (size_t k = 0; k < tr.feature.size(); ++k) {
                            tr.feature[k] = m * tr.feature[k] + (1.0f - m) * obs[k];
                        }
                    }
                    else {
                        tr.feature = obs;
                    }
                    reid_l2_normalize(tr.feature);
                }

                outTrackIds[static_cast<size_t>(di)] = tr.id;
                outTrackLens[static_cast<size_t>(di)] = tr.hits;
            }
            else {
                tr.missed += 1;
            }
        }

        // Remove stale tracks.
        mTracks.erase(std::remove_if(mTracks.begin(), mTracks.end(),
            [&](const Track& t) { return t.missed > mCfg.maxAge; }), mTracks.end());

        // Create new tracks for unmatched detections.
        for (size_t di = 0; di < D; ++di) {
            if (detUsed[di]) {
                continue;
            }
            Track tr;
            tr.id = mNextId++;
            tr.bbox = detBoxes[di];
            tr.hits = 1;
            tr.missed = 0;
            tr.lastFrameId = frameId;
            if (!embeddings.empty() && !embeddings[di].empty()) {
                tr.feature = embeddings[di];
                reid_l2_normalize(tr.feature);
            }
            mTracks.push_back(std::move(tr));

            outTrackIds[di] = mTracks.back().id;
            outTrackLens[di] = mTracks.back().hits;
        }

        errMsg.clear();
        return true;
    }

} // namespace AVSAnalyzer
