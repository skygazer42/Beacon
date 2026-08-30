#include "Common/config.h"
#include "Http/HttpSession.h"
#include "Network/TcpServer.h"
#include "Rtmp/RtmpSession.h"
#include "Rtp/Decoder.h"
#include "Rtp/RtpProcess.h"
#include "Rtsp/RtspSession.h"
#include "Util/File.h"
#include "Util/MD5.h"
#include "Util/SSLBox.h"
#include "Util/logger.h"
#include "Util/util.h"
#include <array>
#include <iostream>
#include <map>
#include <memory>


using namespace std;
using namespace toolkit;
using namespace mediakit;

static semaphore sem;
class PsProcess : public MediaSinkInterface, public std::enable_shared_from_this<PsProcess> {
public:
    using Ptr = std::shared_ptr<PsProcess>;
    PsProcess() {
        MediaTuple media_info;
        media_info.vhost = DEFAULT_VHOST;
        media_info.app = "rtp";
        media_info.stream = "000001";

        _muxer = std::make_shared<MultiMediaSourceMuxer>(media_info, 0.0f, ProtocolOption());
    }
    ~PsProcess() {
    }

    bool inputFrame(const Frame::Ptr &frame) override {
        if (_muxer) {
            _muxer->inputFrame(frame);
            int64_t diff = frame->dts() - timeStamp_last;
            if (diff > 0 && diff < 500) {
                usleep(diff * 1000);
            } else {
                usleep(1 * 1000);
            }
            timeStamp_last = frame->dts();
        }
        return true;
    }
    bool addTrack(const Track::Ptr &track) override {
        if (_muxer) {
            return _muxer->addTrack(track);
        }
        return true;
    }
    void addTrackCompleted() override {
        if (_muxer) {
            _muxer->addTrackCompleted();
        }
    }
    void resetTracks() override {

    }
    virtual void flush() override {}

private:
    MultiMediaSourceMuxer::Ptr _muxer;
    uint64_t timeStamp = 0;
    uint64_t timeStamp_last = 0;
};

static bool loadFile(const char *path) {
    std::unique_ptr<FILE, decltype(&fclose)> fp(fopen(path, "rb"), &fclose);
    if (!fp) {
        WarnL << "open file failed:" << path;
        return false;
    }

    PsProcess::Ptr ps_process = std::make_shared<PsProcess>();
    DecoderImp::Ptr ps_decoder = DecoderImp::createDecoder(DecoderImp::decoder_ps, ps_process.get());
    if (!ps_decoder) {
        WarnL << "create PS decoder failed";
        return false;
    }

    std::array<uint8_t, 64U * 1024U> buffer{};
    size_t total_size = 0;
    size_t bytes = 0;
    while ((bytes = fread(buffer.data(), sizeof(uint8_t), buffer.size(), fp.get())) > 0) {
        if (ps_decoder->input(buffer.data(), bytes) < 0) {
            WarnL << "decode PS data failed:" << path;
            return false;
        }
        total_size += bytes;
    }
    if (ferror(fp.get())) {
        WarnL << "read file failed:" << path;
        return false;
    }
    ps_decoder->flush();
    WarnL << (total_size >> 10) << "KB";
    return true;
}

int main(int argc, char *argv[]) {
    // 设置日志
    Logger::Instance().add(std::make_shared<ConsoleChannel>("ConsoleChannel"));

    // 启动异步日志线程
    Logger::Instance().setWriter(std::make_shared<AsyncLogWriter>());
    loadIniConfig((exeDir() + "config.ini").data());

    TcpServer::Ptr rtspSrv(new TcpServer());
    TcpServer::Ptr rtmpSrv(new TcpServer());
    TcpServer::Ptr httpSrv(new TcpServer());
    rtspSrv->start<RtspSession>(554);  // 默认554
    rtmpSrv->start<RtmpSession>(1935); // 默认1935
    httpSrv->start<HttpSession>(81);   // 默认80

    if (argc == 2) {
        auto poller = EventPollerPool::Instance().getPoller();
        poller->async_first([poller, argv]() {
            loadFile(argv[1]);
            sem.post();
        });
        sem.wait();
        sleep(1);
    } else
        ErrorL << "parameter error.";
    return 0;
}
