#ifndef ANALYZER_LOCAL_LICENSE_H
#define ANALYZER_LOCAL_LICENSE_H

#include <string>
#include <string_view>

namespace AVSAnalyzer {

class Config;

struct LocalLicenseInfo {
    bool ok = false;
    std::string type{};
    std::string machineCode{};
    std::string machineCodeV1{};
    std::string machineCodeV2{};
};

std::string sha256Hex(std::string_view input);
bool shouldUseLocalLicense(const Config* config);

class LocalLicense {
public:
    explicit LocalLicense(const Config* config);

    std::string getMachineCode() const;
    std::string getMachineCodeV1() const;
    std::string getMachineCodeV2() const;
    LocalLicenseInfo check() const;

private:
    bool checkDongle() const;
    bool checkMachineLicense() const;
    std::string getMachineNode() const;
    std::string getMachineCpu() const;
    std::string getMachineStableId() const;
    std::string getMacAddress() const;
    std::string getSystemName() const;

    const Config* mConfig = nullptr;
    mutable std::string mMachineCode{};
    mutable std::string mMachineCodeV1{};
    mutable std::string mMachineCodeV2{};
};

}  // namespace AVSAnalyzer

#endif  // ANALYZER_LOCAL_LICENSE_H
