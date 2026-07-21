#include "Config.h"
#include "LocalLicense.h"

#include <cassert>
#include <filesystem>
#include <fstream>
#include <string>

using namespace AVSAnalyzer;

namespace {

std::filesystem::path writeConfigFile(const std::string& name, const std::string& body) {
    const auto dir = std::filesystem::temp_directory_path() / "beacon_local_license_tests";
    std::filesystem::create_directories(dir);
    const auto path = dir / name;
    std::ofstream ofs(path, std::ios::binary);
    ofs << body;
    ofs.close();
    return path;
}

}  // namespace

int main() {
    {
        const auto cfgPath = writeConfigFile(
            "config_internal_admin_host.json",
            R"({
  "host": "0.0.0.0",
  "adminPort": 9991,
  "analyzerPort": 9993,
  "mediaHttpPort": 9992,
  "mediaRtspPort": 9994
})");
        Config cfg(cfgPath.string().c_str());
        assert(cfg.host == "0.0.0.0");
        assert(cfg.adminHost == "http://127.0.0.1:9991");
    }

    {
        const auto cfgPath = writeConfigFile(
            "config_local_license.json",
            R"({
  "host": "127.0.0.1",
  "adminPort": 9527,
  "analyzerPort": 9528,
  "mediaHttpPort": 8081,
  "mediaRtspPort": 554,
  "licenseType": "dongle",
  "licenseKey": " test-key ",
  "licenseDongleCmd": "probe-cmd",
  "licenseDongleFile": "license.dongle"
})");

        Config cfg(cfgPath.string().c_str());
        assert(cfg.licenseType == "dongle");
        assert(cfg.licenseKey == "test-key");
        assert(cfg.licenseDongleCmd == "probe-cmd");
        assert(cfg.licenseDongleFile == (cfgPath.parent_path() / "license.dongle").lexically_normal().string());
    }

    {
        const auto cfgPath = writeConfigFile(
            "config_machine.json",
            R"({
  "host": "127.0.0.1",
  "adminPort": 9527,
  "analyzerPort": 9528,
  "mediaHttpPort": 8081,
  "mediaRtspPort": 554
})");
        Config cfg(cfgPath.string().c_str());
        cfg.licenseType = "machine";

        LocalLicense local(&cfg);
        const std::string v1 = local.getMachineCodeV1();
        const std::string v2 = local.getMachineCodeV2();
        assert(!v1.empty());
        assert(!v2.empty());

        cfg.licenseKey = "  " + v2 + "\n";
        LocalLicenseInfo info = LocalLicense(&cfg).check();
        assert(info.ok);
        assert(info.type == "machine");
        assert(info.machineCode == info.machineCodeV2);
        assert(info.machineCodeV1 == v1);
        assert(info.machineCodeV2 == v2);

        cfg.licenseKey = sha256Hex(v1);
        info = LocalLicense(&cfg).check();
        assert(info.ok);
    }

    {
        const auto cfgPath = writeConfigFile(
            "config_dongle.json",
            R"({
  "host": "127.0.0.1",
  "adminPort": 9527,
  "analyzerPort": 9528,
  "mediaHttpPort": 8081,
  "mediaRtspPort": 554
})");
        Config cfg(cfgPath.string().c_str());
        cfg.licenseType = "dongle";
        cfg.licenseDongleCmd = "this_command_should_not_exist_12345";

        const auto sentinel = cfgPath.parent_path() / "license.ok";
        {
            std::ofstream ofs(sentinel, std::ios::binary);
            ofs << "ok\n";
        }
        cfg.licenseDongleFile = sentinel.string();

        LocalLicenseInfo info = LocalLicense(&cfg).check();
        assert(info.ok);
        assert(info.type == "dongle");
    }

    {
        const auto cfgPath = writeConfigFile(
            "config_license_type.json",
            R"({
  "host": "127.0.0.1",
  "adminPort": 9527,
  "analyzerPort": 9528,
  "mediaHttpPort": 8081,
  "mediaRtspPort": 554
})");
        Config cfg(cfgPath.string().c_str());
        cfg.licenseType = "machine";
        assert(shouldUseLocalLicense(&cfg));
        cfg.licenseType = "dongle";
        assert(shouldUseLocalLicense(&cfg));
        cfg.licenseType = "pool";
        assert(!shouldUseLocalLicense(&cfg));
        cfg.licenseType = "manager";
        assert(!shouldUseLocalLicense(&cfg));
        cfg.licenseType = "community";
        assert(!shouldUseLocalLicense(&cfg));
        assert(LocalLicense(&cfg).check().ok);
    }

    return 0;
}
