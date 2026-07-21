#include "RecognitionRegions.h"

#include <cassert>
#include <cmath>
#include <string>
#include <vector>

using namespace AVSAnalyzer;

static bool nearly(double a, double b, double eps = 1e-6) {
    return std::fabs(a - b) <= eps;
}

int main() {
    {
        std::vector<std::vector<double>> regions;
        std::string err;
        const std::string raw =
            "0,0,1,0,1,1,0,1;"
            "0.1,0.1,0.2,0.1,0.2,0.2,0.1,0.2";

        bool ok = parseRecognitionRegionsPixels(raw, /*videoWidth=*/100, /*videoHeight=*/100, regions, err);
        assert(ok);
        assert(err.empty());
        assert(regions.size() == 2);
        assert(regions[0].size() == 8);
        assert(regions[1].size() == 8);

        assert(nearly(regions[0][0], 0));
        assert(nearly(regions[0][1], 0));
        assert(nearly(regions[0][2], 100));
        assert(nearly(regions[0][3], 0));
        assert(nearly(regions[0][4], 100));
        assert(nearly(regions[0][5], 100));

        assert(nearly(regions[1][0], 10));
        assert(nearly(regions[1][1], 10));
        assert(nearly(regions[1][2], 20));
        assert(nearly(regions[1][3], 10));
        assert(nearly(regions[1][4], 20));
        assert(nearly(regions[1][5], 20));
    }

    {
        // Supports polygons with > 4 points (e.g., rect with extra midpoints).
        std::vector<std::vector<double>> regions;
        std::string err;
        const std::string raw =
            "0,0,1,0,1,0.5,1,1,0,1,0,0.5"; // 6 points

        bool ok = parseRecognitionRegionsPixels(raw, /*videoWidth=*/200, /*videoHeight=*/100, regions, err);
        assert(ok);
        assert(regions.size() == 1);
        assert(regions[0].size() == 12);

        // Object bbox (50,20)-(60,30) is fully inside => coverage ratio should be ~1.0.
        const std::vector<double> obj = { 50, 20, 60, 20, 60, 30, 50, 30 };
        double ratio = calcMaxCoverageRatio(regions, obj);
        assert(ratio > 0.99);
        assert(ratio <= 1.000001);
    }

    {
        // Invalid region should be ignored if at least one valid region exists.
        std::vector<std::vector<double>> regions;
        std::string err;
        const std::string raw = "bad;0,0,1,0,1,1,0,1";
        bool ok = parseRecognitionRegionsPixels(raw, /*videoWidth=*/100, /*videoHeight=*/100, regions, err);
        assert(ok);
        assert(regions.size() == 1);
        assert(regions[0].size() == 8);
    }

    {
        // Numeric tokens with trailing garbage must invalidate that region.
        std::vector<std::vector<double>> regions;
        std::string err;
        const std::string raw =
            "0,0,1,0,1,1,0,1oops;"
            "0.1,0.1,0.2,0.1,0.2,0.2,0.1,0.2";
        bool ok = parseRecognitionRegionsPixels(raw, /*videoWidth=*/100, /*videoHeight=*/100, regions, err);
        assert(ok);
        assert(err.empty());
        assert(regions.size() == 1);
        assert(regions[0].size() == 8);
        assert(nearly(regions[0][0], 10));
        assert(nearly(regions[0][1], 10));
        assert(nearly(regions[0][6], 10));
        assert(nearly(regions[0][7], 20));
    }

    return 0;
}
