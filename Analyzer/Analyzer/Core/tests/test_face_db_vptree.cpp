#include "FaceDb.h"

#include <cassert>
#include <filesystem>
#include <string>
#include <unordered_set>
#include <vector>

using namespace AVSAnalyzer;

static void test_add_search_persist_reload() {
    const std::string path =
        (std::filesystem::temp_directory_path() / "beacon_test_face_db_v1.bin").string();
    std::error_code ec;
    std::filesystem::remove(path, ec);

    FaceDb db(path);
    std::string err;
    assert(db.loadFromDisk(err) == true);
    assert(db.count() == 0);

    FaceItem a;
    a.id = "alice";
    a.name = "Alice";
    a.embedding = {1.0f, 0.0f};
    assert(db.upsert(a, err) == true);

    FaceItem b;
    b.id = "bob";
    b.name = "Bob";
    b.embedding = {0.0f, 1.0f};
    assert(db.upsert(b, err) == true);
    assert(db.count() == 2);

    {
        const auto items = db.listAll();
        assert(items.size() == 2);
    }
    {
        const auto metas = db.listAllMeta();
        assert(metas.size() == 2);
        std::unordered_set<std::string> ids;
        for (const auto& m : metas) {
            ids.insert(m.id);
        }
        assert(ids.count("alice") == 1);
        assert(ids.count("bob") == 1);
    }

    FaceMatch m;
    assert(db.searchNearest(std::vector<float>{0.9f, 0.1f}, m, err) == true);
    assert(m.id == "alice");
    assert(m.score > 0.8f);

    assert(db.persistToDisk(err) == true);

    FaceDb db2(path);
    assert(db2.loadFromDisk(err) == true);
    assert(db2.count() == 2);
    {
        const auto items2 = db2.listAll();
        assert(items2.size() == 2);
    }
    {
        const auto metas2 = db2.listAllMeta();
        assert(metas2.size() == 2);
    }

    FaceMatch m2;
    assert(db2.searchNearest(std::vector<float>{0.1f, 0.9f}, m2, err) == true);
    assert(m2.id == "bob");
    assert(m2.score > 0.8f);

    std::filesystem::remove(path, ec);
}

int main() {
    test_add_search_persist_reload();
    return 0;
}
