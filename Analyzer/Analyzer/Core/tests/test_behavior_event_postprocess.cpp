#include "BehaviorEventPostprocess.h"

#include <cassert>
#include <cstdint>
#include <vector>

using namespace AVSAnalyzer;

int main() {
    // Default enable for builtin absence/unattended object codes.
    {
        auto cfg = parseBehaviorEventPostprocessConfig("{}", "absence");
        assert(cfg.enabled);
        assert(cfg.mode == BehaviorEventPostprocessMode::Absence);
        assert(cfg.thresholdMs == 3000);
    }
    {
        auto cfg = parseBehaviorEventPostprocessConfig("{\"absenceSeconds\":1}", "absence");
        assert(cfg.enabled);
        assert(cfg.mode == BehaviorEventPostprocessMode::Absence);
        assert(cfg.thresholdMs == 1000);
    }
    {
        auto cfg = parseBehaviorEventPostprocessConfig("{\"unattendedSeconds\":2}", "unattended");
        assert(cfg.enabled);
        assert(cfg.mode == BehaviorEventPostprocessMode::Unattended);
        assert(cfg.thresholdMs == 2000);
    }
    {
        // v4.437-5: legacy NOONE alias should inherit absence postprocess defaults.
        auto cfg = parseBehaviorEventPostprocessConfig("{}", "noone");
        assert(cfg.enabled);
        assert(cfg.mode == BehaviorEventPostprocessMode::Absence);
        assert(cfg.thresholdMs == 3000);
    }
    {
        // v4.437-5: legacy LEAVE alias should inherit unattended postprocess defaults.
        auto cfg = parseBehaviorEventPostprocessConfig("{}", "leave");
        assert(cfg.enabled);
        assert(cfg.mode == BehaviorEventPostprocessMode::Unattended);
        assert(cfg.thresholdMs == 3000);
    }

    // Opt-in enable via behaviorConfig.postprocess for other object codes.
    {
        auto cfg = parseBehaviorEventPostprocessConfig("{\"postprocess\":\"absence\",\"thresholdSeconds\":2}", "person");
        assert(cfg.enabled);
        assert(cfg.mode == BehaviorEventPostprocessMode::Absence);
        assert(cfg.thresholdMs == 2000);
    }

    // Gate behavior: must be continuously true for thresholdMs.
    {
        BehaviorEventPostprocessConfig cfg;
        cfg.enabled = true;
        cfg.mode = BehaviorEventPostprocessMode::Absence;
        cfg.thresholdMs = 2000;
        BehaviorEventPostprocessor p(cfg);

        assert(p.update(/*rawHappen=*/true, /*nowMs=*/0) == false);
        assert(p.update(true, 1000) == false);
        assert(p.update(true, 1999) == false);
        assert(p.update(true, 2000) == true);
        assert(p.update(true, 2500) == true);

        // reset on false
        assert(p.update(false, 2600) == false);
        assert(p.update(true, 4000) == false);
        assert(p.update(true, 6000) == true);
    }

    // Per-region gate: each region has its own timer.
    {
        BehaviorEventPostprocessConfig cfg;
        cfg.enabled = true;
        cfg.mode = BehaviorEventPostprocessMode::Absence;
        cfg.thresholdMs = 1000;

        PerRegionBehaviorEventPostprocessor p;
        p.setConfig(cfg, 2);
        assert(p.enabled());
        assert(p.regionCount() == 2);

        // Region 0: continuous true triggers.
        assert(p.update(std::vector<bool>{true, false}, 0) == -1);
        assert(p.update(std::vector<bool>{true, false}, 999) == -1);
        assert(p.update(std::vector<bool>{true, false}, 1000) == 0);

        // Alternating shouldn't accumulate.
        p.reset();
        assert(p.update(std::vector<bool>{true, false}, 0) == -1);
        assert(p.update(std::vector<bool>{false, true}, 500) == -1);
        assert(p.update(std::vector<bool>{true, false}, 1000) == -1);
        assert(p.update(std::vector<bool>{false, true}, 1500) == -1);
        assert(p.update(std::vector<bool>{false, true}, 2499) == -1);
        assert(p.update(std::vector<bool>{false, true}, 2500) == 1);
    }

    return 0;
}
