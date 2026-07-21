import os
from unittest import mock

from django.contrib.auth.models import User
from django.test import SimpleTestCase

from app.utils.PasswordPolicy import get_password_min_length, validate_password


class PasswordPolicyTest(SimpleTestCase):
    def test_default_minimum_is_eight_characters(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BEACON_PASSWORD_MIN_LENGTH", None)
            self.assertEqual(get_password_min_length(), 8)
            self.assertFalse(validate_password("Short1!")[0])

    def test_configured_minimum_is_enforced(self):
        with mock.patch.dict(os.environ, {"BEACON_PASSWORD_MIN_LENGTH": "12"}):
            ok, message = validate_password("Strong9!Ab")
            self.assertFalse(ok)
            self.assertIn("12", message)

    def test_django_common_and_numeric_validators_are_enforced(self):
        self.assertFalse(validate_password("password")[0])
        self.assertFalse(validate_password("1234567890")[0])

    def test_user_attributes_and_strong_password_are_checked(self):
        user = User(username="beacon-operator", email="operator@example.com")
        self.assertFalse(validate_password("beacon-operator", user=user)[0])
        self.assertTrue(validate_password("S3cure-Beacon-2026!", user=user)[0])
