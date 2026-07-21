#ifndef ANALYZER_ALGORITHM_TEST_INFER_VALIDATION_H
#define ANALYZER_ALGORITHM_TEST_INFER_VALIDATION_H

#include <json/json.h>

#include <string>

namespace AVSAnalyzer {

// Validate params for /api/algorithm/testInfer.
// This helper is side-effect free for unit testing.
bool validate_algorithm_test_infer_request(const Json::Value& root, std::string& errMsg);

} // namespace AVSAnalyzer

#endif // ANALYZER_ALGORITHM_TEST_INFER_VALIDATION_H
