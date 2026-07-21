#include "LocalLicense.h"

#include "Config.h"

#include <algorithm>
#include <array>
#include <chrono>
#include <cctype>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <iphlpapi.h>
#include <winreg.h>
#pragma comment(lib, "iphlpapi.lib")
#else
#include <ifaddrs.h>
#include <net/if.h>
#include <signal.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#if defined(__linux__)
#include <netpacket/packet.h>
#elif defined(__APPLE__)
#include <net/if_dl.h>
#include <sys/sysctl.h>
#endif
#endif

namespace AVSAnalyzer {

namespace {

std::string trimCopy(std::string value) {
    auto notSpace = [](unsigned char ch) { return std::isspace(ch) == 0; };
    value.erase(value.begin(), std::find_if(value.begin(), value.end(), notSpace));
    value.erase(std::find_if(value.rbegin(), value.rend(), notSpace).base(), value.end());
    return value;
}

std::string toLowerCopy(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(),
        [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    return value;
}

std::string joinParts(const std::vector<std::string>& parts) {
    std::string raw;
    bool first = true;
    for (const auto& part : parts) {
        if (!first) {
            raw.push_back('|');
        }
        first = false;
        raw.append(part);
    }
    return raw;
}

std::string bytesToHex(const unsigned char* data, size_t len) {
    std::ostringstream oss;
    oss << std::hex << std::setfill('0');
    for (size_t i = 0; i < len; ++i) {
        oss << std::setw(2) << static_cast<unsigned int>(data[i]);
    }
    return oss.str();
}

class Sha256 {
public:
    Sha256() { reset(); }

    void update(const unsigned char* data, size_t len) {
        for (size_t i = 0; i < len; ++i) {
            mData[mDataLen] = data[i];
            ++mDataLen;
            if (mDataLen == 64) {
                transform();
                mBitLen += 512;
                mDataLen = 0;
            }
        }
    }

    std::string finalHex() {
        size_t i = mDataLen;
        if (mDataLen < 56) {
            mData[i] = 0x80;
            ++i;
            while (i < 56) {
                mData[i] = 0x00;
                ++i;
            }
        }
        else {
            mData[i] = 0x80;
            ++i;
            while (i < 64) {
                mData[i] = 0x00;
                ++i;
            }
            transform();
            std::fill(mData.begin(), mData.begin() + 56, 0x00);
        }

        mBitLen += static_cast<uint64_t>(mDataLen) * 8ULL;
        mData[63] = static_cast<unsigned char>(mBitLen);
        mData[62] = static_cast<unsigned char>(mBitLen >> 8);
        mData[61] = static_cast<unsigned char>(mBitLen >> 16);
        mData[60] = static_cast<unsigned char>(mBitLen >> 24);
        mData[59] = static_cast<unsigned char>(mBitLen >> 32);
        mData[58] = static_cast<unsigned char>(mBitLen >> 40);
        mData[57] = static_cast<unsigned char>(mBitLen >> 48);
        mData[56] = static_cast<unsigned char>(mBitLen >> 56);
        transform();

        unsigned char hash[32];
        for (size_t j = 0; j < 4; ++j) {
            hash[j] = static_cast<unsigned char>((mState[0] >> (24 - j * 8)) & 0xff);
            hash[j + 4] = static_cast<unsigned char>((mState[1] >> (24 - j * 8)) & 0xff);
            hash[j + 8] = static_cast<unsigned char>((mState[2] >> (24 - j * 8)) & 0xff);
            hash[j + 12] = static_cast<unsigned char>((mState[3] >> (24 - j * 8)) & 0xff);
            hash[j + 16] = static_cast<unsigned char>((mState[4] >> (24 - j * 8)) & 0xff);
            hash[j + 20] = static_cast<unsigned char>((mState[5] >> (24 - j * 8)) & 0xff);
            hash[j + 24] = static_cast<unsigned char>((mState[6] >> (24 - j * 8)) & 0xff);
            hash[j + 28] = static_cast<unsigned char>((mState[7] >> (24 - j * 8)) & 0xff);
        }
        return bytesToHex(hash, sizeof(hash));
    }

private:
    void reset() {
        mData.fill(0);
        mDataLen = 0;
        mBitLen = 0;
        mState[0] = 0x6a09e667;
        mState[1] = 0xbb67ae85;
        mState[2] = 0x3c6ef372;
        mState[3] = 0xa54ff53a;
        mState[4] = 0x510e527f;
        mState[5] = 0x9b05688c;
        mState[6] = 0x1f83d9ab;
        mState[7] = 0x5be0cd19;
    }

    static uint32_t rotr(uint32_t x, uint32_t n) {
        return (x >> n) | (x << (32 - n));
    }

    void transform() {
        static const uint32_t k[64] = {
            0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5,
            0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
            0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
            0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
            0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
            0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
            0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
            0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
            0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
            0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
            0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
            0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
            0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5,
            0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
            0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
            0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
        };

        uint32_t m[64];
        for (size_t i = 0, j = 0; i < 16; ++i, j += 4) {
            m[i] = (static_cast<uint32_t>(mData[j]) << 24) |
                   (static_cast<uint32_t>(mData[j + 1]) << 16) |
                   (static_cast<uint32_t>(mData[j + 2]) << 8) |
                   (static_cast<uint32_t>(mData[j + 3]));
        }
        for (size_t i = 16; i < 64; ++i) {
            const uint32_t s0 = rotr(m[i - 15], 7) ^ rotr(m[i - 15], 18) ^ (m[i - 15] >> 3);
            const uint32_t s1 = rotr(m[i - 2], 17) ^ rotr(m[i - 2], 19) ^ (m[i - 2] >> 10);
            m[i] = m[i - 16] + s0 + m[i - 7] + s1;
        }

        uint32_t a = mState[0];
        uint32_t b = mState[1];
        uint32_t c = mState[2];
        uint32_t d = mState[3];
        uint32_t e = mState[4];
        uint32_t f = mState[5];
        uint32_t g = mState[6];
        uint32_t h = mState[7];

        for (size_t i = 0; i < 64; ++i) {
            const uint32_t s1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
            const uint32_t ch = (e & f) ^ (~e & g);
            const uint32_t temp1 = h + s1 + ch + k[i] + m[i];
            const uint32_t s0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
            const uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
            const uint32_t temp2 = s0 + maj;

            h = g;
            g = f;
            f = e;
            e = d + temp1;
            d = c;
            c = b;
            b = a;
            a = temp1 + temp2;
        }

        mState[0] += a;
        mState[1] += b;
        mState[2] += c;
        mState[3] += d;
        mState[4] += e;
        mState[5] += f;
        mState[6] += g;
        mState[7] += h;
    }

    std::array<unsigned char, 64> mData{};
    size_t mDataLen = 0;
    uint64_t mBitLen = 0;
    uint32_t mState[8]{};
};

bool runCommandWithTimeout(const std::string& cmd, int timeoutMs) {
    if (cmd.empty()) {
        return false;
    }

#ifdef _WIN32
    STARTUPINFOA si;
    PROCESS_INFORMATION pi;
    std::memset(&si, 0, sizeof(si));
    std::memset(&pi, 0, sizeof(pi));
    si.cb = sizeof(si);

    std::string command = "cmd.exe /C " + cmd;
    std::vector<char> buffer(command.begin(), command.end());
    buffer.push_back('\0');

    if (!CreateProcessA(nullptr, buffer.data(), nullptr, nullptr, FALSE, CREATE_NO_WINDOW, nullptr, nullptr, &si, &pi)) {
        return false;
    }

    const DWORD waitResult = WaitForSingleObject(pi.hProcess, timeoutMs > 0 ? static_cast<DWORD>(timeoutMs) : 5000);
    bool ok = false;
    if (waitResult == WAIT_OBJECT_0) {
        DWORD exitCode = 1;
        if (GetExitCodeProcess(pi.hProcess, &exitCode)) {
            ok = (exitCode == 0);
        }
    }
    else {
        TerminateProcess(pi.hProcess, 1);
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return ok;
#else
    pid_t pid = fork();
    if (pid < 0) {
        return false;
    }
    if (pid == 0) {
        execl("/bin/sh", "sh", "-c", cmd.c_str(), static_cast<char*>(nullptr));
        _exit(127);
    }

    const int64_t deadlineMs = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count() + (timeoutMs > 0 ? timeoutMs : 5000);

	    int status = 0;
	    while (true) {
	        const pid_t waited = waitpid(pid, &status, WNOHANG);
        if (waited == pid) {
            if (WIFEXITED(status)) {
                return WEXITSTATUS(status) == 0;
            }
            return false;
        }
	        if (waited < 0) {
	            return false;
	        }

	        if (const int64_t nowMs = std::chrono::duration_cast<std::chrono::milliseconds>(
	                std::chrono::steady_clock::now().time_since_epoch()).count();
	            nowMs >= deadlineMs) {
	            kill(pid, SIGKILL);
	            waitpid(pid, &status, 0);
	            return false;
	        }
	        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
#endif
}

std::string readFirstMatchingCpuLine() {
#if defined(_WIN32)
    HKEY hKey = nullptr;
    if (RegOpenKeyExA(HKEY_LOCAL_MACHINE,
                      "HARDWARE\\DESCRIPTION\\System\\CentralProcessor\\0",
                      0,
                      KEY_READ,
                      &hKey) != ERROR_SUCCESS) {
        return std::string();
    }
    char value[512];
    DWORD size = sizeof(value);
    const LONG rc = RegQueryValueExA(hKey, "ProcessorNameString", nullptr, nullptr, reinterpret_cast<LPBYTE>(value), &size);
    RegCloseKey(hKey);
    if (rc != ERROR_SUCCESS || size == 0) {
        return std::string();
    }
    return trimCopy(std::string(value));
#elif defined(__APPLE__)
    char buffer[512];
    size_t size = sizeof(buffer);
    if (sysctlbyname("machdep.cpu.brand_string", buffer, &size, nullptr, 0) == 0 && size > 0) {
        return trimCopy(std::string(buffer, size - 1));
    }
    return std::string();
#else
    std::ifstream ifs("/proc/cpuinfo");
    if (!ifs.is_open()) {
        return std::string();
    }
    std::string line;
    while (std::getline(ifs, line)) {
        std::string lower = toLowerCopy(line);
        if (lower.rfind("model name", 0) == 0) {
            const size_t pos = line.find(':');
            if (pos != std::string::npos) {
                return trimCopy(line.substr(pos + 1));
            }
        }
    }
    return std::string();
#endif
}

}  // namespace

std::string sha256Hex(std::string_view input) {
    Sha256 sha;
    sha.update(reinterpret_cast<const unsigned char*>(input.data()), input.size());
    return sha.finalHex();
}

bool shouldUseLocalLicense(const Config* config) {
    if (!config) {
        return false;
    }
    const std::string type = toLowerCopy(trimCopy(config->licenseType));
    return type == "machine" || type == "dongle";
}

LocalLicense::LocalLicense(const Config* config) : mConfig(config) {}

std::string LocalLicense::getSystemName() const {
#ifdef _WIN32
    return "Windows";
#elif defined(__APPLE__)
    return "Darwin";
#elif defined(__linux__)
    return "Linux";
#else
    return "Unknown";
#endif
}

std::string LocalLicense::getMachineNode() const {
#ifdef _WIN32
    char buffer[MAX_COMPUTERNAME_LENGTH + 1];
    DWORD size = sizeof(buffer);
    if (GetComputerNameA(buffer, &size) != 0 && size > 0) {
        return trimCopy(std::string(buffer, size));
    }
    return "unknown-node";
#else
    char buffer[256];
    std::memset(buffer, 0, sizeof(buffer));
    if (gethostname(buffer, sizeof(buffer) - 1) == 0 && buffer[0] != '\0') {
        return trimCopy(std::string(buffer));
    }
    return "unknown-node";
#endif
}

std::string LocalLicense::getMachineCpu() const {
    if (const std::string value = readFirstMatchingCpuLine(); !value.empty()) {
        return value;
    }
    return "unknown-cpu";
}

std::string LocalLicense::getMachineStableId() const {
#ifdef _WIN32
    HKEY hKey = nullptr;
    if (RegOpenKeyExA(HKEY_LOCAL_MACHINE,
                      "SOFTWARE\\Microsoft\\Cryptography",
                      0,
                      KEY_READ | KEY_WOW64_64KEY,
                      &hKey) == ERROR_SUCCESS) {
        char value[256];
        DWORD size = sizeof(value);
        const LONG rc = RegQueryValueExA(hKey, "MachineGuid", nullptr, nullptr, reinterpret_cast<LPBYTE>(value), &size);
        RegCloseKey(hKey);
        if (rc == ERROR_SUCCESS && size > 0) {
            return trimCopy(std::string(value));
        }
    }
    return std::string();
#elif defined(__APPLE__)
    FILE* pipe = popen("ioreg -rd1 -c IOPlatformExpertDevice 2>/dev/null", "r");
    if (!pipe) {
        return std::string();
    }
    std::string line;
    std::array<char, 256> buffer{};
    while (fgets(buffer.data(), static_cast<int>(buffer.size()), pipe) != nullptr) {
        line.assign(buffer.data());
        const std::string marker = "\"IOPlatformUUID\" = \"";
        const size_t pos = line.find(marker);
        if (pos != std::string::npos) {
            const size_t start = pos + marker.size();
            const size_t end = line.find('"', start);
            pclose(pipe);
            if (end != std::string::npos && end > start) {
                return trimCopy(line.substr(start, end - start));
            }
            return std::string();
        }
    }
    pclose(pipe);
    return std::string();
#else
    for (const char* path : {"/etc/machine-id", "/var/lib/dbus/machine-id"}) {
        std::ifstream ifs(path);
        if (!ifs.is_open()) {
            continue;
        }
        std::string value;
        std::getline(ifs, value);
        value = trimCopy(value);
        if (!value.empty()) {
            return value;
        }
    }
    return std::string();
#endif
}

std::string LocalLicense::getMacAddress() const {
#ifdef _WIN32
    ULONG size = 0;
    if (GetAdaptersAddresses(AF_UNSPEC, GAA_FLAG_SKIP_ANYCAST | GAA_FLAG_SKIP_MULTICAST | GAA_FLAG_SKIP_DNS_SERVER,
                             nullptr, nullptr, &size) != ERROR_BUFFER_OVERFLOW) {
        return std::string();
    }
    std::vector<unsigned char> buffer(size);
    auto* addrs = reinterpret_cast<IP_ADAPTER_ADDRESSES*>(buffer.data());
    if (GetAdaptersAddresses(AF_UNSPEC, GAA_FLAG_SKIP_ANYCAST | GAA_FLAG_SKIP_MULTICAST | GAA_FLAG_SKIP_DNS_SERVER,
                             nullptr, addrs, &size) != NO_ERROR) {
        return std::string();
    }
    for (auto* p = addrs; p != nullptr; p = p->Next) {
        if (p->PhysicalAddressLength != 6) {
            continue;
        }
        if (p->IfType == IF_TYPE_SOFTWARE_LOOPBACK) {
            continue;
        }
        if ((p->PhysicalAddress[0] & 0x01) == 0x01) {
            continue;
        }
        bool allZero = true;
        for (ULONG i = 0; i < p->PhysicalAddressLength; ++i) {
            if (p->PhysicalAddress[i] != 0) {
                allZero = false;
                break;
            }
        }
        if (allZero) {
            continue;
        }
        return bytesToHex(p->PhysicalAddress, p->PhysicalAddressLength);
    }
    return std::string();
#else
    struct ifaddrs* ifaddr = nullptr;
    if (getifaddrs(&ifaddr) != 0 || ifaddr == nullptr) {
        return std::string();
    }

    std::string result;
    for (struct ifaddrs* ifa = ifaddr; ifa != nullptr; ifa = ifa->ifa_next) {
        if (ifa->ifa_addr == nullptr) {
            continue;
        }
        if ((ifa->ifa_flags & IFF_LOOPBACK) != 0) {
            continue;
        }
#if defined(__linux__)
        if (ifa->ifa_addr->sa_family != AF_PACKET) {
            continue;
        }
        auto* s = reinterpret_cast<struct sockaddr_ll*>(ifa->ifa_addr);
        if (s->sll_halen != 6) {
            continue;
        }
        if ((static_cast<std::byte>(s->sll_addr[0]) & static_cast<std::byte>(0x01)) != static_cast<std::byte>(0x00)) {
            continue;
        }
        bool allZero = true;
        for (int i = 0; i < s->sll_halen; ++i) {
            if (s->sll_addr[i] != 0) {
                allZero = false;
                break;
            }
        }
        if (allZero) {
            continue;
        }
        result = bytesToHex(reinterpret_cast<unsigned char*>(s->sll_addr), static_cast<size_t>(s->sll_halen));
        break;
#elif defined(__APPLE__)
        if (ifa->ifa_addr->sa_family != AF_LINK) {
            continue;
        }
        auto* s = reinterpret_cast<struct sockaddr_dl*>(ifa->ifa_addr);
        if (s->sdl_alen != 6) {
            continue;
        }
        const unsigned char* mac = reinterpret_cast<const unsigned char*>(LLADDR(s));
        if ((mac[0] & 0x01) == 0x01) {
            continue;
        }
        bool allZero = true;
        for (int i = 0; i < s->sdl_alen; ++i) {
            if (mac[i] != 0) {
                allZero = false;
                break;
            }
        }
        if (allZero) {
            continue;
        }
        result = bytesToHex(mac, static_cast<size_t>(s->sdl_alen));
        break;
#endif
    }
    freeifaddrs(ifaddr);
    return result;
#endif
}

std::string LocalLicense::getMachineCodeV1() const {
    if (!mMachineCodeV1.empty()) {
        return mMachineCodeV1;
    }
    mMachineCodeV1 = sha256Hex(joinParts({
        getMachineNode(),
        getMachineCpu(),
        getMacAddress(),
    }));
    return mMachineCodeV1;
}

std::string LocalLicense::getMachineCodeV2() const {
    if (!mMachineCodeV2.empty()) {
        return mMachineCodeV2;
    }
    if (const std::string stable = trimCopy(getMachineStableId()); !stable.empty()) {
        mMachineCodeV2 = sha256Hex(joinParts({
            getSystemName(),
            stable,
            getMachineCpu(),
        }));
        return mMachineCodeV2;
    }
    mMachineCodeV2 = getMachineCodeV1();
    return mMachineCodeV2;
}

std::string LocalLicense::getMachineCode() const {
    if (!mMachineCode.empty()) {
        return mMachineCode;
    }
    mMachineCode = getMachineCodeV2();
    return mMachineCode;
}

bool LocalLicense::checkDongle() const {
    const std::string cmd = trimCopy(mConfig ? mConfig->licenseDongleCmd : "");
    const std::string sentinel = trimCopy(mConfig ? mConfig->licenseDongleFile : "");
    if (!cmd.empty() && runCommandWithTimeout(cmd, 5000)) {
        return true;
    }
    if (!sentinel.empty()) {
        return std::filesystem::is_regular_file(std::filesystem::path(sentinel));
    }
    return false;
}

bool LocalLicense::checkMachineLicense() const {
    const std::string key = trimCopy(mConfig ? mConfig->licenseKey : "");
    if (key.empty()) {
        return false;
    }

    std::vector<std::string> codes;
    codes.push_back(getMachineCodeV2());
    codes.push_back(getMachineCodeV1());

    std::vector<std::string> uniq;
    for (const auto& code : codes) {
        if (!code.empty() && std::find(uniq.begin(), uniq.end(), code) == uniq.end()) {
            uniq.push_back(code);
        }
    }

    for (const auto& code : uniq) {
        if (key == code) {
            return true;
        }
        if (key == sha256Hex(code)) {
            return true;
        }
    }
    return false;
}

LocalLicenseInfo LocalLicense::check() const {
    LocalLicenseInfo info;
    info.type = toLowerCopy(trimCopy(mConfig ? mConfig->licenseType : ""));
    if (info.type.empty()) {
        info.type = "community";
    }
    info.machineCode = getMachineCode();
    info.machineCodeV1 = getMachineCodeV1();
    info.machineCodeV2 = getMachineCodeV2();

    if (info.type == "community") {
        info.ok = true;
    }
    else if (info.type == "dongle") {
        info.ok = checkDongle();
    }
    else if (info.type == "machine") {
        info.ok = checkMachineLicense();
    }
    else {
        info.ok = false;
    }
    return info;
}

}  // namespace AVSAnalyzer
