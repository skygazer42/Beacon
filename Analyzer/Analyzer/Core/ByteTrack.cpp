#include "ByteTrack.h"
#include "Utils/Log.h"
#include <algorithm>
#include <limits>
#include <tuple>
#include <utility>

namespace AVSAnalyzer {

    // ========== KalmanBoxTracker Implementation ==========

    KalmanBoxTracker::KalmanBoxTracker(const cv::Rect& bbox)
        : mPredictedBox(bbox) {

        // 状态向量 [x, y, s, r, vx, vy, vs]
        // x, y: 中心坐标
        // s: 面积 (scale)
        // r: 宽高比 (aspect ratio)
        // vx, vy, vs: 速度
        mKF.init(7, 4, 0);

        // 状态转移矩阵 A
        mKF.transitionMatrix = (cv::Mat_<float>(7, 7) <<
            1, 0, 0, 0, 1, 0, 0,
            0, 1, 0, 0, 0, 1, 0,
            0, 0, 1, 0, 0, 0, 1,
            0, 0, 0, 1, 0, 0, 0,
            0, 0, 0, 0, 1, 0, 0,
            0, 0, 0, 0, 0, 1, 0,
            0, 0, 0, 0, 0, 0, 1);

        // 观测矩阵 H
        mKF.measurementMatrix = cv::Mat::zeros(4, 7, CV_32F);
        mKF.measurementMatrix.at<float>(0, 0) = 1.0f;
        mKF.measurementMatrix.at<float>(1, 1) = 1.0f;
        mKF.measurementMatrix.at<float>(2, 2) = 1.0f;
        mKF.measurementMatrix.at<float>(3, 3) = 1.0f;

        // 过程噪声协方差 Q
        cv::setIdentity(mKF.processNoiseCov, cv::Scalar(1e-2));

        // 测量噪声协方差 R
        cv::setIdentity(mKF.measurementNoiseCov, cv::Scalar(1e-1));

        // 后验误差协方差 P
        cv::setIdentity(mKF.errorCovPost, cv::Scalar(10));

        // 初始化状态
	        float cx = static_cast<float>(bbox.x) + static_cast<float>(bbox.width) / 2.0f;
	        float cy = static_cast<float>(bbox.y) + static_cast<float>(bbox.height) / 2.0f;
	        float s = static_cast<float>(bbox.width) * static_cast<float>(bbox.height);
		        float r = static_cast<float>(bbox.width) / static_cast<float>(bbox.height);

        mKF.statePost = (cv::Mat_<float>(7, 1) << cx, cy, s, r, 0, 0, 0);
    }

    cv::Rect KalmanBoxTracker::predict() {
        cv::Mat prediction = mKF.predict();

        float cx = prediction.at<float>(0);
        float cy = prediction.at<float>(1);
        float s = prediction.at<float>(2);
        float r = prediction.at<float>(3);

        float w = std::sqrt(s * r);
        float h = s / w;

        mPredictedBox = cv::Rect(
            static_cast<int>(cx - w / 2),
            static_cast<int>(cy - h / 2),
            static_cast<int>(w),
            static_cast<int>(h)
        );

        mAge++;
        mTimeSinceUpdate++;

        return mPredictedBox;
    }

    void KalmanBoxTracker::update(const cv::Rect& bbox) {
        mTimeSinceUpdate = 0;

	        float cx = static_cast<float>(bbox.x) + static_cast<float>(bbox.width) / 2.0f;
	        float cy = static_cast<float>(bbox.y) + static_cast<float>(bbox.height) / 2.0f;
	        float s = static_cast<float>(bbox.width) * static_cast<float>(bbox.height);
		        float r = static_cast<float>(bbox.width) / static_cast<float>(bbox.height);

        cv::Mat measurement = (cv::Mat_<float>(4, 1) << cx, cy, s, r);
        mKF.correct(measurement);

        mPredictedBox = bbox;
    }

