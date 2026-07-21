#include "FaceDb.h"

#include <algorithm>
#include <cassert>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <limits>
#include <random>
#include <string>
#include <utility>
#include <vector>

#include "ReidFeature.h"

namespace AVSAnalyzer {
    namespace {
        struct FileHeaderV1 {
            char magic[8];
            uint32_t version;
            uint32_t dim;
            uint32_t count;
        };

        constexpr char kMagicV1[8] = {'B', 'E', 'A', 'F', 'A', 'C', 'E', '1'};
        constexpr uint32_t kVersionV1 = 1;

        bool read_exact(std::istream& in, char* buf, size_t n) {
            if (n == 0) {
                return true;
            }
            in.read(buf, static_cast<std::streamsize>(n));
            return in.good();
        }

        bool write_exact(std::ostream& out, const char* buf, size_t n) {
            if (n == 0) {
                return true;
            }
            out.write(buf, static_cast<std::streamsize>(n));
            return out.good();
        }

        int64_t now_ms() {
            using namespace std::chrono;
            return duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count();
        }

        std::string safe_trim_id(std::string value) {
            // Keep minimal here: remove surrounding whitespace.
            auto is_space = [](unsigned char c) { return std::isspace(c) != 0; };
            while (!value.empty() && is_space(static_cast<unsigned char>(value.front()))) {
                value.erase(value.begin());
            }
            while (!value.empty() && is_space(static_cast<unsigned char>(value.back()))) {
                value.pop_back();
            }
            return value;
        }

        float clamp_float(float v, float lo, float hi) {
            if (!std::isfinite(v)) return lo;
            if (v < lo) return lo;
            if (v > hi) return hi;
            return v;
        }
    } // namespace

    FaceDb::FaceDb(std::string dbPath) : mDbPath(std::move(dbPath)) {}
	    FaceDb::~FaceDb() = default;

	    size_t FaceDb::count() const {
	        std::scoped_lock lock(mMtx);
	        return mItems.size();
	    }

	    int FaceDb::embeddingDim() const {
	        std::scoped_lock lock(mMtx);
	        return mDim;
	    }

	    std::vector<FaceItem> FaceDb::listAll() const {
	        std::scoped_lock lock(mMtx);
	        return mItems;
	    }

	    std::vector<FaceItemMeta> FaceDb::listAllMeta() const {
	        std::scoped_lock lock(mMtx);
	        std::vector<FaceItemMeta> out;
	        out.reserve(mItems.size());
	        for (const auto& it : mItems) {
	            FaceItemMeta m;
            m.id = it.id;
            m.name = it.name;
            m.enabled = it.enabled;
            m.createdAtMs = it.createdAtMs;
            out.push_back(std::move(m));
        }
        return out;
    }

    float FaceDb::normalizedL2Distance(const std::vector<float>& a, const std::vector<float>& b) const {
        if (a.empty() || b.empty() || a.size() != b.size()) {
            return std::numeric_limits<float>::infinity();
        }

        // Assume both are L2-normalized (best-effort).
        // dist^2 = ||a - b||^2 = 2 - 2*dot(a,b)  (when both norms are 1)
        double dot = 0.0;
        for (size_t i = 0; i < a.size(); ++i) {
            const double va = std::isfinite(a[i]) ? static_cast<double>(a[i]) : 0.0;
            const double vb = std::isfinite(b[i]) ? static_cast<double>(b[i]) : 0.0;
            dot += va * vb;
        }
        double dist2 = 2.0 - 2.0 * dot;
        if (!(dist2 >= 0.0)) dist2 = 0.0;
        return static_cast<float>(std::sqrt(dist2));
    }

    void FaceDb::rebuildIndexLocked() {
        mNodes.clear();
        mRoot = -1;
        if (mItems.empty()) {
            return;
        }
        std::vector<int> indices;
        indices.reserve(mItems.size());
        for (size_t i = 0; i < mItems.size(); ++i) {
            if (!mItems[i].enabled) {
                continue;
            }
            if (mDim > 0 && static_cast<int>(mItems[i].embedding.size()) != mDim) {
                continue;
            }
            indices.push_back(static_cast<int>(i));
        }
        if (indices.empty()) {
            return;
        }
        mRoot = buildNodeLocked(indices);
    }

