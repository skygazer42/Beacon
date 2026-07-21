#include "ReidTracker.h"

#include <cassert>
#include <string>
#include <vector>

using namespace AVSAnalyzer;

static ReidDetection make_det(int x1, int y1, int x2, int y2) {
    ReidDetection d;
    d.x1 = x1;
    d.y1 = y1;
    d.x2 = x2;
    d.y2 = y2;
    return d;
}

static void test_basic_track_id_stability() {
    ReidTrackerConfig cfg;
    cfg.iouThresh = 0.1f;
    cfg.cosineThresh = 0.1f;
    cfg.maxAge = 10;
    cfg.featureMomentum = 0.0f; // always replace for test determinism
    ReidTracker tracker(cfg);

    std::vector<ReidDetection> dets1 = {
        make_det(0, 0, 10, 10),
        make_det(100, 100, 110, 110),
    };
    std::vector<std::vector<float>> emb1 = {
        {1.0f, 0.0f},
        {0.0f, 1.0f},
    };

    std::vector<int> ids;
    std::vector<int> lens;
    std::string err;
    assert(tracker.update(dets1, emb1, 1, ids, lens, err) == true);
    assert(err.empty());
    assert(ids.size() == 2);
    assert(ids[0] > 0);
    assert(ids[1] > 0);
    assert(ids[0] != ids[1]);

    int idA = ids[0];
    int idB = ids[1];

    // Next frame: slight movement, embeddings still match.
    std::vector<ReidDetection> dets2 = {
        make_det(1, 0, 11, 10),
        make_det(101, 100, 111, 110),
    };
    std::vector<std::vector<float>> emb2 = {
        {0.9f, 0.1f},
        {0.1f, 0.9f},
    };

    assert(tracker.update(dets2, emb2, 2, ids, lens, err) == true);
    assert(err.empty());
    assert(ids.size() == 2);
    assert(ids[0] == idA);
    assert(ids[1] == idB);
    assert(lens[0] >= 2);
    assert(lens[1] >= 2);
}

int main() {
    test_basic_track_id_stability();
    return 0;
}
