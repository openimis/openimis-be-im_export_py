import csv
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from core.test_helpers import create_test_interactive_user, create_admin_role
from im_export.resources import InsureeResource
from im_export.services import InsureeImportExportService
from insuree.models import Insuree, Family
from insuree.test_helpers import create_test_insuree
from location.test_helpers import create_test_village

Strategy = InsureeImportExportService.Strategy


def _csv_file(rows):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=InsureeResource.insuree_headers)
    writer.writeheader()
    writer.writerows(rows)
    return SimpleUploadedFile("insurees.csv", out.getvalue().encode(), content_type="text/csv")


def _location_columns(village):
    return {
        "village": village.name,
        "municipality": village.parent.name,
        "district": village.parent.parent.name,
        "region": village.parent.parent.parent.name,
    }


class InsureeRoundTripTest(TestCase):
    """OP-2296: an insuree export can be imported back, and the update strategies work."""

    def setUp(self):
        super().setUp()
        self.user = create_test_interactive_user(
            username="test_im_export_round_trip",
            custom_props={"roles": [create_admin_role().id]},
        )
        self.service = InsureeImportExportService(self.user)
        self.village = create_test_village()
        self.head = create_test_insuree(
            is_head=True, custom_props={"chf_id": "700000001", "last_name": "Head"},
            family_custom_props={"location": self.village},
        )
        # A member that lives at the family's location: current_village stays empty.
        self.member = create_test_insuree(
            with_family=False,
            custom_props={"chf_id": "700000002", "last_name": "Member",
                          "family": self.head.family, "current_village": None},
        )

    def _export_rows(self):
        _, data = self.service.export_insurees("csv")
        return {row["insuree_number"]: row for row in csv.DictReader(io.StringIO(data))}

    def _row(self, insuree, **changes):
        return {
            "head_insuree_number": insuree.family.head_insuree.chf_id,
            "insuree_number": insuree.chf_id,
            "last_name": insuree.last_name,
            "other_names": insuree.other_names,
            "dob": insuree.dob.isoformat(),  # the format the export writes
            "sex": insuree.gender.code,
            **_location_columns(self.village),
            **changes,
        }

    def test_export_falls_back_to_the_family_location(self):
        rows = self._export_rows()
        for chf_id in ("700000001", "700000002"):
            for column, expected in _location_columns(self.village).items():
                self.assertEqual(rows[chf_id][column], expected, f"{chf_id} {column}")

    def test_export_can_be_imported_back_with_insert_update(self):
        rows = [r for r in self._export_rows().values() if r["insuree_number"].startswith("7000000")]
        success, totals, errors = self.service.import_insurees(
            _csv_file(rows), dry_run=True, strategy=Strategy.INSERT_UPDATE)
        self.assertTrue(success, errors)
        self.assertEqual(totals["skipped"], 2, totals)

    def test_insert_creates_the_family_of_a_new_head(self):
        success, _, errors = self.service.import_insurees(_csv_file([
            self._row(self.head, head_insuree_number="700000010", insuree_number="700000010"),
            self._row(self.head, head_insuree_number="700000010", insuree_number="700000011"),
        ]), strategy=Strategy.INSERT)
        self.assertTrue(success, errors)
        head = Insuree.objects.get(chf_id="700000010", validity_to__isnull=True)
        member = Insuree.objects.get(chf_id="700000011", validity_to__isnull=True)
        self.assertTrue(head.head)
        self.assertEqual(head.family.location_id, self.village.id)
        self.assertEqual(member.family_id, head.family_id)
        self.assertIsNone(member.current_village_id)

    def test_insert_refuses_an_existing_insuree(self):
        success, _, errors = self.service.import_insurees(
            _csv_file([self._row(self.member)]), dry_run=True, strategy=Strategy.INSERT)
        self.assertFalse(success)
        self.assertTrue(any("already exists" in e for e in errors), errors)

    def test_update_changes_an_existing_insuree_and_keeps_its_history(self):
        success, totals, errors = self.service.import_insurees(
            _csv_file([self._row(self.member, last_name="Renamed")]), strategy=Strategy.UPDATE)
        self.assertTrue(success, errors)
        self.assertEqual(totals["updated"], 1, totals)
        current = Insuree.objects.get(chf_id="700000002", validity_to__isnull=True)
        self.assertEqual(current.last_name, "Renamed")
        # save_history keeps the previous version as a row pointing at the current one
        self.assertTrue(
            Insuree.objects.filter(legacy_id=current.id, last_name="Member").exists(),
            list(Insuree.objects.filter(chf_id="700000002").values("id", "legacy_id", "last_name", "validity_to")))

    def test_update_moves_the_family_when_the_head_changes_village(self):
        other = create_test_village()
        success, _, errors = self.service.import_insurees(
            _csv_file([self._row(self.head, **_location_columns(other))]), strategy=Strategy.UPDATE)
        self.assertTrue(success, errors)
        family = Family.objects.get(id=self.head.family_id)
        self.assertEqual(family.location_id, other.id)

    def test_update_refuses_an_unknown_insuree(self):
        success, _, errors = self.service.import_insurees(
            _csv_file([self._row(self.member, insuree_number="700000099")]),
            dry_run=True, strategy=Strategy.UPDATE)
        self.assertFalse(success)
        self.assertTrue(any("does not exist" in e for e in errors), errors)

    def test_update_refuses_to_move_an_insuree_to_another_family(self):
        other_head = create_test_insuree(is_head=True, custom_props={"chf_id": "700000003"})
        success, _, errors = self.service.import_insurees(
            _csv_file([self._row(self.member, head_insuree_number=other_head.chf_id)]),
            dry_run=True, strategy=Strategy.UPDATE)
        self.assertFalse(success)
        self.assertTrue(any("another family" in e for e in errors), errors)


