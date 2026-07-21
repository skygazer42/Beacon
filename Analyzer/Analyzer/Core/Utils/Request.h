#ifndef ANALYZER_REQUEST_H
#define ANALYZER_REQUEST_H
#include <string>
#include <string_view>
namespace AVSAnalyzer {
    // Notes:
    // - For https:// URLs, certificate chain and hostname verification are always enabled.
    class Request
    {
    public:
        Request();
        ~Request();

        bool get(const char* url, std::string& response);
        bool post(const char* url, const char* data, std::string& response);
        bool post(const char* url, std::string_view data, std::string& response);
        bool post(const char* url, std::string_view data, std::string& response, std::string_view token);
        bool post(const char* url, std::string_view data, std::string& response, std::string_view token,
                  int connectTimeoutSeconds, int timeoutSeconds);

    };
}
#endif //ANALYZER_REQUEST_H
