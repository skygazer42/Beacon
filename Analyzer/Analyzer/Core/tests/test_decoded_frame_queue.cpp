#include "DecodedFrameQueue.h"

#include <cassert>
#include <vector>

using namespace AVSAnalyzer;

int main() {
    {
        std::vector<int> released;
        DecodedFrameQueue q(2, [&](Frame* frame) {
            if (!frame) {
                return;
            }
            released.push_back(frame->regionIndex);
            delete frame;
        });

        Frame* f1 = new Frame(3);
        Frame* f2 = new Frame(3);
        Frame* f3 = new Frame(3);
        f1->regionIndex = 1;
        f2->regionIndex = 2;
        f3->regionIndex = 3;

        q.push(f1);
        q.push(f2);
        q.push(f3);

        assert(q.size() == 2);
        assert(released.size() == 1);
        assert(released[0] == 1);

        Frame* out = nullptr;
        assert(q.pop(out));
        assert(out == f2);
        delete out;

        out = nullptr;
        assert(q.pop(out));
        assert(out == f3);
        delete out;

        out = reinterpret_cast<Frame*>(0x1);
        assert(!q.pop(out));
        assert(out == nullptr);
    }

    return 0;
}