    cv::Rect KalmanBoxTracker::getState() const {
        return mPredictedBox;
    }

	    // ========== STrack Implementation ==========

	    STrack::STrack(const cv::Rect& bbox, float score, int currentFrameId)
	        : bbox(bbox), score(score), frameId(currentFrameId),
	          startFrame(currentFrameId), kalmanFilter(std::make_unique<KalmanBoxTracker>(bbox)) {

	        prediction = kalmanFilter->getPrediction();
	    }

    void STrack::activate(int currentFrameId, int newId) {
        this->trackId = newId;
        this->trackletLen = 0;
        this->state = State::Tracked;
        this->isActivated = true;
        this->frameId = currentFrameId;
        this->startFrame = currentFrameId;
    }

    void STrack::reActivate(const STrack& newTrack, int currentFrameId, int newId) {
        this->bbox = newTrack.bbox;
        this->score = newTrack.score;
        if (kalmanFilter) {
            kalmanFilter->update(newTrack.bbox);
        }
        this->trackletLen = 0;
        this->state = State::Tracked;
        this->isActivated = true;
        this->frameId = currentFrameId;
        if (newId != -1) {
            this->trackId = newId;
        }
    }

    void STrack::update(const STrack& newTrack, int currentFrameId) {
        this->frameId = currentFrameId;
        this->trackletLen++;

        this->bbox = newTrack.bbox;
        this->score = newTrack.score;

        if (kalmanFilter) {
            kalmanFilter->update(newTrack.bbox);
        }

        this->state = State::Tracked;
        this->isActivated = true;
    }

    void STrack::markLost() {
        this->state = State::Lost;
    }

    void STrack::markRemoved() {
        this->state = State::Removed;
    }

    // ========== ByteTracker Implementation ==========

	    ByteTracker::ByteTracker(int frameRate, int trackBuffer, float trackThresh,
	                             float highThresh, float matchThresh)
	        : mFrameRate(frameRate), mTrackBuffer(trackBuffer),
	          mTrackThresh(trackThresh), mHighThresh(highThresh),
	          mMatchThresh(matchThresh) {

	        mMaxTimeLost = static_cast<int>(
	            static_cast<float>(mFrameRate) / 30.0f * static_cast<float>(mTrackBuffer));
	    }

    ByteTracker::ByteTracker(ByteTracker&& other) noexcept
        : mFrameId(other.mFrameId),
          mFrameRate(other.mFrameRate),
          mTrackBuffer(other.mTrackBuffer),
          mTrackThresh(other.mTrackThresh),
          mHighThresh(other.mHighThresh),
          mMatchThresh(other.mMatchThresh),
          mMaxTimeLost(other.mMaxTimeLost),
          mNextId(other.mNextId),
          mTrackedStracks(std::move(other.mTrackedStracks)),
          mLostStracks(std::move(other.mLostStracks)),
          mRemovedStracks(std::move(other.mRemovedStracks)) {
        other.clear();
    }

    ByteTracker& ByteTracker::operator=(ByteTracker&& other) noexcept {
        if (this == &other) {
            return *this;
        }

        clear();

        mFrameId = other.mFrameId;
        mFrameRate = other.mFrameRate;
        mTrackBuffer = other.mTrackBuffer;
        mTrackThresh = other.mTrackThresh;
        mHighThresh = other.mHighThresh;
        mMatchThresh = other.mMatchThresh;
        mMaxTimeLost = other.mMaxTimeLost;
        mNextId = other.mNextId;
        mTrackedStracks = std::move(other.mTrackedStracks);
        mLostStracks = std::move(other.mLostStracks);
        mRemovedStracks = std::move(other.mRemovedStracks);

        other.clear();
        return *this;
    }

    ByteTracker::~ByteTracker() {
        clear();
    }

