# This file is part party_personal_data_permission module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
import unittest


from trytond.tests.test_tryton import ModuleTestCase
from trytond.tests.test_tryton import suite as test_suite


class PartyPersonalDataPermissionTestCase(ModuleTestCase):
    'Test Party Personal Data Permission module'
    module = 'party_personal_data_permission'


def suite():
    suite = test_suite()
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(
            PartyPersonalDataPermissionTestCase))
    return suite
