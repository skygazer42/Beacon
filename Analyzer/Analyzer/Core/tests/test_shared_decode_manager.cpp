#include "SharedDecodeKey.h"
#include "SharedDecodeManager.h"

#include <cassert>

using namespace AVSAnalyzer;

int main() {
    {
        DecodeReuseKey a = makeDecodeReuseKey("rtsp://cam-1", false, false);
        DecodeReuseKey b = makeDecodeReuseKey("rtsp://cam-1", false, false);
        DecodeReuseKey c = makeDecodeReuseKey("rtsp://cam-1", true, false);
        DecodeReuseKey d = makeDecodeReuseKey("rtsp://cam-2", false, false);

        assert(!a.value.empty());
        assert(a.value == b.value);
        assert(a.value != c.value);
        assert(a.value != d.value);
    }

    {
        SharedDecodeManager mgr;
        auto* s1 = mgr.acquire("k1");
        auto* s2 = mgr.acquire("k1");
        auto* s3 = mgr.acquire("k2");

        assert(s1 != nullptr);
        assert(s2 == s1);
        assert(s3 != nullptr);
        assert(s3 != s1);
        assert(mgr.sessionCount() == 2);
        assert(mgr.refCount("k1") == 2);
        assert(mgr.refCount("k2") == 1);

        mgr.release("k1");
        assert(mgr.sessionCount() == 2);
        assert(mgr.refCount("k1") == 1);

        mgr.release("k1");
        assert(mgr.sessionCount() == 1);
        assert(mgr.refCount("k1") == 0);

        mgr.release("k2");
        assert(mgr.sessionCount() == 0);
    }

    return 0;
}
