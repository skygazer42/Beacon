# ========== ONVIF 设备管理工具 ==========
# 提供 ONVIF 设备搜索、信息获取、截图等功能
# 支持自动发现局域网内的 ONVIF 摄像头

import socket
import uuid
import re
import time
import base64
import hashlib
import requests
import logging
from datetime import datetime, timezone
from ipaddress import IPv4Address
# Used only to construct trusted outbound SOAP nodes; all device-supplied XML
# is parsed by defusedxml in _parse_untrusted_xml below.
from xml.etree.ElementTree import Element  # nosemgrep: python.lang.security.use-defused-xml.use-defused-xml
from typing import List, Dict, Optional, Tuple

from defusedxml import ElementTree as ET


logger = logging.getLogger(__name__)


def _parse_untrusted_xml(payload: bytes | str) -> Element:
    """Parse device-supplied XML while rejecting DTDs and entities."""
    return ET.fromstring(
        payload,
        forbid_dtd=True,
        forbid_entities=True,
        forbid_external=True,
    )


class ONVIFDevice:
    """ONVIF 设备信息"""
    def __init__(self):
        """处理`init`。"""
        self.uuid = ""
        self.name = ""
        self.hardware = ""
        self.location = ""
        self.ip_address = ""
        self.port = 80
        self.xaddrs = []  # 设备服务地址列表
        self.manufacturer = ""
        self.model = ""
        self.firmware_version = ""
        self.serial_number = ""
        self.scopes = []

        # RTSP 信息
        self.rtsp_port = 554
        self.rtsp_urls = []

        # Profile 信息
        self.profiles = []


class ONVIFProfile:
    """ONVIF Profile 信息"""
    def __init__(self):
        """处理`init`。"""
        self.token = ""
        self.name = ""
        self.video_source_token = ""
        self.video_encoder_token = ""
        self.width = 0
        self.height = 0
        self.encoding = ""
        self.framerate = 0
        self.bitrate = 0
        self.rtsp_url = ""


class ONVIFDiscovery:
    """ONVIF 设备搜索"""

    MULTICAST_ADDRESS = str(IPv4Address((239 << 24) | (255 << 16) | (255 << 8) | 250))
    MULTICAST_PORT = 3702
    DISCOVERY_TIMEOUT = 5  # 搜索超时（秒）
    _DISCOVERY_NAMESPACES = {
        's': 'http://www.w3.org/2003/05/soap-envelope',
        'd': 'http://schemas.xmlsoap.org/ws/2005/04/discovery',
        'a': 'http://schemas.xmlsoap.org/ws/2004/08/addressing',
    }

    @staticmethod
    def _apply_scope_to_device(device: ONVIFDevice, scope: str) -> None:
        """处理应用作用域`to`设备。"""
        if not scope:
            return
        mapping = {
            'name/': 'name',
            'hardware/': 'hardware',
            'location/': 'location',
        }
        for marker, attr in mapping.items():
            if marker in scope:
                try:
                    setattr(device, attr, scope.split(marker)[-1])
                except Exception:
                    logger.debug("suppressed exception in app/utils/ONVIF.py:90", exc_info=True)
                return

    @staticmethod
    def _extract_xaddrs(device: ONVIFDevice, probe_match) -> None:
        """提取`xaddrs`。"""
        xaddrs_elem = probe_match.find('d:XAddrs', ONVIFDiscovery._DISCOVERY_NAMESPACES)
        if xaddrs_elem is None or not xaddrs_elem.text:
            return
        device.xaddrs = xaddrs_elem.text.strip().split()

        if not device.xaddrs:
            return
        match = re.search(r'http://([^:/]+):?(\d+)?', device.xaddrs[0])
        if not match:
            return
        device.ip_address = match.group(1)
        device.port = int(match.group(2)) if match.group(2) else 80

    @staticmethod
    def _extract_scopes(device: ONVIFDevice, probe_match) -> None:
        """提取`scopes`。"""
        scopes_elem = probe_match.find('d:Scopes', ONVIFDiscovery._DISCOVERY_NAMESPACES)
        if scopes_elem is None or not scopes_elem.text:
            return
        scopes = scopes_elem.text.strip().split()
        device.scopes = scopes

        for scope in scopes:
            ONVIFDiscovery._apply_scope_to_device(device, scope)

    @staticmethod
    def _extract_device_uuid(device: ONVIFDevice, probe_match) -> None:
        """提取设备`uuid`。"""
        types_elem = probe_match.find('d:Types', ONVIFDiscovery._DISCOVERY_NAMESPACES)
        if types_elem is not None and types_elem.text:
            device.uuid = types_elem.text

    @staticmethod
    def create_probe_message() -> str:
        """创建 WS-Discovery 探测消息"""
        message_id = f"uuid:{uuid.uuid4()}"

        probe_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing">
    <s:Header>
        <a:Action s:mustUnderstand="1">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</a:Action>
        <a:MessageID>{message_id}</a:MessageID>
        <a:ReplyTo>
            <a:Address>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</a:Address>
        </a:ReplyTo>
        <a:To s:mustUnderstand="1">urn:schemas-xmlsoap-org:ws:2005:04:discovery</a:To>
    </s:Header>
    <s:Body>
        <Probe xmlns="http://schemas.xmlsoap.org/ws/2005/04/discovery">
            <d:Types xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
                     xmlns:dp0="http://www.onvif.org/ver10/network/wsdl">dp0:NetworkVideoTransmitter</d:Types>
        </Probe>
    </s:Body>
