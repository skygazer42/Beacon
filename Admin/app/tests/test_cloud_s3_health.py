import sys
from types import ModuleType
from unittest import mock

from django.test import SimpleTestCase

from app.utils import CloudS3


class CloudS3HealthCheckTest(SimpleTestCase):
    def test_check_bucket_access_uses_bounded_client_and_head_bucket(self):
        class FakeConfig:
            def __init__(self, *, connect_timeout, read_timeout, retries):
                self.connect_timeout = connect_timeout
                self.read_timeout = read_timeout
                self.retries = retries

        botocore_package = ModuleType("botocore")
        botocore_package.__path__ = []
        botocore_config = ModuleType("botocore.config")
        botocore_config.Config = FakeConfig
        client = mock.Mock()
        with (
            mock.patch.dict(
                sys.modules,
                {"botocore": botocore_package, "botocore.config": botocore_config},
            ),
            mock.patch.object(
                CloudS3,
                "make_s3_client_from_env",
                return_value=client,
            ) as make_client,
        ):
            CloudS3.check_bucket_access("beacon-cloud")

        make_client.assert_called_once()
        config = make_client.call_args.kwargs.get("client_config")
        self.assertIsNotNone(config)
        self.assertEqual(config.connect_timeout, 1)
        self.assertEqual(config.read_timeout, 1)
        self.assertEqual(config.retries.get("total_max_attempts"), 1)
        client.head_bucket.assert_called_once_with(Bucket="beacon-cloud")

    def test_check_bucket_access_rejects_empty_bucket_without_client(self):
        with mock.patch.object(CloudS3, "make_s3_client_from_env") as make_client:
            with self.assertRaisesRegex(ValueError, "bucket is required"):
                CloudS3.check_bucket_access("  ")

        make_client.assert_not_called()