	    void ByteTracker::clear() {
	        mTrackedStracks.clear();
	        mLostStracks.clear();
	        mRemovedStracks.clear();
	        mFrameId = 0;
	        mNextId = 1;
	    }

    size_t ByteTracker::getTrackCount() const {
        return mTrackedStracks.size();
    }

    float ByteTracker::iou(const cv::Rect& a, const cv::Rect& b) {
        int x1 = std::max(a.x, b.x);
        int y1 = std::max(a.y, b.y);
        int x2 = std::min(a.x + a.width, b.x + b.width);
        int y2 = std::min(a.y + a.height, b.y + b.height);

        if (x2 < x1 || y2 < y1) return 0.0f;

        auto intersectionArea = static_cast<float>((x2 - x1) * (y2 - y1));
        auto areaA = static_cast<float>(a.width * a.height);
        auto areaB = static_cast<float>(b.width * b.height);
        float unionArea = areaA + areaB - intersectionArea;

        return (unionArea > 0.0f) ? (intersectionArea / unionArea) : 0.0f;
    }

    std::vector<std::vector<float>> ByteTracker::iouDistance(
        const std::vector<STrack*>& aTracks,
        const std::vector<STrack*>& bTracks) {

        std::vector<std::vector<float>> costMatrix(aTracks.size(), std::vector<float>(bTracks.size(), 0.0f));

        for (size_t i = 0; i < aTracks.size(); ++i) {
            for (size_t j = 0; j < bTracks.size(); ++j) {
                costMatrix[i][j] = 1.0f - iou(aTracks[i]->bbox, bTracks[j]->bbox);
            }
        }

        return costMatrix;
    }

    void ByteTracker::linearAssignment(
        const std::vector<std::vector<float>>& costMatrix,
        float thresh,
        std::vector<std::vector<int>>& matches,
        std::vector<int>& unmatched_a,
        std::vector<int>& unmatched_b) {

        if (costMatrix.empty()) return;

        size_t rows = costMatrix.size();
        size_t cols = costMatrix[0].size();

        // 按 IoU 代价执行贪心一对一分配。
        std::vector<int> assignment = GreedyAssignment::Solve(costMatrix);

        std::vector<bool> matchedA(rows, false);
        std::vector<bool> matchedB(cols, false);

        for (size_t i = 0; i < assignment.size(); ++i) {
            if (assignment[i] >= 0 && costMatrix[i][assignment[i]] < thresh) {
                matches.push_back({static_cast<int>(i), assignment[i]});
                matchedA[i] = true;
                matchedB[assignment[i]] = true;
            }
        }

        for (size_t i = 0; i < rows; ++i) {
            if (!matchedA[i]) {
                unmatched_a.push_back(static_cast<int>(i));
            }
        }

        for (size_t j = 0; j < cols; ++j) {
            if (!matchedB[j]) {
                unmatched_b.push_back(static_cast<int>(j));
            }
        }
    }

    void ByteTracker::removeDuplicateStracks(
        std::vector<STrack*>& aTracks,
        std::vector<STrack*>& bTracks,
        std::vector<STrack*>& result) {

        std::vector<std::vector<float>> pdist = iouDistance(aTracks, bTracks);

        std::vector<std::pair<int, int>> pairs;
        for (size_t i = 0; i < pdist.size(); ++i) {
            for (size_t j = 0; j < pdist[i].size(); ++j) {
                if (pdist[i][j] < 0.15f) {
                    pairs.push_back({static_cast<int>(i), static_cast<int>(j)});
                }
            }
        }

        std::vector<int> dupA;
        std::vector<int> dupB;
        for (const auto& pair : pairs) {
            int timep = aTracks[pair.first]->frameId - aTracks[pair.first]->startFrame;
            int timeq = bTracks[pair.second]->frameId - bTracks[pair.second]->startFrame;
            if (timep > timeq) {
                dupB.push_back(pair.second);
            } else {
                dupA.push_back(pair.first);
            }
        }

        std::vector<STrack*> resA;
        std::vector<STrack*> resB;
        for (size_t i = 0; i < aTracks.size(); ++i) {
            if (std::find(dupA.begin(), dupA.end(), i) == dupA.end()) {
                resA.push_back(aTracks[i]);
            }
        }

        for (size_t i = 0; i < bTracks.size(); ++i) {
            if (std::find(dupB.begin(), dupB.end(), i) == dupB.end()) {
                resB.push_back(bTracks[i]);
            }
        }

        result = resA;
        result.insert(result.end(), resB.begin(), resB.end());
    }