class InsureeLocationColumnsTest(TestCase):
    """OCM-700: location columns follow the location type, and a bad location only rejects its row."""

    def setUp(self):
        super().setUp()
        self.user = create_test_interactive_user(
            username="test_im_export_loc_cols",
            custom_props={"roles": [create_admin_role().id]},
        )
        self.service = InsureeImportExportService(self.user)
        self.village = create_test_village()

    def _export_rows(self):
        _, data = self.service.export_insurees("csv")
        return {row["insuree_number"]: row for row in csv.DictReader(io.StringIO(data))}

    def test_export_of_a_family_above_village_level_keeps_the_columns_by_type(self):
        municipality = self.village.parent
        self.assertEqual(municipality.type, "W")
        head = create_test_insuree(
            is_head=True, custom_props={"chf_id": "700000101"}, family_custom_props={"location": municipality})
        # The insuree lives at the family's location: the export falls back to the family location.
        Insuree.objects.filter(id=head.id).update(current_village=None)
        self.assertEqual(Family.objects.get(id=head.family_id).location_id, municipality.id)
        row = self._export_rows()["700000101"]
        self.assertEqual(row["village"], "")
        self.assertEqual(row["municipality"], municipality.name)
        self.assertEqual(row["district"], municipality.parent.name)
        self.assertEqual(row["region"], municipality.parent.parent.name)

    def test_import_reports_a_row_with_unknown_locations_as_invalid(self):
        gender = create_test_insuree(is_head=True, custom_props={"chf_id": "700000102"}).gender
        good = {
            "head_insuree_number": "700000110", "insuree_number": "700000110", "last_name": "Good",
            "other_names": "Row", "dob": "1990-01-01", "sex": gender.code, **_location_columns(self.village),
        }
        bad = {
            **good, "head_insuree_number": "700000111", "insuree_number": "700000111", "last_name": "Bad",
            "village": "", "municipality": "", "district": "", "region": "No such region",
        }
        success, totals, errors = self.service.import_insurees(
            _csv_file([good, bad]), dry_run=True, strategy=Strategy.INSERT)
        self.assertFalse(success)
        self.assertEqual(totals["sent"], 2, (totals, errors))
        self.assertEqual(totals["invalid"], 1, (totals, errors))
        self.assertEqual(totals["created"], 1, (totals, errors))
        self.assertEqual(totals["failed"], 0, (totals, errors))
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("No such region", errors[0])