    int FaceDb::buildNodeLocked(std::vector<int>& indices) {
        if (indices.empty()) {
            return -1;
        }

        // Choose a pivot deterministically for test stability.
        const int pivot = indices.back();
        indices.pop_back();

        const auto nodeIndex = static_cast<int>(mNodes.size());
        mNodes.push_back(VpNode{pivot, 0.0f, -1, -1});

        if (indices.empty()) {
            return nodeIndex;
        }

        // Compute distances to pivot.
        std::vector<std::pair<float, int>> dists;
        dists.reserve(indices.size());
        for (int idx : indices) {
            const float d = normalizedL2Distance(mItems[pivot].embedding, mItems[idx].embedding);
            dists.emplace_back(d, idx);
        }

        const size_t median = dists.size() / 2;
        std::nth_element(dists.begin(), dists.begin() + static_cast<std::ptrdiff_t>(median), dists.end(),
                         [](const auto& a, const auto& b) { return a.first < b.first; });
        const float threshold = dists[median].first;
        mNodes[static_cast<size_t>(nodeIndex)].threshold = threshold;

        std::vector<int> inner;
        std::vector<int> outer;
        inner.reserve(dists.size());
        outer.reserve(dists.size());
        for (const auto& p : dists) {
            if (p.first < threshold) {
                inner.push_back(p.second);
            }
            else {
                outer.push_back(p.second);
            }
        }

        mNodes[static_cast<size_t>(nodeIndex)].left = buildNodeLocked(inner);
        mNodes[static_cast<size_t>(nodeIndex)].right = buildNodeLocked(outer);
        return nodeIndex;
    }

    void FaceDb::searchNodeLocked(int nodeIndex, const std::vector<float>& query, int& bestIndex, float& bestDist, size_t& visited) const {
        if (nodeIndex < 0) {
            return;
        }
        if (nodeIndex >= static_cast<int>(mNodes.size())) {
            return;
        }

        ++visited;
        const VpNode& node = mNodes[static_cast<size_t>(nodeIndex)];
        if (node.pivot < 0 || node.pivot >= static_cast<int>(mItems.size())) {
            return;
        }
        const FaceItem& pivot = mItems[static_cast<size_t>(node.pivot)];
        if (!pivot.enabled) {
            return;
        }
        const float dist = normalizedL2Distance(query, pivot.embedding);
        if (dist < bestDist) {
            bestDist = dist;
            bestIndex = node.pivot;
        }

        const float threshold = node.threshold;
        if (node.left < 0 && node.right < 0) {
            return;
        }

        // Branch-and-bound
        if (dist < threshold) {
            if (dist - bestDist <= threshold) {
                searchNodeLocked(node.left, query, bestIndex, bestDist, visited);
            }
            if (dist + bestDist >= threshold) {
                searchNodeLocked(node.right, query, bestIndex, bestDist, visited);
            }
        }
        else {
            if (dist + bestDist >= threshold) {
                searchNodeLocked(node.right, query, bestIndex, bestDist, visited);
            }
            if (dist - bestDist <= threshold) {
                searchNodeLocked(node.left, query, bestIndex, bestDist, visited);
            }
        }
	    }

	    bool FaceDb::upsert(const FaceItem& item, std::string& errMsg) {
	        std::scoped_lock lock(mMtx);
	        errMsg.clear();

	        FaceItem in = item;
	        in.id = safe_trim_id(in.id);
        if (in.id.empty()) {
            errMsg = "id is required";
            return false;
        }
        if (in.embedding.empty()) {
            errMsg = "embedding is required";
            return false;
        }
        if (mDim <= 0) {
            mDim = static_cast<int>(in.embedding.size());
        }
        if (static_cast<int>(in.embedding.size()) != mDim) {
            errMsg = "embedding dim mismatch";
            return false;
        }
        if (in.createdAtMs <= 0) {
            in.createdAtMs = now_ms();
        }

        // Normalize embedding for cosine/L2 metrics.
        reid_l2_normalize(in.embedding);

        bool updated = false;
        for (auto& e : mItems) {
            if (e.id == in.id) {
                // Keep original createdAt for auditability.
                const int64_t created = e.createdAtMs;
                e = in;
                if (created > 0) {
                    e.createdAtMs = created;
                }
                updated = true;
                break;
            }
        }
        if (!updated) {
            mItems.push_back(std::move(in));
        }

        rebuildIndexLocked();
        return true;
	    }

