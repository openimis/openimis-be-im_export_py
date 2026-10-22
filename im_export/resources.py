from django.db.models import Q
from django.utils.translation import gettext as _
from core.datetimes.ad_datetime import datetime
from im_export.apps import ImportExportConfig
from insuree.models import Insuree, Family, Gender
from location.models import Location
import logging
from import_export import fields, resources, widgets
logger = logging.getLogger(__name__)


class CharRequiredWidget(widgets.CharWidget):
    def clean(self, value, row=None, *args, **kwargs):
        val = super().clean(value)
        if val:
            return val
        else:
            raise ValueError('this field is required')


class ForeignkeyRequiredWidget(widgets.ForeignKeyWidget):
    def clean(self, value, row=None, *args, **kwargs):
        if value:
            return self.get_queryset(value, row, *args, **kwargs).get(**{self.field: value})
        else:
            raise ValueError(self.field + ' required')


def get_location_str_filter(str):
    return Q(code=str) | Q(name=str)  # | Q(uuid=str) | Q(id=int(str) if str.isdigit() else None)


def get_locations_ids(row, regions, districts, municipalities, villages):
    uniq_region = str(row['region'] or '').strip()
    if uniq_region not in regions:
        region_model = Location.objects.all().filter(validity_to__isnull=True) \
            .filter(get_location_str_filter(uniq_region)).first()
        if region_model:
            regions[uniq_region] = region_model.id
        else:
            raise ValueError('Location {} not found in the database'.format(uniq_region))

    district = str(row['district'] or '').strip()
    uniq_district = uniq_region + "|" + district
    if uniq_district not in districts:
        district_model = Location.objects.all() \
            .filter(validity_to__isnull=True, parent_id=regions[uniq_region]) \
            .filter(get_location_str_filter(district)).first()
        if district_model:
            districts[uniq_district] = district_model.id
        else:
            raise ValueError('Location {} not found in the database'.format(uniq_district))

    municipality = str(row['municipality'] or '').strip()
    uniq_municipality = uniq_district + "|" + municipality
    if uniq_municipality not in municipalities:
        municipality_model = Location.objects.all() \
            .filter(validity_to__isnull=True, parent_id=districts[uniq_district]) \
            .filter(get_location_str_filter(municipality)).first()
        if municipality_model:
            municipalities[uniq_municipality] = municipality_model.id
        else:
            raise ValueError('Location {} not found in the database'.format(uniq_municipality))

    village = str(row['village'] or '').strip()
    uniq_village = uniq_municipality + "|" + village
    if uniq_village not in villages:
        village_model = Location.objects.all() \
            .filter(validity_to__isnull=True, parent_id=municipalities[uniq_municipality]) \
            .filter(get_location_str_filter(village)).first()
        if village_model:
            villages[uniq_village] = village_model.id
        else:
            raise ValueError('Location {} not found in the database'.format(uniq_village))

    return regions[uniq_region], districts[uniq_district], municipalities[uniq_municipality], villages[uniq_village]


def validate_and_preprocess(dataset):
    # change the region names/codes into id.
    # a village can have homonyms therefore the parent must be taken into account
    # check if head insuree
    # check if insuree number is unique
    regions = dict()
    districts = dict()
    municipalities = dict()
    villages = dict()

    regions_ids = list()
    districts_ids = list()
    municipalities_ids = list()
    villages_ids = list()
    head = list()
    empty_indices = list()

    insuree_no_seen = set()

    # we don't process
    for idx, row in enumerate(dataset.dict, start=1):
        row_str = ''.join([str(col or '') for col in row])
        if row_str.strip() == '':
            empty_indices.append(idx)
        else:
            # Check locations
            region_id, district_id, municipality_id, village_id = \
                get_locations_ids(row, regions, districts, municipalities, villages)
            regions_ids.append(region_id)
            districts_ids.append(district_id)
            municipalities_ids.append(municipality_id)
            villages_ids.append(village_id)

            insuree_number = row['insuree_number']
            if insuree_number not in insuree_no_seen:
                insuree_no_seen.add(insuree_number)

            if insuree_number == row['head_insuree_number']:
                head.append(True)
            else:
                head.append(False)

    for index in sorted(empty_indices, reverse=True):
        del dataset[index]

    if len(insuree_no_seen) != len(dataset['insuree_number']):
        raise ValueError('There are duplicates of insurance number in the list')

    dataset.append_col(head, 'head')
    dataset.append_col(villages_ids, 'village_id')
    dataset.append_col(municipalities_ids, 'municipality_id')
    dataset.append_col(districts_ids, 'district_id')
    dataset.append_col(regions_ids, 'region_id')


