#ifndef ANALYZER_LOG_H
#define ANALYZER_LOG_H
#include <cstdio>
#include <ctime>
#include <iomanip>
#include <sstream>
#include <string>
#ifdef _MSC_VER
#pragma warning( disable : 4996 )
#endif
namespace AVSAnalyzer {
            static inline std::string formatLogTime(const std::tm& tmValue) {
                std::ostringstream stream;
                stream << std::put_time(&tmValue, "%Y-%m-%d %H:%M:%S");
                return stream.str();
            }

		    static std::string logTime() {
		        time_t t = time(nullptr);
		        std::tm tm_buf{};
#ifdef _WIN32
		        localtime_s(&tm_buf, &t);
#else
		        localtime_r(&t, &tm_buf);
#endif
		        return formatLogTime(tm_buf);
		    }



    //  __FILE__ 获取源文件的相对路径和名字
    //  __LINE__ 获取该行代码在文件中的行号
    //  __func__ 或 __FUNCTION__ 获取函数名

#define LOGI(format, ...)  fprintf(stderr,"[INFO]%s [%s:%d] " format "\n", logTime().data(),__func__,__LINE__,##__VA_ARGS__)
#define LOGE(format, ...)  fprintf(stderr,"[ERROR]%s [%s:%d] " format "\n",logTime().data(),__func__,__LINE__,##__VA_ARGS__)
#define LOGW(format, ...)  fprintf(stderr,"[WARN]%s [%s:%d] " format "\n", logTime().data(),__func__,__LINE__,##__VA_ARGS__)
}
#endif //ANALYZER_LOG_H
