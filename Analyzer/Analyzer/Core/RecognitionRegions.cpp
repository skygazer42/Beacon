#include "RecognitionRegions.h"

#include "Utils/CalcuIOU.h"
#include "Utils/Common.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <exception>
#include <string>
#include <stdexcept>
#include <vector>

namespace AVSAnalyzer {

namespace {
    std::string trim_copy(std::string value) {
        auto is_ws = [](unsigned char c) { return std::isspace(c) != 0; };
        while (!value.empty() && is_ws(static_cast<unsigned char>(value.front()))) {
            value.erase(value.begin());
        }
        while (!value.empty() && is_ws(static_cast<unsigned char>(value.back()))) {
            value.pop_back();
        }
        return value;
    }

    double clamp(double v, double lo, double hi) {
        if (v < lo) return lo;
        if (v > hi) return hi;
        return v;
    }

    bool parse_normalized_coordinate(const std::string& tokenRaw, double& outValue) {
        const std::string token = trim_copy(tokenRaw);
        if (token.empty()) {
            return false;
        }

        try {
            size_t parsedLength = 0;
            const double parsed = std::stod(token, &parsedLength);
            if (parsedLength != token.size()) {
                return false;
            }

            outValue = clamp(parsed, 0.0, 1.0);
            return true;
        }
        catch (const std::invalid_argument&) {
            return false;
        }
        catch (const std::out_of_range&) {
            return false;
        }
    }

    bool parse_region_pixels(
        const std::string& regionStr,
        int videoWidth,
        int videoHeight,
        std::vector<double>& outRegionPixels)
    {
        if (const auto tokens = split(regionStr, ","); tokens.size() < 6 || (tokens.size() % 2) != 0) {
            return false;
        }
        else {
            outRegionPixels.clear();
            outRegionPixels.reserve(tokens.size());
            for (size_t i = 0; i < tokens.size(); i += 2) {
                double normalizedX = 0.0;
                double normalizedY = 0.0;
                if (!parse_normalized_coordinate(tokens[i], normalizedX) ||
                    !parse_normalized_coordinate(tokens[i + 1], normalizedY)) {
                    return false;
                }

                outRegionPixels.push_back(normalizedX * static_cast<double>(videoWidth));
                outRegionPixels.push_back(normalizedY * static_cast<double>(videoHeight));
            }
        }

        return (outRegionPixels.size() / 2) >= 3;
    }
}

bool parseRecognitionRegionsPixels(
    const std::string& normalizedRegions,
    int videoWidth,
    int videoHeight,
    std::vector<std::vector<double>>& outRegionsPixels,
    std::string& errMsg)
{
    outRegionsPixels.clear();
    errMsg.clear();

    if (videoWidth <= 0 || videoHeight <= 0) {
        errMsg = "invalid video size";
        return false;
    }

    std::string raw = trim_copy(normalizedRegions);
    if (raw.empty()) {
        errMsg = "empty recognitionRegion";
        return false;
    }

    std::vector<std::string> regionStrings = split(raw, ";");
    if (regionStrings.empty()) {
        regionStrings.push_back(raw);
    }

    for (const auto& regionStrRaw : regionStrings) {
        std::string regionStr = trim_copy(regionStrRaw);
        if (regionStr.empty()) {
            continue;
        }

        std::vector<double> regionPixels;
        if (!parse_region_pixels(regionStr, videoWidth, videoHeight, regionPixels)) {
            continue;
        }

        outRegionsPixels.push_back(std::move(regionPixels));
    }

    if (outRegionsPixels.empty()) {
        errMsg = "no valid regions parsed";
        return false;
    }

    return true;
}

double calcMaxCoverageRatio(
    const std::vector<std::vector<double>>& regionPixels,
    const std::vector<double>& objectPixels)
{
    if (regionPixels.empty()) {
        return 0.0;
    }
    if (objectPixels.size() < 6 || (objectPixels.size() % 2) != 0) {
        return 0.0;
    }

	    double best = 0.0;
	    for (const auto& region : regionPixels) {
	        if (region.size() < 6 || (region.size() % 2) != 0) {
	            continue;
	        }
	        if (const double ratio = CalcuPolygonIOU(region, objectPixels); ratio > best) {
	            best = ratio;
	        }
	        if (best >= 1.0) {
	            return 1.0;
	        }
	    }
    if (best < 0.0) {
        best = 0.0;
    }
    if (best > 1.0) {
        best = 1.0;
    }
    return best;
}

} // namespace AVSAnalyzer