	    bool FaceDb::remove(const std::string& id, std::string& errMsg) {
	        std::scoped_lock lock(mMtx);
	        errMsg.clear();
	        const std::string key = safe_trim_id(id);
	        if (key.empty()) {
	            errMsg = "id is required";
            return false;
        }
        const auto it = std::remove_if(mItems.begin(), mItems.end(), [&](const FaceItem& e) {
            return e.id == key;
        });
        if (it == mItems.end()) {
            errMsg = "not found";
            return false;
        }
        mItems.erase(it, mItems.end());
        if (mItems.empty()) {
            mDim = 0;
        }
        rebuildIndexLocked();
        return true;
	    }

	    bool FaceDb::searchNearest(const std::vector<float>& embedding, FaceMatch& out, std::string& errMsg) const {
	        std::scoped_lock lock(mMtx);
	        errMsg.clear();
	        out = FaceMatch{};

        if (mItems.empty() || mDim <= 0) {
            errMsg = "empty db";
            return false;
        }
        if (static_cast<int>(embedding.size()) != mDim) {
            errMsg = "embedding dim mismatch";
            return false;
        }

        std::vector<float> query = embedding;
        reid_l2_normalize(query);

        if (mRoot < 0 || mNodes.empty()) {
            // Fallback: linear scan (should be rare)
            int bestIndex = -1;
            float bestDist = std::numeric_limits<float>::infinity();
            for (size_t i = 0; i < mItems.size(); ++i) {
                if (!mItems[i].enabled) {
                    continue;
                }
                const float d = normalizedL2Distance(query, mItems[i].embedding);
                if (d < bestDist) {
                    bestDist = d;
                    bestIndex = static_cast<int>(i);
                }
            }
            if (bestIndex < 0) {
                errMsg = "no enabled face";
                return false;
            }
            const FaceItem& e = mItems[static_cast<size_t>(bestIndex)];
            out.id = e.id;
            out.name = e.name;
            out.distance = bestDist;
            out.score = reid_cosine_similarity(query, e.embedding);
            out.score = clamp_float(out.score, -1.0f, 1.0f);
            return true;
        }

        int bestIndex = -1;
        float bestDist = std::numeric_limits<float>::infinity();
        size_t visited = 0;
        searchNodeLocked(mRoot, query, bestIndex, bestDist, visited);
        if (bestIndex < 0) {
            errMsg = "not found";
            return false;
        }

        const FaceItem& e = mItems[static_cast<size_t>(bestIndex)];
        out.id = e.id;
        out.name = e.name;
        out.distance = bestDist;
        out.score = reid_cosine_similarity(query, e.embedding);
        out.score = clamp_float(out.score, -1.0f, 1.0f);
        (void)visited;
        return true;
	    }

	    bool FaceDb::loadFromDisk(std::string& errMsg) {
	        std::scoped_lock lock(mMtx);
	        errMsg.clear();

        mItems.clear();
        mNodes.clear();
        mRoot = -1;
        mDim = 0;

        if (mDbPath.empty()) {
            // In-memory only.
            return true;
        }

        if (!std::filesystem::exists(mDbPath)) {
            return true;
        }

        std::ifstream in(mDbPath, std::ios::binary);
        if (!in.is_open()) {
            errMsg = "failed to open db";
            return false;
        }

        FileHeaderV1 h{};
        if (!read_exact(in, reinterpret_cast<char*>(&h), sizeof(h))) {
            errMsg = "invalid header";
            return false;
        }
        if (std::memcmp(h.magic, kMagicV1, sizeof(kMagicV1)) != 0) {
            errMsg = "invalid magic";
            return false;
        }
        if (h.version != kVersionV1) {
            errMsg = "unsupported version";
            return false;
        }
        if (h.dim == 0 || h.dim > 8192) {
            errMsg = "invalid dim";
            return false;
        }
        if (h.count > 5000000u) {
            errMsg = "invalid count";
            return false;
        }
        mDim = static_cast<int>(h.dim);

        mItems.reserve(h.count);
        for (uint32_t i = 0; i < h.count; ++i) {
            uint32_t idLen = 0;
            uint32_t nameLen = 0;
            uint8_t enabled = 1;
            uint64_t createdAtMs = 0;
            if (!read_exact(in, reinterpret_cast<char*>(&idLen), sizeof(idLen)) || idLen == 0 || idLen > 1024 * 4) {
                errMsg = "invalid id length";
                return false;
            }
            std::string id(idLen, '\0');
            if (!read_exact(in, id.data(), idLen)) {
                errMsg = "invalid id data";
                return false;
            }
            if (!read_exact(in, reinterpret_cast<char*>(&nameLen), sizeof(nameLen)) || nameLen > 1024 * 16) {
                errMsg = "invalid name length";
                return false;
            }
            std::string name;
            if (nameLen > 0) {
                name.resize(nameLen, '\0');
                if (!read_exact(in, name.data(), nameLen)) {
                    errMsg = "invalid name data";
                    return false;
                }
            }
            if (!read_exact(in, reinterpret_cast<char*>(&enabled), sizeof(enabled))) {
                errMsg = "invalid enabled";
                return false;
            }
            if (!read_exact(in, reinterpret_cast<char*>(&createdAtMs), sizeof(createdAtMs))) {
                errMsg = "invalid createdAt";
                return false;
            }

            std::vector<float> emb;
            emb.resize(static_cast<size_t>(mDim));
            if (!read_exact(in, reinterpret_cast<char*>(emb.data()), sizeof(float) * emb.size())) {
                errMsg = "invalid embedding";
                return false;
            }
            reid_l2_normalize(emb);

            FaceItem e;
            e.id = std::move(id);
            e.name = std::move(name);
            e.enabled = (enabled != 0);
            e.createdAtMs = static_cast<int64_t>(createdAtMs);
            e.embedding = std::move(emb);
            mItems.push_back(std::move(e));
        }

        rebuildIndexLocked();
        return true;
	    }

