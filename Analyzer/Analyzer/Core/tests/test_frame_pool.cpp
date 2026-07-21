#include "Frame.h"

#include <cassert>
#include <cstdlib>

namespace {

void set_env(const char* key, const char* value) {
    if (!key || !*key) {
        return;
    }
#ifdef _WIN32
    _putenv_s(key, value ? value : "");
#else
    setenv(key, value ? value : "", 1);
#endif
}

}  // namespace

using namespace AVSAnalyzer;

int main() {
    set_env("BEACON_FRAMEPOOL_MAX_FRAMES", "2");

    {
        FramePool pool(16);
        Frame* a = pool.gain();
        Frame* b = pool.gain();
        Frame* c = pool.gain();

        assert(a != nullptr);
        assert(b != nullptr);

        if (c != nullptr) {
            pool.giveBack(c);
        }
        pool.giveBack(a);
        pool.giveBack(b);

        // With BEACON_FRAMEPOOL_MAX_FRAMES=2, the 3rd allocation should be refused.
        assert(c == nullptr);

        // After returning frames, pool should be able to serve new ones again.
        Frame* d = pool.gain();
        assert(d != nullptr);
        assert(d->getCapacity() == 16);
        pool.giveBack(d);
    }

    set_env("BEACON_FRAMEPOOL_MAX_FRAMES", "1");
    {
        FramePool pool(16);
        Frame* first = pool.gain();
        assert(first != nullptr);
        assert(first->getCapacity() == 16);

        // resetSize() should invalidate returned in-flight frames with stale capacity.
        pool.resetSize(32);
        pool.giveBack(first);

        Frame* second = pool.gain();
        assert(second != nullptr);
        assert(second->getCapacity() == 32);
        pool.giveBack(second);

        // resetSize() should also clear idle frames so the next gain uses the new size.
        pool.resetSize(48);
        Frame* third = pool.gain();
        assert(third != nullptr);
        assert(third->getCapacity() == 48);
        pool.giveBack(third);
    }

    return 0;
}
