#ifndef ANALYZER_COMMON_H
#define ANALYZER_COMMON_H

#include <chrono>
#include <ctime>
#include <cstdio>
#include <iomanip>
#include <random>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>
#include <time.h>


namespace AVSAnalyzer {
    static inline std::string formatTimeStr(const std::tm& tmValue, const char* format) {
        std::ostringstream stream;
        stream << std::put_time(&tmValue, format ? format : "%Y-%m-%d %H:%M:%S");
        return stream.str();
    }

    static int64_t getCurTime()// 获取当前系统启动以来的毫秒数
    {
#ifndef WIN32
        // Linux系统
        struct timespec now;// tv_sec (s) tv_nsec (ns-纳秒)
        clock_gettime(CLOCK_MONOTONIC, &now);
        return (now.tv_sec * 1000 + now.tv_nsec / 1000000);
#else
        long long now = std::chrono::steady_clock::now().time_since_epoch().count();
        return now / 1000000;
#endif // !WIN32

    }
	    static int64_t getCurTimestamp()// 获取毫秒级时间戳（13位）
    {
        return std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch()).
            count();

	    }
		    static std::string getCurFormatTimeStr(const char* format = "%Y-%m-%d %H:%M:%S") {

		        time_t t = time(nullptr);
		        std::tm tm_buf{};
#ifdef _WIN32
		        localtime_s(&tm_buf, &t);
#else
		        localtime_r(&t, &tm_buf);
#endif
		        return formatTimeStr(tm_buf, format);
		    }
		    static std::vector<std::string> split(std::string_view str, std::string_view sep) {

		        std::vector<std::string> arr;
		        if (sep.empty()) {
		            arr.emplace_back(str.data(), str.size());
		            return arr;
		        }

		        std::string_view::size_type last_pos = 0;
		        while (true) {
		            const auto pos = str.find(sep, last_pos);
		            if (pos == std::string_view::npos) {
		                break;
		            }
			            arr.emplace_back(str.data() + last_pos, pos - last_pos);
			            last_pos = pos + sep.size();
			        }
				        if (const std::string_view tail = str.substr(last_pos); !tail.empty()) { //截取最后一个分隔符后的内容
				            arr.emplace_back(tail.data(), tail.size());//如果最后一个分隔符后还有内容就入队
				        }

			        return arr;
			    }

	    static bool removeFile(std::string_view filename) {
	        std::string path(filename.data(), filename.size());

	        if (remove(path.c_str()) == 0) {
	            return true;
	        }
	        else {
	            return false;
	        }
    }

		    static int getRandomInt() {
		        // Replaces `rand()` with <random> to avoid weak global RNG and thread-safety issues.
		        // Format preserved: 8 digits, first digit is 1-9, rest are 0-9.
		        static thread_local std::mt19937 rng{std::random_device{}()};
		        std::uniform_int_distribution first_digit(1, 9);
		        std::uniform_int_distribution rest_digit(0, 9);
		        int num = first_digit(rng);
		        for (int i = 0; i < 7; ++i) {
		            num = (num * 10) + rest_digit(rng);
		        }
	        return num;
	    }


};

#endif //ANALYZER_COMMON_H
