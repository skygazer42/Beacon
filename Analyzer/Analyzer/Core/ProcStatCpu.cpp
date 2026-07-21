#include "ProcStatCpu.h"

#include <algorithm>
#include <fstream>
#include <sstream>

namespace AVSAnalyzer {

    bool parseProcStatCpuLine(const std::string& line, CpuTimes& out) {
        out = CpuTimes{};
        if (line.empty()) {
            return false;
        }

        std::istringstream iss(line);
        std::string tag;
        if (!(iss >> tag)) {
            return false;
        }
        if (tag != "cpu") {
            return false;
        }

        uint64_t user = 0;
        uint64_t nice = 0;
        uint64_t system = 0;
        uint64_t idle = 0;
        uint64_t iowait = 0;
        uint64_t irq = 0;
        uint64_t softirq = 0;
        uint64_t steal = 0;
        // guest fields are optional and not counted in total the same way; ignore

        if (!(iss >> user >> nice >> system >> idle)) {
            return false;
        }

        // Optional fields (kernel version dependent)
        iss >> iowait >> irq >> softirq >> steal;

        uint64_t idleAll = idle + iowait;
        uint64_t nonIdle = user + nice + system + irq + softirq + steal;
        uint64_t total = idleAll + nonIdle;

        out.idle = idleAll;
        out.total = total;
        return true;
    }

    double computeCpuUsagePercent(const CpuTimes& prev, const CpuTimes& cur) {
        if (cur.total <= prev.total) {
            return 0.0;
        }
        uint64_t totald = cur.total - prev.total;
        if (totald == 0) {
            return 0.0;
        }

        uint64_t idled = 0;
        if (cur.idle > prev.idle) {
            idled = cur.idle - prev.idle;
        }

        double usage = (static_cast<double>(totald - idled) / static_cast<double>(totald)) * 100.0;
        if (usage < 0.0) {
            usage = 0.0;
        }
        if (usage > 100.0) {
            usage = 100.0;
        }
        return usage;
    }

    bool readProcStatCpuTimes(CpuTimes& out, const std::string& path) {
        std::ifstream ifs(path);
        if (!ifs.is_open()) {
            return false;
        }
        std::string line;
        if (!std::getline(ifs, line)) {
            return false;
        }
        return parseProcStatCpuLine(line, out);
    }

}  // namespace AVSAnalyzer

