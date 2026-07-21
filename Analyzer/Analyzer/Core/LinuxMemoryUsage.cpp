#include "LinuxMemoryUsage.h"

#include <algorithm>
#include <cctype>
#include <fstream>
#include <sstream>

namespace AVSAnalyzer {

namespace {

bool parseMemInfoBytes(const std::string& line, const char* key, std::uint64_t& outBytes) {
    const std::string prefix(key);
    if (line.rfind(prefix, 0) != 0) {
        return false;
    }

    std::istringstream iss(line.substr(prefix.size()));
    std::uint64_t value = 0;
    if (!(iss >> value)) {
        return false;
    }

    std::string unit;
    if (!(iss >> unit)) {
        outBytes = value;
        return true;
    }

    std::transform(unit.begin(), unit.end(), unit.begin(),
                   [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });

    if (unit == "kb") {
        outBytes = value * 1024ULL;
        return true;
    }

    outBytes = value;
    return true;
}

}  // namespace

double computeLinuxMemoryUsagePercent(std::uint64_t totalBytes, std::uint64_t availableBytes) {
    if (totalBytes == 0) {
        return 0.0;
    }

    if (availableBytes > totalBytes) {
        availableBytes = totalBytes;
    }

    const double usage = 100.0 * (1.0 - static_cast<double>(availableBytes) / static_cast<double>(totalBytes));
    return std::clamp(usage, 0.0, 100.0);
}

bool readLinuxMemInfoAvailableBytes(std::uint64_t& totalBytes,
                                    std::uint64_t& availableBytes,
                                    const std::string& path) {
    totalBytes = 0;
    availableBytes = 0;

    std::ifstream ifs(path);
    if (!ifs.is_open()) {
        return false;
    }

    bool hasTotal = false;
    bool hasAvailable = false;
    std::string line;
    while (std::getline(ifs, line)) {
        if (!hasTotal && parseMemInfoBytes(line, "MemTotal:", totalBytes)) {
            hasTotal = true;
        }
        else if (!hasAvailable && parseMemInfoBytes(line, "MemAvailable:", availableBytes)) {
            hasAvailable = true;
        }

        if (hasTotal && hasAvailable) {
            if (availableBytes > totalBytes) {
                availableBytes = totalBytes;
            }
            return totalBytes > 0;
        }
    }

    totalBytes = 0;
    availableBytes = 0;
    return false;
}

}  // namespace AVSAnalyzer
