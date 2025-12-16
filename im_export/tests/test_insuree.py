import os
from tablib import Dataset
from im_export.resources import InsureeResource
from django.test import TestCase
from location.test_helpers import create_test_location, create_basic_test_locations
from core.test_helpers import create_test_interactive_user
from insuree.test_helpers import create_test_gender, create_test_insuree
from location.models import Location
_TEST_USER_NAME = "test_insuree_import"
_TEST_USER_PWD = "test_insuree_import"
_TEST_DATA_USER = {
    "last_name": _TEST_USER_NAME,
    "password": _TEST_USER_PWD,
    "other_names": _TEST_USER_NAME,
    "user_types": "INTERACTIVE",
    "language": "en",
    "roles": [1, 5, 9],
}

# all location used in the test files must use those name
_TEST_LOCATIONS = [
    {
        'region': 'Batha',
        'district': 'Batha',
        'municipality': 'BEGOU',
        'villages': [
            'Baguirmi',
            'Boua',
            'Niellim',
            'Sarakaba',
            'Maroc'
        ]
    }
]


class ImportInsureeTest(TestCase):

    def setUp(self) -> None:
        create_basic_test_locations()
        create_test_gender()
        for i in range(0, 10, 1):
            create_test_insuree(custom_props={'chfid': f"54656844{i}"})

        super(ImportInsureeTest, self).setUp()

        self.user = create_test_interactive_user(username=_TEST_USER_NAME, custom_props=_TEST_DATA_USER)
        test_location = _TEST_LOCATIONS

        for locations in test_location:
            test_region = create_test_location('R', custom_props={"name": locations['region']})
            test_district = create_test_location('D', custom_props={"name": locations['district'],
                                                                    "parent_id": test_region.id})
            test_municipality = create_test_location('M', custom_props={"name": locations['municipality'],
                                                                        "parent_id": test_district.id})
            for villages in locations['villages']:
                create_test_location('V', custom_props={"name": villages, "parent_id": test_municipality.id})

    def test_simple_import(self):
        region = Location.objects.all() \
            .filter(validity_to__isnull=True) \
            .filter(name='Batha Region', type='R').first()
        if not region:
            region = create_test_location('R', custom_props={'name': 'Batha Region', 'code': 'R99'})
        district = Location.objects.all() \
            .filter(validity_to__isnull=True) \
            .filter(name='Batha', type='D', parent=region).first()
        if not district:
            district = create_test_location('D', custom_props={'name': 'Batha', 'code': 'R99D1', 'parent': region})
        ward = Location.objects.all() \
            .filter(validity_to__isnull=True) \
            .filter(name='Batha', type='M', parent=district).first()
        if not ward:
            ward = create_test_location('M', custom_props={'name': 'BEGOU', 'code': 'R99D1M1', 'parent': district})
        village = Location.objects.all() \
            .filter(validity_to__isnull=True) \
            .filter(name='Batha', type='V', parent=ward).first()
        if not village:
            village = create_test_location('V', custom_props={'name': 'Boua', 'code': 'R99D1M1V', 'parent': ward})

        dir_path = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
        resource = InsureeResource(user=self.user)
        # with Patch("ImportExportConfig.im_export_date_format", '%m/%d/%Y')
        with open(os.path.join(dir_path, 'tests/import_example.csv'), 'r') as f:
            imported_data = resource \
                .validate_and_sort_dataset(Dataset(headers=InsureeResource.insuree_headers).load(f.read()))
            result = resource.import_data(
                imported_data, dry_run=True, use_transactions=True,
                collect_failed_rows=False,
            )
            self.assertEqual(result.has_errors(), False)

    def test_simple_export(self):
        result = InsureeResource(self.user).export().dict
        self.assertTrue(result)
