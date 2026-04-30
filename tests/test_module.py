
# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

import datetime

from trytond.modules.company.tests import CompanyTestMixin
from trytond.modules.company.tests import create_company, set_company
from trytond.pool import Pool
from trytond.tests.test_tryton import ModuleTestCase, with_transaction


class PartyPersonalDataPermissionTestCase(CompanyTestMixin, ModuleTestCase):
    'Test PartyPersonalDataPermission module'
    module = 'party_personal_data_permission'

    @with_transaction()
    def test_personal_data_permission_report_execute(self):
        pool = Pool()
        Party = pool.get('party.party')
        Address = pool.get('party.address')
        Permission = pool.get('party.personal_data.permission')
        Report = pool.get('party.personal_data.permission.report',
            type='report')

        company = create_company()
        with set_company(company):
            company.party.addresses = [Address(
                    street='Main street 1',
                    postal_code='08001',
                    city='Barcelona',
                    )]
            company.party.phone = '935555555'
            company.party.fax = '934444444'
            company.party.email = 'info@example.com'
            company.party.website = 'https://example.com'
            company.party.save()

            party = Party(
                name='John Doe',
                birthdate=datetime.date(1980, 1, 1),
                )
            party.addresses = [Address(
                    street='Patient street 1',
                    postal_code='08002',
                    city='Barcelona',
                    )]
            party.save()

            permission, = Permission.create([{
                        'party': party.id,
                        'company': company.id,
                        'issue_date': datetime.date.today(),
                        'accept_sms': True,
                        }])

            ext, content, _, _ = Report.execute([permission.id], {})
            self.assertEqual(ext, 'pdf')
            self.assertTrue(content)
            self.assertTrue(content.startswith(b'%PDF'))


del ModuleTestCase
