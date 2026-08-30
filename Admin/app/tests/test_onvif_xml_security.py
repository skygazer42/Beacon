import os
import tempfile
from unittest import TestCase, mock

from app.utils.ONVIF import ONVIFClient, ONVIFDiscovery, _parse_untrusted_xml


class OnvifXmlSecurityTest(TestCase):
    def test_parses_valid_probe_match(self):
        response = b"""<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">
  <s:Body>
    <d:ProbeMatch>
      <d:XAddrs>http://192.0.2.10:8080/onvif/device_service</d:XAddrs>
      <d:Scopes>onvif://www.onvif.org/name/TestCamera</d:Scopes>
      <d:Types>uuid:test-camera</d:Types>
    </d:ProbeMatch>
  </s:Body>
</s:Envelope>"""

        device = ONVIFDiscovery.parse_probe_match(response)

        self.assertIsNotNone(device)
        self.assertEqual(device.ip_address, "192.0.2.10")
        self.assertEqual(device.port, 8080)
        self.assertEqual(device.name, "TestCamera")

    def test_rejects_dtd_and_entity_expansion(self):
        malicious = b"""<?xml version="1.0"?>
<!DOCTYPE envelope [<!ENTITY payload "expanded">]>
<envelope>&payload;</envelope>"""

        with self.assertRaises(Exception):
            _parse_untrusted_xml(malicious)

        self.assertIsNone(ONVIFDiscovery.parse_probe_match(malicious))

    def test_device_advertised_endpoint_must_remain_on_device_host(self):
        client = ONVIFClient("192.168.1.20", 80)
        self.assertEqual(
            client._validated_device_url("http://192.168.1.20/onvif/media"),
            "http://192.168.1.20/onvif/media",
        )
        with self.assertRaises(ValueError):
            client._validated_device_url("http://169.254.169.254/latest/meta-data")
        with self.assertRaises(ValueError):
            client._validated_device_url("http://192.168.1.21/onvif/media")

    def test_soap_header_escapes_untrusted_username(self):
        client = ONVIFClient("192.168.1.20", 80, username='ops</wsse:Username><evil>', password="secret")

        header = client.create_soap_header()

        self.assertIn("ops&lt;/wsse:Username&gt;&lt;evil&gt;", header)
        self.assertNotIn("<evil>", header)

    @mock.patch("app.utils.ONVIF.requests.post")
    def test_soap_request_does_not_follow_redirects(self, post):
        post.return_value.status_code = 500
        client = ONVIFClient("192.168.1.20", 80)

        self.assertIsNone(client.send_soap_request(client.device_service_url, "<tds:GetDeviceInformation/>"))

        self.assertFalse(post.call_args.kwargs["allow_redirects"])

    @mock.patch("app.utils.ONVIF.requests.get")
    def test_snapshot_is_streamed_bounded_and_atomically_saved(self, get):
        response = mock.Mock()
        response.status_code = 200
        response.headers = {"Content-Length": "8"}
        response.iter_content.return_value = [b"\xff\xd8\xffvalid"]
        get.return_value = response
        client = ONVIFClient("192.168.1.20", 80)
        client.get_snapshot_uri = mock.Mock(return_value="http://192.168.1.20/snapshot.jpg")

        with tempfile.TemporaryDirectory() as temp_dir:
            target = os.path.join(temp_dir, "camera.jpg")
            self.assertTrue(client.capture_snapshot("profile", target, allowed_root=temp_dir))
            with open(target, "rb") as handle:
                self.assertEqual(handle.read(), b"\xff\xd8\xffvalid")
            self.assertEqual(os.listdir(temp_dir), ["camera.jpg"])

        self.assertTrue(get.call_args.kwargs["stream"])
        self.assertFalse(get.call_args.kwargs["allow_redirects"])
        response.close.assert_called_once()

    @mock.patch("app.utils.ONVIF.requests.get")
    def test_snapshot_rejects_oversized_or_non_image_payloads(self, get):
        client = ONVIFClient("192.168.1.20", 80)
        client.get_snapshot_uri = mock.Mock(return_value="http://192.168.1.20/snapshot.jpg")

        with tempfile.TemporaryDirectory() as temp_dir:
            target = os.path.join(temp_dir, "camera.jpg")
            oversized = mock.Mock(
                status_code=200,
                headers={"Content-Length": str(20 * 1024 * 1024 + 1)},
            )
            get.return_value = oversized
            self.assertFalse(client.capture_snapshot("profile", target, allowed_root=temp_dir))
            self.assertFalse(os.path.exists(target))

            invalid = mock.Mock(status_code=200, headers={})
            invalid.iter_content.return_value = [b"<html>not an image</html>"]
            get.return_value = invalid
            self.assertFalse(client.capture_snapshot("profile", target, allowed_root=temp_dir))
            self.assertEqual(os.listdir(temp_dir), [])