    void ByteTracker::jointStracks(
        std::vector<STrack*>& aTracks,
        const std::vector<STrack*>& bTracks,
        std::vector<STrack*>& result) {

        std::map<int, int> exists;
        result = aTracks;

        for (size_t i = 0; i < aTracks.size(); ++i) {
            exists[aTracks[i]->trackId] = 1;
        }

        for (auto* track : bTracks) {
            if (exists.find(track->trackId) == exists.end()) {
                result.push_back(track);
            }
        }
    }

    void ByteTracker::subStracks(
        std::vector<STrack*>& aTracks,
        const std::vector<STrack*>& bTracks) {

        std::map<int, STrack*> stracks;
        for (auto* track : aTracks) {
            stracks[track->trackId] = track;
        }

        for (const auto* track : bTracks) {
            auto it = stracks.find(track->trackId);
            if (it != stracks.end()) {
                stracks.erase(it);
            }
        }

        aTracks.clear();
        for (const auto& pair : stracks) {
            aTracks.push_back(pair.second);
        }
    }

    std::vector<STrack*> ByteTracker::update(const std::vector<DetectObject>& detections, int frameId) {
        mFrameId = frameId;

	        // Step 1: build detection tracks (high / low)
	        std::vector<std::unique_ptr<STrack>> detsHigh;
	        std::vector<std::unique_ptr<STrack>> detsLow;
	        detsHigh.reserve(detections.size());
	        detsLow.reserve(detections.size());

        for (const auto& det : detections) {
            const int w = det.x2 - det.x1;
            const int h = det.y2 - det.y1;
            if (w <= 0 || h <= 0) {
                continue;
	            }
	            cv::Rect bbox(det.x1, det.y1, w, h);
	            auto track = std::make_unique<STrack>(bbox, det.class_score, mFrameId);
	            if (det.class_score >= mTrackThresh) {
	                detsHigh.push_back(std::move(track));
	            } else {
	                detsLow.push_back(std::move(track));
	            }
	        }

	        // Step 2: build track pool (tracked + lost)
	        std::vector<STrack*> trackPool;
	        trackPool.reserve(mTrackedStracks.size() + mLostStracks.size());
	        for (const auto& t : mTrackedStracks) {
	            trackPool.push_back(t.get());
	        }
	        for (const auto& t : mLostStracks) {
	            trackPool.push_back(t.get());
	        }

        // Predict current poses by KF
        for (auto* t : trackPool) {
            if (t && t->kalmanFilter) {
                t->prediction = t->kalmanFilter->predict();
            }
        }

        // Step 3: first association (trackPool <-> high detections)
        std::vector<std::vector<int>> matchesHigh;
        std::vector<int> unmatchedTrackIdx;
        std::vector<int> unmatchedDetHighIdx;

	        if (!trackPool.empty() && !detsHigh.empty()) {
	            std::vector<STrack*> detsHighPtr;
	            detsHighPtr.reserve(detsHigh.size());
	            for (const auto& det : detsHigh) {
	                detsHighPtr.push_back(det.get());
	            }
	            std::vector<std::vector<float>> dists = iouDistance(trackPool, detsHighPtr);
	            linearAssignment(dists, mMatchThresh, matchesHigh, unmatchedTrackIdx, unmatchedDetHighIdx);
	        } else {
            for (size_t i = 0; i < trackPool.size(); ++i) unmatchedTrackIdx.push_back(static_cast<int>(i));
            for (size_t i = 0; i < detsHigh.size(); ++i) unmatchedDetHighIdx.push_back(static_cast<int>(i));
        }

        for (const auto& match : matchesHigh) {
            const int tIdx = match[0];
            const int dIdx = match[1];
            if (tIdx < 0 || dIdx < 0) {
                continue;
            }
            if (static_cast<size_t>(tIdx) >= trackPool.size()) {
                continue;
            }
            if (static_cast<size_t>(dIdx) >= detsHigh.size()) {
                continue;
            }

            STrack* track = trackPool[tIdx];
            const STrack* det = detsHigh[dIdx].get();
            if (!track || !det) {
                continue;
            }

            if (track->state == STrack::State::Tracked) {
                track->update(*det, mFrameId);
            } else {
                track->reActivate(*det, mFrameId);
            }

            detsHigh[dIdx].reset();
        }

        // Step 4: second association (remaining tracked <-> low detections)
        std::vector<STrack*> remainingTracked;
        remainingTracked.reserve(unmatchedTrackIdx.size());
        for (int idx : unmatchedTrackIdx) {
            if (idx < 0) continue;
            if (static_cast<size_t>(idx) >= trackPool.size()) continue;
            STrack* t = trackPool[idx];
            if (t && t->state == STrack::State::Tracked) {
                remainingTracked.push_back(t);
            }
        }

        std::vector<std::vector<int>> matchesLow;
        std::vector<int> unmatchedRemainingIdx;
        std::vector<int> unmatchedDetLowIdx;

	        if (!remainingTracked.empty() && !detsLow.empty()) {
	            std::vector<STrack*> detsLowPtr;
	            detsLowPtr.reserve(detsLow.size());
	            for (const auto& det : detsLow) {
	                detsLowPtr.push_back(det.get());
	            }
	            std::vector<std::vector<float>> dists = iouDistance(remainingTracked, detsLowPtr);
	            linearAssignment(dists, 0.5f, matchesLow, unmatchedRemainingIdx, unmatchedDetLowIdx);
	        } else {
            for (size_t i = 0; i < remainingTracked.size(); ++i) unmatchedRemainingIdx.push_back(static_cast<int>(i));
            for (size_t i = 0; i < detsLow.size(); ++i) unmatchedDetLowIdx.push_back(static_cast<int>(i));
        }

        for (const auto& match : matchesLow) {
            const int tIdx = match[0];
            const int dIdx = match[1];
            if (tIdx < 0 || dIdx < 0) {
                continue;
            }
            if (static_cast<size_t>(tIdx) >= remainingTracked.size()) {
                continue;
            }
            if (static_cast<size_t>(dIdx) >= detsLow.size()) {
                continue;
            }

            STrack* track = remainingTracked[tIdx];
            const STrack* det = detsLow[dIdx].get();
            if (!track || !det) {
                continue;
            }

            track->update(*det, mFrameId);

            detsLow[dIdx].reset();
        }

        for (int idx : unmatchedRemainingIdx) {
            if (idx < 0) continue;
            if (static_cast<size_t>(idx) >= remainingTracked.size()) continue;
            STrack* track = remainingTracked[idx];
            if (track && track->state != STrack::State::Lost) {
                track->markLost();
            }
        }

	        // Step 5: init new tracks from unmatched high detections
	        for (int idx : unmatchedDetHighIdx) {
	            if (idx < 0) continue;
	            if (static_cast<size_t>(idx) >= detsHigh.size()) continue;
	            auto& det = detsHigh[idx];
	            if (!det) continue;

		            if (det->score >= mHighThresh) {
		                const int nextTrackId = mNextId;
		                ++mNextId;
		                det->activate(mFrameId, nextTrackId);
		                mTrackedStracks.push_back(std::move(det));
		            }
	            else {
	                det.reset();
	            }
	        }

	        // Step 6: cleanup remaining detection tracks
	        detsHigh.clear();
	        detsLow.clear();

	        // Step 7: rebuild tracked/lost lists and drop removed tracks
	        std::vector<std::unique_ptr<STrack>> all;
	        all.reserve(mTrackedStracks.size() + mLostStracks.size());
	        for (auto& t : mTrackedStracks) {
	            all.push_back(std::move(t));
	        }
	        for (auto& t : mLostStracks) {
	            all.push_back(std::move(t));
	        }

	        mTrackedStracks.clear();
	        mLostStracks.clear();
	        mRemovedStracks.clear();

	        for (auto& t : all) {
	            if (!t) continue;
	            if (t->state == STrack::State::Lost) {
	                if (mFrameId - t->frameId > mMaxTimeLost) {
	                    continue;
	                }
	                mLostStracks.push_back(std::move(t));
	            }
	            else if (t->state == STrack::State::Tracked) {
	                mTrackedStracks.push_back(std::move(t));
	            }
	            else if (t->state == STrack::State::Removed) {
	                // drop
	            }
	            else {
	                // New/unknown -> treat as tracked if activated, otherwise drop
	                if (t->isActivated) {
	                    t->state = STrack::State::Tracked;
	                    mTrackedStracks.push_back(std::move(t));
	                }
	            }
	        }

	        std::vector<STrack*> output;
	        output.reserve(mTrackedStracks.size());
	        for (const auto& t : mTrackedStracks) {
	            if (t && t->isActivated) {
	                output.push_back(t.get());
	            }
	        }

        return output;
    }

