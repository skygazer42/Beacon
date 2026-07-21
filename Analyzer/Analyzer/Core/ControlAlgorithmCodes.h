#ifndef ANALYZER_CONTROL_ALGORITHM_CODES_H
#define ANALYZER_CONTROL_ALGORITHM_CODES_H

#include <string>
#include <vector>

namespace AVSAnalyzer {

struct Control;

// Collect all local algorithm codes that must be bound/unbound to a Control.
// This is used to keep Scheduler refCount accurate for multi-algorithm pipeline modes.
std::vector<std::string> collectLocalAlgorithmCodes(const Control* control);

}  // namespace AVSAnalyzer

#endif  // ANALYZER_CONTROL_ALGORITHM_CODES_H

