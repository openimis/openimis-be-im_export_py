"""OP-3322: insuree export and import stay inside the user's locations."""
import csv
import io

from django.test import TestCase

from core.test_helpers import create_right_only_user
from im_export.services import InsureeImportExportService
from im_export.tests.test_round_trip import _csv_file, _location_columns
from insuree.models import Insuree
from insuree.test_helpers import create_test_insuree
from location.test_helpers import create_test_village

Strategy = InsureeImportExportService.Strategy


class InsureeImportExportScopeTest(TestCase):

    def setUp(self):
        super().setUp()
        self.village_in = create_test_village()
        self.village_out = create_test_village()
        self.head_in = create_test_insuree(
            is_head=True, custom_props={"chf_id": "700000201", "last_name": "Inside"},
            family_custom_props={"location": self.village_in})
        self.head_out = create_test_insuree(
            is_head=True, custom_props={"chf_id": "700000202", "last_name": "Outside"},
            family_custom_props={"location": self.village_out})
        # Created last: building the user clears the location caches.
        self.user = create_right_only_user(
            "test_im_export_scope", [], district_codes=[self.village_in.parent.parent.code])
        self.service = InsureeImportExportService(self.user)

    def _row(self, village, **values):
        return {
            "head_insuree_number": values.get("insuree_number"),
            "last_name": "Imported", "other_names": "Row", "dob": "1990-01-01",
            "sex": self.head_in.gender.code, **_location_columns(village), **values,
        }

    def test_export_holds_only_the_insurees_in_scope(self):
        _, data = self.service.export_insurees("csv")
        numbers = {row["insuree_number"] for row in csv.DictReader(io.StringIO(data))}
        self.assertIn(self.head_in.chf_id, numbers)
        self.assertNotIn(self.head_out.chf_id, numbers)

    def test_import_refuses_a_village_out_of_scope(self):
        success, totals, errors = self.service.import_insurees(_csv_file([
            self._row(self.village_in, insuree_number="700000210"),
            self._row(self.village_out, insuree_number="700000211"),
        ]), dry_run=True, strategy=Strategy.INSERT)
        self.assertFalse(success)
        self.assertEqual(totals["invalid"], 1, (totals, errors))
        self.assertEqual(totals["created"], 1, (totals, errors))
        self.assertTrue(any("outside your area" in e for e in errors), errors)

    def test_import_does_not_attach_a_member_to_a_family_out_of_scope(self):
        success, _, errors = self.service.import_insurees(_csv_file([
            self._row(self.village_in, insuree_number="700000212",
                      head_insuree_number=self.head_out.chf_id),
        ]), strategy=Strategy.INSERT)
        self.assertFalse(success)
        self.assertTrue(any("not found" in e for e in errors), errors)
        self.assertFalse(Insuree.objects.filter(chf_id="700000212").exists())

    def test_update_refuses_an_insuree_out_of_scope(self):
        row = self._row(self.village_in, insuree_number=self.head_out.chf_id, last_name="Renamed")
        success, _, errors = self.service.import_insurees(_csv_file([row]), strategy=Strategy.UPDATE)
        self.assertFalse(success)
        self.assertTrue(any("outside your area" in e for e in errors), errors)
        self.head_out.refresh_from_db()
        self.assertEqual(self.head_out.last_name, "Outside")