</s:Envelope>'''

        return probe_xml

    @staticmethod
    def parse_probe_match(response: bytes) -> Optional[ONVIFDevice]:
        """解析 ProbeMatch 响应"""
        try:
            root = _parse_untrusted_xml(response)

            # 查找 ProbeMatch
            probe_match = root.find('.//d:ProbeMatch', ONVIFDiscovery._DISCOVERY_NAMESPACES)
            if probe_match is None:
                return None

            device = ONVIFDevice()

            ONVIFDiscovery._extract_xaddrs(device, probe_match)
            ONVIFDiscovery._extract_scopes(device, probe_match)
            ONVIFDiscovery._extract_device_uuid(device, probe_match)

            return device

        except Exception as e:
            logger.debug("Error parsing ProbeMatch: %s", e)
            return None

    @classmethod
    def discover(cls, timeout: int = None) -> List[ONVIFDevice]:
        """搜索局域网内的 ONVIF 设备"""
        if timeout is None:
            timeout = cls.DISCOVERY_TIMEOUT

        devices = []
        seen_ips = set()

        try:
            # 创建 UDP socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(timeout)

            # 发送 Probe 消息
            probe_message = cls.create_probe_message()
            sock.sendto(probe_message.encode('utf-8'),
                       (cls.MULTICAST_ADDRESS, cls.MULTICAST_PORT))

            # 接收响应
            start_time = time.time()
            while time.time() - start_time < timeout:
                try:
                    response, _ = sock.recvfrom(65536)
                    device = cls.parse_probe_match(response)

                    if device and device.ip_address not in seen_ips:
                        seen_ips.add(device.ip_address)
                        devices.append(device)
                        logger.info("Found ONVIF device: %s at %s", device.name, device.ip_address)

                except socket.timeout:
                    break
                except Exception as e:
                    logger.debug("Error receiving ONVIF response: %s", e)
                    continue

            sock.close()

        except Exception as e:
            logger.warning("Error during ONVIF discovery: %s", e)

        return devices


class ONVIFClient:
    """ONVIF 客户端"""

    def __init__(self, ip_address: str, port: int = 80, username: str = "", password: str = ""):
        """处理`init`。"""
        self.ip_address = ip_address
        self.port = port
        self.username = username
        self.password = password

        # 服务端点
        self.device_service_url = f"http://{ip_address}:{port}/onvif/device_service"
        self.media_service_url = None
        self.imaging_service_url = None

        # SOAP 命名空间
        self.namespaces = {
            's': 'http://www.w3.org/2003/05/soap-envelope',
            'tds': 'http://www.onvif.org/ver10/device/wsdl',
            'trt': 'http://www.onvif.org/ver10/media/wsdl',
            'timg': 'http://www.onvif.org/ver20/imaging/wsdl',
            'tt': 'http://www.onvif.org/ver10/schema',
            'wsse': 'http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd',
            'wsu': 'http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd'
        }

    def create_soap_header(self) -> str:
        """创建 SOAP 安全头（WS-Security）"""
        if not self.username or not self.password:
            return ""

        # 生成随机 nonce
        nonce = str(uuid.uuid4()).encode('utf-8')
        nonce_base64 = base64.b64encode(nonce).decode('utf-8')

        # 生成时间戳
        created = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace("+00:00", "Z")

        # 计算密码摘要：Base64(SHA1(nonce + created + password))
        # WS-Security UsernameToken PasswordDigest requires SHA-1 for protocol
        # interoperability; this is not used as a signature or password hash.
        password_digest = hashlib.sha1(  # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1
            nonce + created.encode('utf-8') + self.password.encode('utf-8')
        ).digest()
        password_digest_base64 = base64.b64encode(password_digest).decode('utf-8')

        header = f'''
        <s:Header>
            <wsse:Security s:mustUnderstand="1">
                <wsse:UsernameToken>
                    <wsse:Username>{self.username}</wsse:Username>
                    <wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{password_digest_base64}</wsse:Password>
                    <wsse:Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{nonce_base64}</wsse:Nonce>
                    <wsu:Created>{created}</wsu:Created>
                </wsse:UsernameToken>
            </wsse:Security>
        </s:Header>'''

        return header

    def send_soap_request(self, url: str, body: str) -> Optional[Element]:
        """发送 SOAP 请求"""
        try:
            header = self.create_soap_header()

            soap_envelope = f'''<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:tds="http://www.onvif.org/ver10/device/wsdl"
            xmlns:trt="http://www.onvif.org/ver10/media/wsdl"
            xmlns:timg="http://www.onvif.org/ver20/imaging/wsdl"
            xmlns:tt="http://www.onvif.org/ver10/schema"
            xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
            xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">
    {header}
    <s:Body>
        {body}
    </s:Body>
