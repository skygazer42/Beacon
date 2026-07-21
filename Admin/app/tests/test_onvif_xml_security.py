from unittest import TestCase

from app.utils.ONVIF import ONVIFDiscovery, _parse_untrusted_xml


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