    // ========== ByteTrackNode Implementation ==========

    bool ByteTrackNode::process(PipelineContext& context) {
        mFrameId++;

        std::vector<STrack*> tracks = mTracker.update(context.detections, mFrameId);

        // 将追踪ID添加到检测对象中
        for (size_t i = 0; i < context.detections.size() && i < tracks.size(); ++i) {
            for (const auto* track : tracks) {
                float iou = ByteTracker::iou(
                    cv::Rect(context.detections[i].x1, context.detections[i].y1,
                            context.detections[i].x2 - context.detections[i].x1,
                            context.detections[i].y2 - context.detections[i].y1),
                    track->bbox
                );

                if (iou > 0.3f) {
                    context.detections[i].attributes["track_id"] = static_cast<float>(track->trackId);
                    context.detections[i].attributes["track_len"] = static_cast<float>(track->trackletLen);
                    break;
                }
            }
        }

        LOGI("ByteTrackNode: %zu detections -> %zu tracks", context.detections.size(), tracks.size());

        return true;
    }

    // ========== GreedyAssignment Implementation ==========

    std::vector<int> GreedyAssignment::Solve(const std::vector<std::vector<float>>& costMatrix) {
        size_t nRows = costMatrix.size();
        if (nRows == 0) return {};

        size_t nCols = costMatrix[0].size();
        std::vector<int> assignment(nRows, -1);

        std::vector<bool> rowUsed(nRows, false);
        std::vector<bool> colUsed(nCols, false);

        // 按代价从小到大排序
        std::vector<std::tuple<float, int, int>> costs;
        for (size_t i = 0; i < nRows; ++i) {
            for (size_t j = 0; j < nCols; ++j) {
                costs.push_back({costMatrix[i][j], static_cast<int>(i), static_cast<int>(j)});
            }
        }

        std::sort(costs.begin(), costs.end());

        // 贪心分配
        for (const auto& cost : costs) {
            int row = std::get<1>(cost);
            int col = std::get<2>(cost);

            if (!rowUsed[row] && !colUsed[col]) {
                assignment[row] = col;
                rowUsed[row] = true;
                colUsed[col] = true;
            }
        }

        return assignment;
    }

} // namespace AVSAnalyzer
