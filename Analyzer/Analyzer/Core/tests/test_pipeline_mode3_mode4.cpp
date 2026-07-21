#include "PipelineModeAdvanced.h"

#include <cmath>
#include <string>
#include <vector>

namespace {

AVSAnalyzer::Control makeControl() {
    AVSAnalyzer::Control control;
    control.objectCode = "truck";
    control.objects_v1 = {"sedan", "truck"};
    control.objects_v1_len = static_cast<int>(control.objects_v1.size());
    return control;
}

AVSAnalyzer::DetectObject makeDetect(const std::string& className, int classId, float score) {
    AVSAnalyzer::DetectObject detect;
    detect.class_name = className;
    detect.class_id = classId;
    detect.class_score = score;
    return detect;
}

}  // namespace

int main() {
    AVSAnalyzer::Control control = makeControl();

    // mode 3: ROI classifier output should override detector labels with classification labels.
    AVSAnalyzer::DetectObject roiDetect = makeDetect("car", 0, 0.30f);
    const AVSAnalyzer::DetectObject roiClassResult = makeDetect("", 1, 0.92f);
    AVSAnalyzer::applyPipelineClassificationResult(&control, roiClassResult, roiDetect);
    if (roiDetect.class_name != "truck") {
        return 10;
    }
    if (std::fabs(roiDetect.class_score - 0.92f) > 1e-6f) {
        return 11;
    }
    if (!AVSAnalyzer::pipelineDetectMatchesObjectCode(&control, roiDetect)) {
        return 12;
    }

    // mode 3: explicit classifier labels should remain stable and still match non-ResNet targets.
    AVSAnalyzer::DetectObject roiNamedDetect = makeDetect("car", 0, 0.30f);
    const AVSAnalyzer::DetectObject roiNamedClassResult = makeDetect("truck", 1, 0.91f);
    AVSAnalyzer::applyPipelineClassificationResult(&control, roiNamedClassResult, roiNamedDetect);
    if (roiNamedDetect.class_name != "truck") {
        return 13;
    }
    if (!AVSAnalyzer::pipelineDetectMatchesObjectCode(&control, roiNamedDetect)) {
        return 14;
    }

    // mode 4: frame classifier output with only class_id should still map to configured labels.
    AVSAnalyzer::DetectObject frameClassResult = makeDetect("", 1, 0.88f);
    AVSAnalyzer::fillPipelineClassNameFromControl(&control, frameClassResult);
    if (frameClassResult.class_name != "truck") {
        return 20;
    }
    if (!AVSAnalyzer::pipelineDetectMatchesObjectCode(&control, frameClassResult)) {
        return 21;
    }

    // out-of-range class ids must not create a false positive match.
    AVSAnalyzer::DetectObject unknownClass = makeDetect("", 9, 0.50f);
    AVSAnalyzer::fillPipelineClassNameFromControl(&control, unknownClass);
    if (!unknownClass.class_name.empty()) {
        return 30;
    }
    if (AVSAnalyzer::pipelineDetectMatchesObjectCode(&control, unknownClass)) {
        return 31;
    }

    return 0;
}
