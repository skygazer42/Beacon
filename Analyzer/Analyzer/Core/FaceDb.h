#ifndef ANALYZER_FACE_DB_H
#define ANALYZER_FACE_DB_H

#include <cstdint>
#include <mutex>
#include <string>
#include <vector>

namespace AVSAnalyzer {

    struct FaceItem {
        std::string id;
        std::string name;
        bool enabled = true;
        int64_t createdAtMs = 0;
        std::vector<float> embedding;
    };

    // Lightweight view for listing faces without copying embeddings.
    struct FaceItemMeta {
        std::string id;
        std::string name;
        bool enabled = true;
        int64_t createdAtMs = 0;
    };

    struct FaceMatch {
        std::string id;
        std::string name;
        float score = 0.0f;     // cosine similarity in [-1, 1]
        float distance = 0.0f;  // L2 distance on normalized vectors in [0, 2]
    };

    // Persistent face embedding database with an in-memory VP-tree index.
    // Industrial intent:
    // - Support large face libraries with sub-linear nearest search (typical case).
    // - Keep storage compact (binary file) and robust (atomic replace).
    class FaceDb {
    public:
        explicit FaceDb(std::string dbPath);
        ~FaceDb();

        bool loadFromDisk(std::string& errMsg);
        bool persistToDisk(std::string& errMsg) const;

        bool upsert(const FaceItem& item, std::string& errMsg);
        bool remove(const std::string& id, std::string& errMsg);

        std::vector<FaceItem> listAll() const;
        std::vector<FaceItemMeta> listAllMeta() const;

        bool searchNearest(const std::vector<float>& embedding, FaceMatch& out, std::string& errMsg) const;

        size_t count() const;
        int embeddingDim() const;

    private:
        struct VpNode {
            int pivot = -1;       // index into mItems
            float threshold = 0;  // median radius
            int left = -1;
            int right = -1;
        };

        void rebuildIndexLocked();
        int buildNodeLocked(std::vector<int>& indices);
        void searchNodeLocked(int nodeIndex, const std::vector<float>& query, int& bestIndex, float& bestDist, size_t& visited) const;

        float normalizedL2Distance(const std::vector<float>& a, const std::vector<float>& b) const;

        std::string mDbPath;
        int mDim = 0;
        mutable std::mutex mMtx;
        std::vector<FaceItem> mItems;

        // VP-tree index
        std::vector<VpNode> mNodes;
        int mRoot = -1;
    };

} // namespace AVSAnalyzer

#endif // ANALYZER_FACE_DB_H
