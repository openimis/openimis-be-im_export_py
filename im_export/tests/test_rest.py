
from core.test_helpers import create_test_interactive_user
from rest_framework import status
from rest_framework.test import APITestCase
from graphql_jwt.shortcuts import get_token
from django.conf import settings

from core.models.openimis_graphql_test_case import BaseTestContext as DummyContext


class ReportAPITests(APITestCase):

    admin_user = None
    admin_token = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin_user = create_test_interactive_user(username="testLocationAdmin")
        cls.admin_token = get_token(cls.admin_user, DummyContext(user=cls.admin_user))

    def test_export_csv(self):
        URL = f'/{settings.SITE_ROOT()}im_export/exports/insurees?file_format=csv'
        headers = {"HTTP_AUTHORIZATION": f"Bearer {self.admin_token}"}
        response = self.client.get(URL, format='json', **headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_export_xls(self):
        URL = f'/{settings.SITE_ROOT()}im_export/exports/insurees?file_format=xls'
        headers = {"HTTP_AUTHORIZATION": f"Bearer {self.admin_token}"}
        response = self.client.get(URL, format='json', **headers)
        error = str(response.content) if response.status_code != status.HTTP_200_OK else ""
        self.assertEqual(response.status_code, status.HTTP_200_OK, error)

# todo expand tests