	    bool FaceDb::persistToDisk(std::string& errMsg) const {
	        std::scoped_lock lock(mMtx);
	        errMsg.clear();

        if (mDbPath.empty()) {
            errMsg = "dbPath is empty";
            return false;
        }

        std::filesystem::path p(mDbPath);
        std::error_code ec;
        if (p.has_parent_path()) {
            std::filesystem::create_directories(p.parent_path(), ec);
        }

        const std::string tmpPath = mDbPath + ".tmp";
        std::ofstream out(tmpPath, std::ios::binary | std::ios::trunc);
        if (!out.is_open()) {
            errMsg = "failed to open tmp file";
            return false;
        }

        FileHeaderV1 h{};
        std::memcpy(h.magic, kMagicV1, sizeof(kMagicV1));
        h.version = kVersionV1;
        h.dim = static_cast<uint32_t>(mDim > 0 ? mDim : 0);
        h.count = static_cast<uint32_t>(mItems.size());
        if (h.dim == 0 && !mItems.empty()) {
            h.dim = static_cast<uint32_t>(mItems[0].embedding.size());
        }
        if (h.dim == 0) {
            h.dim = 0;
        }

        if (!write_exact(out, reinterpret_cast<const char*>(&h), sizeof(h))) {
            errMsg = "failed to write header";
            return false;
        }

        for (const auto& e : mItems) {
            const std::string id = e.id;
            const std::string name = e.name;
            const auto idLen = static_cast<uint32_t>(id.size());
            const auto nameLen = static_cast<uint32_t>(name.size());
            const uint8_t enabled = e.enabled ? uint8_t(1) : uint8_t(0);
            const auto createdAtMs = static_cast<uint64_t>(std::max<int64_t>(0, e.createdAtMs));

            if (idLen == 0 || idLen > 1024 * 4) {
                errMsg = "invalid id";
                return false;
            }
            if (nameLen > 1024 * 16) {
                errMsg = "invalid name";
                return false;
            }
            if (static_cast<uint32_t>(e.embedding.size()) != h.dim) {
                errMsg = "embedding dim mismatch";
                return false;
            }

            if (!write_exact(out, reinterpret_cast<const char*>(&idLen), sizeof(idLen)) ||
                !write_exact(out, id.data(), id.size()) ||
                !write_exact(out, reinterpret_cast<const char*>(&nameLen), sizeof(nameLen)) ||
                (nameLen > 0 && !write_exact(out, name.data(), name.size())) ||
                !write_exact(out, reinterpret_cast<const char*>(&enabled), sizeof(enabled)) ||
                !write_exact(out, reinterpret_cast<const char*>(&createdAtMs), sizeof(createdAtMs)) ||
                !write_exact(out, reinterpret_cast<const char*>(e.embedding.data()), sizeof(float) * e.embedding.size())) {
                errMsg = "failed to write record";
                return false;
            }
        }

        out.flush();
        if (!out.good()) {
            errMsg = "failed to flush";
            return false;
        }
        out.close();

        std::filesystem::rename(tmpPath, mDbPath, ec);
        if (ec) {
            errMsg = "failed to rename tmp";
            return false;
        }
        return true;
    }

} // namespace AVSAnalyzer
