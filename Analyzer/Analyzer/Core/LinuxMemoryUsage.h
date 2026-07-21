#pragma once

#include <cstdint>
#include <string>

namespace AVSAnalyzer {

double computeLinuxMemoryUsagePercent(std::uint64_t totalBytes, std::uint64_t availableBytes);

bool readLinuxMemInfoAvailableBytes(std::uint64_t& totalBytes,
                                    std::uint64_t& availableBytes,
                                    const std::string& path = "/proc/meminfo");

}  // namespace AVSAnalyzer
