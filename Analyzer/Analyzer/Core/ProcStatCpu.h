#ifndef ANALYZER_PROC_STAT_CPU_H
#define ANALYZER_PROC_STAT_CPU_H

#include <cstdint>
#include <string>

namespace AVSAnalyzer {

    struct CpuTimes {
        uint64_t idle = 0;
        uint64_t total = 0;
    };

    bool parseProcStatCpuLine(const std::string& line, CpuTimes& out);
    double computeCpuUsagePercent(const CpuTimes& prev, const CpuTimes& cur);
    bool readProcStatCpuTimes(CpuTimes& out, const std::string& path = "/proc/stat");

}  // namespace AVSAnalyzer

#endif  // ANALYZER_PROC_STAT_CPU_H

