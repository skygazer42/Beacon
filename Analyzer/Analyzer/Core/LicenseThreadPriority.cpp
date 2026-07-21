#include "LicenseThreadPriority.h"

#include <algorithm>
#include <cerrno>
#include <cstring>
#include <limits>

#if defined(__linux__)
#include <pthread.h>
#include <sched.h>
#include <sys/resource.h>
#include <sys/syscall.h>
#include <unistd.h>
#endif

namespace AVSAnalyzer {

namespace {

int clampSignedToInt(long long value) {
    if (value < static_cast<long long>(std::numeric_limits<int>::min())) {
        return std::numeric_limits<int>::min();
    }
    if (value > static_cast<long long>(std::numeric_limits<int>::max())) {
        return std::numeric_limits<int>::max();
    }
    return static_cast<int>(value);
}

int clampUnsignedToInt(unsigned long long value) {
    if (value > static_cast<unsigned long long>(std::numeric_limits<int>::max())) {
        return std::numeric_limits<int>::max();
    }
    return static_cast<int>(value);
}

int parseIntOrDefault(const Json::Value& value, int defaultValue) {
    if (value.isInt()) {
        return value.asInt();
    }
    if (value.isUInt()) {
        return clampUnsignedToInt(static_cast<unsigned long long>(value.asUInt()));
    }
    if (value.isInt64()) {
        return clampSignedToInt(static_cast<long long>(value.asInt64()));
    }
    if (value.isUInt64()) {
        return clampUnsignedToInt(static_cast<unsigned long long>(value.asUInt64()));
    }
    if (value.isString()) {
        try {
            return clampSignedToInt(std::stoll(value.asString()));
        }
        catch (...) {
            return defaultValue;
        }
    }
    return defaultValue;
}

}  // namespace

int clampThreadNiceValue(int value) {
    return std::max(-20, std::min(19, value));
}

LicenseThreadPriorityHint parseLicenseThreadPriorityHint(const Json::Value& raw) {
    LicenseThreadPriorityHint hint;
    if (!raw.isObject()) {
        return hint;
    }

    hint.enabled = raw.get("enabled", false).asBool();
    hint.streamRank = std::max(0, parseIntOrDefault(raw["stream_rank"], 0));
    hint.firstNActiveStreams = std::max(0, parseIntOrDefault(raw["first_n_active_streams"], 0));
    hint.niceValue = clampThreadNiceValue(parseIntOrDefault(raw["nice_value"], 0));
    return hint;
}

bool isThreadPriorityBoostActive(const LicenseThreadPriorityHint& hint) {
    return hint.enabled && hint.streamRank > 0 && hint.firstNActiveStreams > 0 && hint.streamRank <= hint.firstNActiveStreams;
}

int targetThreadNiceValue(const LicenseThreadPriorityHint& hint) {
    return isThreadPriorityBoostActive(hint) ? clampThreadNiceValue(hint.niceValue) : 0;
}

bool applyCurrentThreadPriorityBestEffort(const LicenseThreadPriorityHint& hint, std::string* errMsg) {
    if (!isThreadPriorityBoostActive(hint)) {
        if (errMsg) {
            errMsg->clear();
        }
        return true;
    }

    const int targetNice = targetThreadNiceValue(hint);

#if defined(__linux__)
    const pid_t tid = static_cast<pid_t>(syscall(SYS_gettid));
    if (tid <= 0) {
        if (errMsg) {
            *errMsg = "gettid_failed";
        }
        return false;
    }

    errno = 0;
    if (setpriority(PRIO_PROCESS, static_cast<id_t>(tid), targetNice) == 0) {
        if (errMsg) {
            errMsg->clear();
        }
        return true;
    }

    if (errMsg) {
        *errMsg = std::strerror(errno);
    }
    return false;
#else
    if (targetNice == 0) {
        if (errMsg) {
            errMsg->clear();
        }
        return true;
    }
    if (errMsg) {
        *errMsg = "unsupported_platform";
    }
    return false;
#endif
}

}  // namespace AVSAnalyzer