class InsureeResource(resources.ModelResource):
    insuree_headers = ['head_insuree_number', 'insuree_number', 'last_name', 'other_names', 'dob', 'sex', 'village',
                       'municipality', 'district', 'region']

    head_insuree_number = fields.Field(
        attribute='family',
        column_name='head_insuree_number',
        widget=ForeignkeyRequiredWidget(Family, field='head_insuree__chf_id'),
        readonly=True,
    )

    insuree_number = fields.Field(
        attribute='chf_id',
        column_name='insuree_number',
    )

    last_name = fields.Field(
        attribute='last_name',
        column_name='last_name',
    )

    other_names = fields.Field(
        attribute='other_names',
        column_name='other_names',
    )

    dob = fields.Field(
        attribute='dob',
        column_name='dob',
        widget=widgets.DateWidget(format=ImportExportConfig.im_export_date_format)
    )

    sex = fields.Field(
        attribute='gender',
        column_name='sex',
        widget=ForeignkeyRequiredWidget(Gender, field='code'),
    )

    village = fields.Field(
        attribute='current_village',
        column_name='village',
        widget=ForeignkeyRequiredWidget(Location, field='name'),
        readonly=True
    )

    # readonly, just for export and import validation
    municipality = fields.Field(
        attribute='current_village',
        column_name='municipality',
        widget=ForeignkeyRequiredWidget(Location, field='parent__name'),
        readonly=True
    )

    # readonly, just for export and import validation
    district = fields.Field(
        attribute='current_village',
        column_name='district',
        widget=ForeignkeyRequiredWidget(Location, field='parent__parent__name'),
        readonly=True
    )

    # readonly, just for export and import validation
    region = fields.Field(
        attribute='current_village',
        column_name='region',
        widget=ForeignkeyRequiredWidget(Location, field='parent__parent__parent__name'),
        readonly=True
    )

    # Import strategies, see InsureeImportExportService.Strategy.
    STRATEGY_INSERT = 'INSERT'
    STRATEGY_UPDATE = 'UPDATE'
    STRATEGY_INSERT_UPDATE = 'INSERT_UPDATE'

    def __init__(self, user, queryset=None, strategy=STRATEGY_INSERT):
        """
        @param user: User to be used for location rights for import and export, and for audit_user_id
        @param queryset: Queryset to use for export, Default to full quetyset
        @param strategy: INSERT (new insurees only), UPDATE (existing only) or INSERT_UPDATE
        """
        super().__init__()
        self._queryset = queryset
        self._user = user
        self.strategy = strategy

    @classmethod
    def validate_and_sort_dataset(cls, dataset):
        validate_and_preprocess(dataset)
        return dataset.sort('head', reverse=True)

    # --- export ---------------------------------------------------------------

    @staticmethod
    def _effective_village(insuree):
        # A member that lives at the family's location has no current_village of its own.
        if insuree.current_village_id:
            return insuree.current_village
        return insuree.family.location if insuree.family_id else None

    @classmethod
    def _village_ancestor_name(cls, insuree, depth):
        location = cls._effective_village(insuree)
        for _level in range(depth):
            location = location.parent if location else None
        return location.name if location else ''

    def dehydrate_village(self, insuree):
        return self._village_ancestor_name(insuree, 0)

    def dehydrate_municipality(self, insuree):
        return self._village_ancestor_name(insuree, 1)

    def dehydrate_district(self, insuree):
        return self._village_ancestor_name(insuree, 2)

    def dehydrate_region(self, insuree):
        return self._village_ancestor_name(insuree, 3)

    # --- import ---------------------------------------------------------------

    def after_init_instance(self, instance, new, row, **kwargs):
        super().after_init_instance(instance, new, row, **kwargs)
        if new and self.strategy == self.STRATEGY_UPDATE:
            raise ValueError(_("Insuree %(insuree_number)s does not exist") % {"insuree_number": row['insuree_number']})
        if not new and self.strategy == self.STRATEGY_INSERT:
            raise ValueError(_("Insuree %(insuree_number)s already exists") % {"insuree_number": row['insuree_number']})
        if not new:
            family_head = instance.family.head_insuree.chf_id if instance.family_id else None
            if family_head != row['head_insuree_number']:
                raise ValueError(_("Moving insuree %(insuree_number)s to another family is not supported")
                                 % {"insuree_number": row['insuree_number']})
            if bool(instance.head) != bool(row['head']):
                raise ValueError(_("Changing the head of the family of insuree %(insuree_number)s is not supported")
                                 % {"insuree_number": row['insuree_number']})

    def import_instance(self, instance, row, **kwargs):
        # Family moves of an existing head, applied in do_instance_save.
        instance._im_export_family_location_id = None
        if not instance.id:
            instance.head = row['head']
            instance.current_village_id = row['village_id']
            instance.card_issued = False
            if not instance.head:
                family = Family.objects.all().filter(validity_to__isnull=True) \
                    .select_related('location') \
                    .get(head_insuree__chf_id=row['head_insuree_number'])
                instance.family = family
                # a member living at the family's location keeps no current_village
                if family.location_id == row['village_id']:
                    instance.current_village_id = None
        elif instance.head:
            # The head's location is the family's location.
            if instance.family.location_id != row['village_id']:
                instance._im_export_family_location_id = row['village_id']
        else:
            instance.current_village_id = None if instance.family.location_id == row['village_id'] \
                else row['village_id']

        # important to be at the end
        super().import_instance(instance, row, **kwargs)

    def skip_row(self, instance, original, row, import_validation_errors=None):
        if original is None or import_validation_errors:
            return False
        compared = ('last_name', 'other_names', 'dob', 'gender_id', 'current_village_id')
        return all(getattr(instance, f) == getattr(original, f) for f in compared) \
            and instance._im_export_family_location_id is None

    def before_save_instance(self, instance, row, **kwargs):
        if hasattr(instance, 'audit_user_id'):
            if self._user and self._user._u.id:
                instance.audit_user_id = self._user._u.id
            else:
                instance.audit_user_id = -1
                logger.warning(_("im_export.save_without_user"))

    def do_instance_save(self, instance, is_create):
        # Only called when the row is really written (not on a dry run without transactions).
        if not is_create:
            # save_history copies the object it is called on: copy the stored version, read
            # through _base_manager because Insuree.objects may answer from a cache that
            # already holds the modified instance.
            Insuree._base_manager.get(id=instance.id).save_history()
            instance.validity_from = datetime.now()
        instance.save()
        if is_create and instance.head:
            instance.family = self.create_family(instance)
            instance.current_village = None
            instance.save()
        elif instance._im_export_family_location_id:
            family = Family._base_manager.get(id=instance.family_id)
            family.save_history()
            family.location_id = instance._im_export_family_location_id
            family.validity_from = datetime.now()
            family.audit_user_id = instance.audit_user_id
            family.save()

    def create_family(self, instance):
        return Family.objects.create(**{
            'validity_from': datetime.now(),
            'audit_user_id': self._user.i_user.id,
            'head_insuree': instance,
            'location': instance.current_village,
            'is_offline': False,
        })

    def get_queryset(self):
        queryset = self._queryset if self._queryset else super().get_queryset()
        return queryset \
            .filter(validity_to__isnull=True) \
            .select_related('gender', 'current_village', 'family', 'family__location', 'family__location__parent',
                            'family__location__parent__parent', 'family__location__parent__parent__parent')

    class Meta:
        model = Insuree
        import_id_fields = ('insuree_number',)
        fields = ('insuree_number', 'head_insuree_number', 'last_name', 'other_names', 'dob', 'sex', 'village',
                  'municipality', 'district', 'region')
