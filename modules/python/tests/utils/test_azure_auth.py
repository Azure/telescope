"""Tests for Azure credential configuration."""

import unittest
from unittest import mock

from utils.azure_auth import configure_credential


class TestConfigureCredential(unittest.TestCase):
    """Tests for configure_credential"""

    @mock.patch("utils.azure_auth.DefaultAzureCredential")
    def test_configure_default_credential(self, mock_default_credential):
        credential = configure_credential()

        mock_default_credential.assert_called_once_with()
        self.assertIs(credential, mock_default_credential.return_value)

    @mock.patch("utils.azure_auth.DefaultAzureCredential")
    def test_configure_default_credential_excludes_managed_identity(
        self, mock_default_credential
    ):
        credential = configure_credential(default_credential_exclude_mi=True)

        mock_default_credential.assert_called_once_with(
            exclude_managed_identity_credential=True
        )
        self.assertIs(credential, mock_default_credential.return_value)

    @mock.patch.dict("os.environ", {}, clear=True)
    @mock.patch("utils.azure_auth.ManagedIdentityCredential")
    def test_configure_system_assigned_managed_identity(
        self, mock_managed_identity_credential
    ):
        credential = configure_credential(use_managed_identity=True)

        mock_managed_identity_credential.assert_called_once_with()
        self.assertIs(credential, mock_managed_identity_credential.return_value)

    @mock.patch.dict(
        "os.environ", {"AZURE_MI_ID": "fake-managed-identity-id"}, clear=True
    )
    @mock.patch("utils.azure_auth.ManagedIdentityCredential")
    def test_configure_user_assigned_managed_identity(
        self, mock_managed_identity_credential
    ):
        credential = configure_credential(use_managed_identity=True)

        mock_managed_identity_credential.assert_called_once_with(
            client_id="fake-managed-identity-id"
        )
        self.assertIs(credential, mock_managed_identity_credential.return_value)


if __name__ == "__main__":
    unittest.main()
