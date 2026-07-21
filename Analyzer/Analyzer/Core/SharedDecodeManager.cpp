#include "SharedDecodeManager.h"

namespace AVSAnalyzer {

SharedDecodeHandle* SharedDecodeManager::acquire(const std::string& key) {
    std::lock_guard<std::mutex> lock(mMtx);
    Entry& entry = mEntries[key];
    if (!entry.handle) {
        entry.handle = std::make_unique<SharedDecodeHandle>();
        entry.handle->key = key;
    }
    entry.refs++;
    return entry.handle.get();
}

void SharedDecodeManager::release(const std::string& key) {
    std::lock_guard<std::mutex> lock(mMtx);
    auto it = mEntries.find(key);
    if (it == mEntries.end()) {
        return;
    }
    if (it->second.refs > 0) {
        it->second.refs--;
    }
    if (it->second.refs <= 0) {
        mEntries.erase(it);
    }
}

size_t SharedDecodeManager::sessionCount() const {
    std::lock_guard<std::mutex> lock(mMtx);
    return mEntries.size();
}

int SharedDecodeManager::refCount(const std::string& key) const {
    std::lock_guard<std::mutex> lock(mMtx);
    auto it = mEntries.find(key);
    if (it == mEntries.end()) {
        return 0;
    }
    return it->second.refs;
}

}  // namespace AVSAnalyzer