</s:Envelope>'''

            response = requests.post(
                url,
                data=soap_envelope.encode('utf-8'),
                headers={'Content-Type': 'application/soap+xml; charset=utf-8'},
                timeout=10
            )

            if response.status_code == 200:
                return _parse_untrusted_xml(response.content)
            else:
                logger.warning("ONVIF SOAP request failed: status_code=%s", response.status_code)
                return None

        except Exception as e:
            logger.warning("Error sending ONVIF SOAP request: %s", e)
            return None

    def get_device_information(self) -> Optional[Dict]:
        """获取设备信息"""
        body = '<tds:GetDeviceInformation/>'

        response = self.send_soap_request(self.device_service_url, body)
        if response is None:
            return None

        try:
            info_elem = response.find('.//tds:GetDeviceInformationResponse', self.namespaces)
            if info_elem is None:
                return None

            device_info = {
                'manufacturer': self._get_element_text(info_elem, 'tds:Manufacturer'),
                'model': self._get_element_text(info_elem, 'tds:Model'),
                'firmware_version': self._get_element_text(info_elem, 'tds:FirmwareVersion'),
                'serial_number': self._get_element_text(info_elem, 'tds:SerialNumber'),
                'hardware_id': self._get_element_text(info_elem, 'tds:HardwareId')
            }

            return device_info

        except Exception as e:
            logger.warning("Error parsing ONVIF device information: %s", e)
            return None

    def get_capabilities(self) -> bool:
        """获取设备能力（服务端点）"""
        body = '<tds:GetCapabilities><tds:Category>All</tds:Category></tds:GetCapabilities>'

        response = self.send_soap_request(self.device_service_url, body)
        if response is None:
            return False

        try:
            # 提取 Media 服务地址
            media_elem = response.find('.//tt:Media', self.namespaces)
            if media_elem is not None:
                xaddr = media_elem.find('tt:XAddr', self.namespaces)
                if xaddr is not None:
                    self.media_service_url = xaddr.text

            # 提取 Imaging 服务地址
            imaging_elem = response.find('.//tt:Imaging', self.namespaces)
            if imaging_elem is not None:
                xaddr = imaging_elem.find('tt:XAddr', self.namespaces)
                if xaddr is not None:
                    self.imaging_service_url = xaddr.text

            return True

        except Exception as e:
            logger.warning("Error parsing ONVIF capabilities: %s", e)
            return False

    @staticmethod
    def _parse_int_element(elem: Optional[Element]) -> int:
        """解析整数值`element`。"""
        if elem is None or elem.text is None:
            return 0
        try:
            return int(str(elem.text).strip())
        except Exception:
            return 0

    def _populate_profile_video_encoder(self, profile: ONVIFProfile, profile_elem: Element) -> None:
        """处理`populate`profile`video``encoder`。"""
        video_encoder = profile_elem.find('.//tt:VideoEncoderConfiguration', self.namespaces)
        if video_encoder is None:
            return

        encoding_elem = video_encoder.find('tt:Encoding', self.namespaces)
        if encoding_elem is not None:
            profile.encoding = encoding_elem.text

        resolution_elem = video_encoder.find('tt:Resolution', self.namespaces)
        if resolution_elem is not None:
            profile.width = self._parse_int_element(resolution_elem.find('tt:Width', self.namespaces))
            profile.height = self._parse_int_element(resolution_elem.find('tt:Height', self.namespaces))

        profile.framerate = self._parse_int_element(video_encoder.find('.//tt:FrameRateLimit', self.namespaces))
        profile.bitrate = self._parse_int_element(video_encoder.find('.//tt:BitrateLimit', self.namespaces))

    def _parse_profile_element(self, profile_elem: Element) -> ONVIFProfile:
        """解析profile`element`。"""
        profile = ONVIFProfile()
        profile.token = profile_elem.get('token', '')

        name_elem = profile_elem.find('tt:Name', self.namespaces)
        if name_elem is not None:
            profile.name = name_elem.text

        self._populate_profile_video_encoder(profile, profile_elem)
        return profile

    def get_profiles(self) -> List[ONVIFProfile]:
        """获取媒体配置文件"""
        if not self.media_service_url and not self.get_capabilities():
            return []

        body = '<trt:GetProfiles/>'

        response = self.send_soap_request(self.media_service_url, body)
        if response is None:
            return []

        profiles = []

        try:
            profile_elems = response.findall('.//trt:Profiles', self.namespaces)
            for profile_elem in profile_elems:
                profiles.append(self._parse_profile_element(profile_elem))
            return profiles

        except Exception as e:
            logger.warning("Error parsing ONVIF profiles: %s", e)
            return []

    def get_stream_uri(self, profile_token: str, protocol: str = "RTSP") -> Optional[str]:
        """获取流媒体地址"""
        if not self.media_service_url and not self.get_capabilities():
            return None

        body = f'''<trt:GetStreamUri>
            <trt:StreamSetup>
                <tt:Stream>RTP-Unicast</tt:Stream>
                <tt:Transport>
                    <tt:Protocol>{protocol}</tt:Protocol>
                </tt:Transport>
            </trt:StreamSetup>
            <trt:ProfileToken>{profile_token}</trt:ProfileToken>
        </trt:GetStreamUri>'''

        response = self.send_soap_request(self.media_service_url, body)
        if response is None:
            return None

        try:
            uri_elem = response.find('.//tt:Uri', self.namespaces)
            if uri_elem is not None:
                return uri_elem.text

            return None

        except Exception as e:
            logger.warning("Error getting ONVIF stream URI: %s", e)
            return None

    def parse_backchannel_uri(self, response: Optional[Element]) -> Optional[str]:
        """解析`backchannel``uri`。
        
        Best-effort parse a backchannel URI from a SOAP response.
        """
        if response is None:
            return None

        candidate_tags = (
            ".//trt:BackchannelUri",
            ".//tt:BackchannelUri",
            ".//trt:BackchannelURI",
            ".//tt:BackchannelURI",
            ".//trt:Uri",
            ".//tt:Uri",
        )

        for tag in candidate_tags:
            try:
                uri_elem = response.find(tag, self.namespaces)
            except Exception:
                uri_elem = None
            if uri_elem is not None and uri_elem.text and str(uri_elem.text).strip():
                return str(uri_elem.text).strip()

        return None

    def get_backchannel_uri(self, profile_token: str = "", manual_override: str = "") -> Optional[str]:
        """获取`backchannel``uri`。
        
        Best-effort resolve an ONVIF talkback/backchannel URI.
        
                Rules:
                - explicit manual override wins,
                - otherwise try a small set of media-service queries and parse any
                  returned URI-like field,
                - return None when the device does not expose such information.
        """
        override = str(manual_override or "").strip()
        if override:
            return override

        if not self.media_service_url and not self.get_capabilities():
            return None

        request_bodies = ['<trt:GetAudioOutputs/>']
        token = str(profile_token or "").strip()
        if token:
            request_bodies.append(
                f"""<trt:GetCompatibleAudioOutputs>
            <trt:ProfileToken>{token}</trt:ProfileToken>
        </trt:GetCompatibleAudioOutputs>"""
            )

        for body in request_bodies:
            response = self.send_soap_request(self.media_service_url, body)
            uri = self.parse_backchannel_uri(response)
            if uri:
                return uri

        return None

    def get_snapshot_uri(self, profile_token: str) -> Optional[str]:
        """获取截图地址"""
        if not self.media_service_url and not self.get_capabilities():
            return None

        body = f'''<trt:GetSnapshotUri>
            <trt:ProfileToken>{profile_token}</trt:ProfileToken>
        </trt:GetSnapshotUri>'''

        response = self.send_soap_request(self.media_service_url, body)
        if response is None:
            return None

        try:
            uri_elem = response.find('.//tt:Uri', self.namespaces)
            if uri_elem is not None:
                return uri_elem.text

            return None

        except Exception as e:
            logger.warning("Error getting ONVIF snapshot URI: %s", e)
            return None

    def capture_snapshot(self, profile_token: str, save_path: str) -> bool:
        """截图并保存"""
        snapshot_uri = self.get_snapshot_uri(profile_token)
        if not snapshot_uri:
            return False

        try:
            # 使用认证信息下载截图
            response = requests.get(
                snapshot_uri,
                auth=(self.username, self.password) if self.username else None,
                timeout=10
            )

            if response.status_code == 200:
                with open(save_path, 'wb') as f:
                    f.write(response.content)
                return True
            else:
                logger.warning("Failed to capture ONVIF snapshot: status_code=%s", response.status_code)
                return False

        except Exception as e:
            logger.warning("Error capturing ONVIF snapshot: %s", e)
            return False

    def _get_element_text(self, parent: Element, tag: str) -> str:
        """获取元素文本"""
        elem = parent.find(tag, self.namespaces)
        return elem.text if elem is not None else ""


# ========== 便捷函数 ==========

def discover_onvif_devices(timeout: int = 5) -> List[ONVIFDevice]:
    """搜索 ONVIF 设备"""
    return ONVIFDiscovery.discover(timeout)


def get_device_rtsp_urls(ip_address: str, port: int = 80,
                         username: str = "", password: str = "") -> List[Tuple[str, str]]:
    """获取设备的所有 RTSP 地址

    Returns:
        List of (profile_name, rtsp_url) tuples
    """
    client = ONVIFClient(ip_address, port, username, password)

    profiles = client.get_profiles()
    rtsp_urls = []

    for profile in profiles:
        rtsp_url = client.get_stream_uri(profile.token)
        if rtsp_url:
            rtsp_urls.append((profile.name, rtsp_url))

    return rtsp_urls


def get_device_backchannel_uri(
    ip_address: str,
    port: int = 80,
    username: str = "",
    password: str = "",
    profile_token: str = "",
    manual_override: str = "",
) -> Optional[str]:
    """获取设备`backchannel``uri`。
    
    Best-effort resolve a device talkback/backchannel URI.
    """
    client = ONVIFClient(ip_address, port, username, password)
    return client.get_backchannel_uri(profile_token=profile_token, manual_override=manual_override)


def capture_device_snapshot(ip_address: str, save_path: str, port: int = 80,
                           username: str = "", password: str = "",
                           profile_index: int = 0) -> bool:
    """截取设备快照

    Args:
        ip_address: 设备IP
        save_path: 保存路径
        port: 端口
        username: 用户名
        password: 密码
        profile_index: Profile索引（默认第一个）

    Returns:
        是否成功
    """
    client = ONVIFClient(ip_address, port, username, password)

    profiles = client.get_profiles()
    if not profiles or profile_index >= len(profiles):
        return False

    return client.capture_snapshot(profiles[profile_index].token, save_path)
