PERM_CLOUD_REMOTE_STREAMS_VIEW = "cloud.remote_streams.view"
PERM_CLOUD_REMOTE_STREAMS_MANAGE = "cloud.remote_streams.manage"
PERM_CLOUD_REMOTE_RECORDINGS_VIEW = "cloud.remote_recordings.view"
PERM_CLOUD_REMOTE_PLATFORM_VIEW = "cloud.remote_platform.view"


CLOUD_REMOTE_PERMISSION_META = [
    {
        "key": PERM_CLOUD_REMOTE_STREAMS_VIEW,
        "name": "远程摄像头-查看",
        "desc": "允许查看边缘节点的远程摄像头列表与详情页",
    },
    {
        "key": PERM_CLOUD_REMOTE_STREAMS_MANAGE,
        "name": "远程摄像头-管理",
        "desc": "允许通过云平台修改边缘节点的摄像头配置",
    },
    {
        "key": PERM_CLOUD_REMOTE_RECORDINGS_VIEW,
        "name": "远程录像-查看",
        "desc": "允许查看边缘节点录像文件列表与播放地址",
    },
    {
        "key": PERM_CLOUD_REMOTE_PLATFORM_VIEW,
        "name": "远程平台-查看",
        "desc": "允许查看算法流与核心进程等平台信息",
    },
]
