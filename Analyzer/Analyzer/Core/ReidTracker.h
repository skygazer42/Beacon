#ifndef ANALYZER_REID_TRACKER_H
#define ANALYZER_REID_TRACKER_H

#include <cstdint>
#include <string>
#include <vector>

namespace AVSAnalyzer {

    struct ReidDetection {
        int x1 = 0;
        int y1 = 0;
        int x2 = 0;
        int y2 = 0;
    };

    struct ReidTrackerConfig {
        float iouThresh = 0.3f;        // bbox IOU gating threshold
        float cosineThresh = 0.5f;     // embedding cosine similarity gating threshold
        int maxAge = 30;               // max missed frames before removing a track
        float featureMomentum = 0.9f;  // EMA: new = m*old + (1-m)*obs
    };

    class ReidTracker {
    public:
        explicit ReidTracker(const ReidTrackerConfig& cfg);
        ~ReidTracker();

        void reset();

        bool update(
            const std::vector<ReidDetection>& detections,
            const std::vector<std::vector<float>>& embeddings,
            int frameId,
            std::vector<int>& outTrackIds,
            std::vector<int>& outTrackLens,
            std::string& errMsg
        );

    private:
        struct Track {
            int id = 0;
            ReidDetection bbox;
            std::vector<float> feature;
            int hits = 0;
            int missed = 0;
            int lastFrameId = 0;
        };

        static float iou(const ReidDetection& a, const ReidDetection& b);

        ReidTrackerConfig mCfg;
        int mNextId = 1;
        std::vector<Track> mTracks;
    };

} // namespace AVSAnalyzer

#endif // ANALYZER_REID_TRACKER_H
