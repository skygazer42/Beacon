#ifndef ANALYZER_SHARED_DECODE_MANAGER_H
#define ANALYZER_SHARED_DECODE_MANAGER_H

#include <map>
#include <memory>
#include <mutex>
#include <string>

namespace AVSAnalyzer {

struct SharedDecodeHandle {
    std::string key{};
};

class SharedDecodeManager {
public:
    SharedDecodeHandle* acquire(const std::string& key);
    void release(const std::string& key);
    size_t sessionCount() const;
    int refCount(const std::string& key) const;

private:
    struct Entry {
        std::unique_ptr<SharedDecodeHandle> handle;
        int refs = 0;
    };

    mutable std::mutex mMtx;
    std::map<std::string, Entry> mEntries;
};

}  // namespace AVSAnalyzer

#endif  // ANALYZER_SHARED_DECODE_MANAGER_H
