#include "Algorithm.h"
#include "Config.h"
#include "Utils/Log.h"
#include "Utils/Common.h"

namespace AVSAnalyzer {
    Algorithm::Algorithm(const Config* config) :mConfig(config)
    {

    }

    Algorithm::~Algorithm() = default;
    bool Algorithm::createState() const{
        return mCreateState;
    }

}
