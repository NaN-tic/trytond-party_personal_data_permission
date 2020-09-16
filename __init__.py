# This file is part party_personal_data_permission module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import Pool
from . import party
from . import attachment

def register():
    Pool.register(
        party.Party,
        party.PersonalDataPermission,
        party.DeviceConfiguration,
        attachment.Attachment,
        module='party_personal_data_permission', type_='model')
    Pool.register(
        party.PersonalDataPermissionReport,
        module='party_personal_data_permission', type_='report')
