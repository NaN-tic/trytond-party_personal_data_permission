# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
import subprocess
import os
import requests
import base64
from trytond.model import ModelSQL, ModelView, fields, Workflow, MatchMixin
from trytond.pool import PoolMeta, Pool
from trytond.pyson import Eval, Not, Equal, Bool
from trytond.transaction import Transaction
from trytond.modules.jasper_reports.jasper import JasperReport
from trytond.config import config
from trytond.i18n import gettext
from trytond.exceptions import UserError


class VidCloudHelper(object):

    def __init__(self):
        self.ip = config.get('vidsigner', 'connection')

        self.user = config.get('vidsigner', 'user')
        self.password = config.get('vidsigner', 'pass')
        self.auth = base64.b64encode(bytes('%s:%s' % (self.user,
                    self.password), 'utf-8'))
        self.doc_gui = None
        self.device_name = None

    def set_device_name(self, name):
        self.device_name = name

    def get_devices(self):
        if not self.ip:
            return []
        url = self.ip + '/api/devices'
        response = requests.request('GET', url,
            auth=(self.user, self.password))
        if response.status_code == 404:
            return []
        return response.json()

    def upload_document(self, document, document_name, party, pos):
        """
        Uploads a documents with the post method to be signed
        document -- pdf to be signed encoded in base64
        document_name -- Name of the document
        """
        x, y, sx, sy = pos

        url = self.ip + '/api/documents'
        doc = self._get_encoded_pdf(document[-2])
        data = {
            'DocContent': doc,
            'FileName': document_name,
            'OrderedSignatures': 'true',
            'Signers': [
                {
                    'DeviceName': self.device_name,
                    'NumberID': party.personal_identifier.code,
                    'SignerName': party.name,
                    'TypeOfID': 'NIF',
                    'Visible':
                        {
                        'Page': 1,
                        'PosX': x,
                        'PosY': y,
                        'SizeX': sx,
                        'SizeY': sy
                        },
                }
            ]
        }
        response = requests.request('POST', url, json=data,
            auth=(self.user, self.password))
        response_text = eval(response.text)
        self.doc_gui = response_text['DocGUI']
        return self.doc_gui

    def get_signed_pdf(self):
        if not self.doc_gui:
            raise Exception('DocGUI', 'No DOC GUI value for current process')

        url = self.ip + '/api/signeddocuments/' + self.doc_gui
        response = requests.request('GET', url=url,
            auth=(self.user, self.password))

        if response.status_code not in [200, 409]:
            return (False, response.text, response.status_code)
        return (True, response.status_code, response.json())

    def get_document_status(self):
        if not self.doc_gui:
            raise Exception('DocGUI', 'No DOC GUI value for current process')

        url = self.ip + '/api/documentinfo/' + self.doc_gui
        response = requests.request('GET', url=url,
            auth=(self.user, self.password))

        if response.status_code != 200:
            return (False, response.text)
        return (True, (response.json()))

    def delete_document(self, signed):
        path = '/api/%s/' % ('signeddocuments' if signed else 'documents')

        if signed and not self.doc_gui:
            raise Exception('DocGUI', 'No DOC GUI value for current process')

        if signed:
            url = self.ip + path + self.doc_gui
        else:
            url = self.ip + path

        response = requests.request('DELETE', url=url,
            auth=(self.user, self.password))
        if response.status_code not in [200, 204]:
            return False
        self.doc_gui = None
        return True

    def _get_encoded_pdf(self, data):
        return base64.b64encode(data)


class Party(metaclass=PoolMeta):
    __name__ = 'party.party'
    birthdate = fields.Date('Birthdate')
    age = fields.Function(fields.Integer('Age'), 'on_change_with_age')
    personal_data_permission = fields.Function(fields.Boolean(
            'Personal Data Permission Signed'), 'get_personal_data_permission',
        searcher='search_personal_data_permission')
    personal_identifier = fields.Function(fields.Many2One('party.identifier',
            'Personal Identifier'), 'on_change_with_personal_identifier')

    @classmethod
    def __register__(cls, module_name):
        handler = cls.__table_handler__(module_name)
        handler.column_rename('age', 'birthdate')
        super().__register__(module_name)

    @fields.depends('birthdate')
    def on_change_with_age(self, name=None):
        Date = Pool().get('ir.date')
        today = Date.today()
        if not self.birthdate:
            return
        return today.year - self.birthdate.year - ((today.month, today.day) <
            (self.birthdate.month, self.birthdate.day))

    @classmethod
    def personal_identifier_types(cls):
        return ['es_nie', 'es_dni', 'eu_vat']

    @fields.depends('identifiers')
    def on_change_with_personal_identifier(self, name=None):
        if not self.identifiers:
            return
        types = self.personal_identifier_types()
        for identifier in self.identifiers:
            if identifier.type in types:
                return identifier.id

    def get_personal_data_permission(self, name=None):
        Permission = Pool().get('party.personal_data.permission')
        res = Permission.search([
                ('party', '=', self),
                ('state', '=', 'signed'),
                ], limit=1)
        return bool(res)

    @classmethod
    def search_personal_data_permission(cls, name, clause):
        Permission = Pool().get('party.personal_data.permission')

        operator = '=' if clause[2] else '!='
        # TODO: Use a one2many field instead
        res = Permission.search([
                ('state', operator, 'signed'),
                ])
        return [('id', 'in', [x.party.id for x in res])]


class PersonalDataPermission(Workflow, ModelSQL, ModelView):
    'Party Personal Data Permission'
    __name__ = 'party.personal_data.permission'

    issue_date = fields.Date('Issue Date', required=True)
    revocation_date = fields.Date('Revocation Date', states={
            'invisible': Not(Equal(Eval('state'), 'revoked'))
            })
    party = fields.Many2One('party.party', 'Party', required=True,
        context={
            'company': Eval('company'),
            },
        depends=['company'])
    guardian = fields.Many2One('party.party', 'Guardian', states={
            'required': Eval('party_age', 18) < 18,
            },
        context={
            'company': Eval('company'),
            },
        depends=['company'])
    party_age = fields.Function(fields.Integer('Age', states={
                'invisible': ~Bool(Eval('party'))}),
            'on_change_with_party_age')

    # PDF document
    document = fields.Many2One('ir.attachment', 'Document', states={
            'required': Eval('state') == 'signed',
            'readonly': Eval('state').in_(['signed', 'revoked']),
            }, depends=['state'])
    document_pdf = fields.Function(fields.Binary('Document',
            states={
                'readonly': Eval('state').in_(['signed', 'revoked']),
                }), 'on_change_with_document_pdf', setter='set_document')
    # JPG document (converted from document)
    document_image_attach = fields.Many2One('ir.attachment', 'Document Image',
        states={
            'required': Eval('state') == 'signed',
            'readonly': Eval('state').in_(['signed', 'revoked']),
            }, depends=['state'])

    document_image = fields.Function(fields.Binary('Document Image',
            states={
                'invisible': Eval('state').in_(['draft', 'waiting',
                        'rejected']),
                }, depends=['state'], readonly=True),
            'on_change_with_document_image')

    file_name = fields.Function(fields.Char('File name'),
        'on_change_with_file_name')

    doc_gui = fields.Char('Document ID')

    state = fields.Selection([
            ('draft', 'Draft'),
            ('waiting', 'Waiting'),
            ('signed', 'Signed'),
            ('rejected', 'Rejected'),
            ('revoked', 'Revoked'),
            ], 'State', readonly=True)
    company = fields.Many2One('company.company', 'Company',
        states={
            'invisible': True,
        })
    accept_sms = fields.Boolean('Accept SMS',
        help='If marked the party accepts beeing sent information',
        states={
            'readonly': Eval('state') != 'draft'
        })

    @classmethod
    def __register__(cls, module_name):
        handler = cls.__table_handler__(module_name)
        handler.column_rename('pacient', 'party')
        super().__register__(module_name)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._transitions |= set((
            ('draft', 'waiting'),
            ('draft', 'signed'),
            ('waiting', 'signed'),
            ('waiting', 'rejected'),
            ('signed', 'revoked'),
            ))

        cls._buttons.update({
                'wait': {
                    'invisible': Eval('state') != 'draft',
                    'readonly': Bool(Eval('document_pdf'))
                },
                'collect': {
                    'invisible': Eval('state') != 'waiting',
                    'readonly': Bool(Eval('document_pdf'))
                },
                'sign': {
                    'invisible': Eval('state').in_(
                        ['signed', 'revoked', 'rejected']),
                    'readonly': Not(Bool(Eval('document_pdf')))
                },
                'revoke': {
                    'invisible': Eval('state') != 'signed'  # Needed?
                }
                })

    @staticmethod
    def default_state():
        return 'draft'

    @staticmethod
    def default_accept_sms():
        return True

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @staticmethod
    def default_issue_date():
        Date = Pool().get('ir.date')
        return Date.today()

    @staticmethod
    def default_revocation_date():
        Date = Pool().get('ir.date')
        return Date.today()

    @fields.depends('document')
    def on_change_with_file_name(self, name=None):
        if not self.document:
            return
        return self.document.name

    @fields.depends('document_image_attach')
    def on_change_with_document_image(self, name=None):
        if self.document_image_attach:
            return self.document_image_attach.data

    @fields.depends('document')
    def on_change_with_document_pdf(self, name=None):
        if self.document:
            return self.document.data

    @classmethod
    def set_document(cls, records, name, value):
        pool = Pool()
        Attachment = pool.get('ir.attachment')

        if not value:
            return

        records_to_write = []

        for record in records:
            attach = Attachment(
                name='signed.pdf',
                type='data',
                data=value,
                resource=str(record))
            attach, = Attachment.create([attach._save_values])
            records_to_write.extend(([record], {
                'document': attach.id}))

        if records_to_write:
            cls.write(*records_to_write)

    @staticmethod
    def to_jpg(pdf_binary):
        """
        Vidsigner will return a PDF document. This method should use
        unix "convert" utility and return a JPG binary which can be stored in
        a binary field.
        """
        path = '/'.join(pdf_binary.file_path.split('/')[:-1])

        jpg_name = pdf_binary.file_id + '.jpg'
        jpg_path = path + '/' + jpg_name

        pdf_binary_file_path = pdf_binary.file_path
        identify_cmd = ['identify', '-format', '%n\n', pdf_binary_file_path]
        head_cmd = ['head', '-1']
        identify_process = subprocess.Popen(identify_cmd,
            stdout=subprocess.PIPE)
        process = subprocess.Popen(head_cmd, stdin=identify_process.stdout,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = process.communicate()
        frames = int(out) if not err else 0
        if frames > 1:
            pdf_binary_file_path += '[0]'

        subprocess.call([
                'convert', '-quality', '90', '-density', '200x200',
                '-background', 'white', '-alpha', 'remove',
                pdf_binary_file_path, jpg_path
                ])
        return (jpg_path, jpg_name)

    @fields.depends('party')
    def on_change_with_party_age(self, name=None):
        if not self.party:
            return
        return self.party.age

    @classmethod
    def copy(cls, shipments, default=None):
        if default is None:
            default = {}
        default = default.copy()
        default['document'] = None
        default['document_image'] = None
        default['doc_gui'] = None
        default['accept_sms'] = True
        return super().copy(shipments, default=default)

    @classmethod
    @ModelView.button
    @Workflow.transition('waiting')
    def wait(cls, permissions):
        """
        Send data to vidsigner
        """
        pool = Pool()
        ActionReport = pool.get('ir.action.report')
        User = pool.get('res.user')
        PersonalDataPermissionReport = pool.get(
            'party.personal_data.permission.report', type='report')
        DeviceConfig = pool.get('party.permission.device.configuration')

        action_report, = ActionReport.search([
                ('report_name', '=', 'party.personal_data.permission.report')
                ])
        data = {
            'model': 'party.personal_data.permission',
            'action_id': action_report.id,
            'ids': [p.id for p in permissions],
            'id': permissions[0],
            }
        user = User(Transaction().user)

        to_write = []
        for permission in permissions:
            helper = VidCloudHelper()
            if (not permission.guardian and not
                    permission.party.personal_identifier or permission.guardian
                    and not permission.guardian.personal_identifier):
                raise UserError(gettext(
                        'party_personal_data_permission.party_no_vat'))

            context = Transaction().context
            ip = context.get('_request', {}).get('remote_addr')

            pattern = {
                'user': user,
                'IP': ip,
                }
            device_name = DeviceConfig.get_device(pattern=pattern)
            if not device_name:
                raise UserError(gettext(
                    'party_personal_data_permission.no_device_assigned',
                        user=user.rec_name,
                        ip=ip))

            helper.set_device_name(device_name)

            data['id'] = permission.id
            # Render report and get bytes stream
            data = PersonalDataPermissionReport.render(action_report, data,
                data['model'], [permission.id])

            # Pos X, Pos Y, Size X, Size Y in mm
            pos = (125, 160, 56, 20)
            if permission.guardian:
                pos = (125, 205, 56, 20)

                uploader = permission.guardian
                uploader_name = permission.guardian.name

            else:
                uploader = permission.party
                uploader_name = permission.party.name

            doc_gui = helper.upload_document(data, '%s_pdf' % (uploader_name),
                uploader, pos)

            to_write.extend(([permission], {
                        'doc_gui': doc_gui
                        }))
        if to_write:
            cls.write(*to_write)

    @classmethod
    @ModelView.button
    def collect(cls, permissions):
        """
        Check the status of the document in VidSigner. If signed, get the
        PDF document and move to signed state. If rejected move to
        rejected state. Otherwise keep current state.
        """
        pool = Pool()
        Attachment = pool.get('ir.attachment')
        User = pool.get('res.user')
        DeviceConfig = pool.get('party.permission.device.configuration')

        documents_to_write = []
        permissions_to_sign = []

        user = User(Transaction().user)

        context = Transaction().context
        ip = context.get('_request', {}).get('remote_addr')

        for permission in permissions:
            helper = VidCloudHelper()
            # Edge case when the user closes the view before the patient
            # has signed the pdf

            helper.doc_gui = permission.doc_gui

            if helper.device_name is None:
                pattern = {
                    'user': user,
                    'IP': ip,
                    }
                device_name = DeviceConfig.get_device(pattern)
                if not device_name:
                    raise UserError(gettext(
                        'party_personal_data_permission.no_device_assigned',
                        user=user.rec_name,
                        ip=ip))
                helper.set_device_name(device_name)

            status_result = helper.get_document_status()

            if not status_result[0]:
                # Not signed yet
                if status_result[1] == 409:
                    continue
                else:
                    raise UserError(gettext(
                            'party_personal_data_permission.get_error',
                            error=status_result[1]))

            if status_result[1]['DocStatus'] == 'Rejected':
                cls.reject([permission])

            elif status_result[1]['DocStatus'] == 'Signed':
                result = helper.get_signed_pdf()

                res = helper.delete_document(signed=True)
                if not res:
                    raise UserError(gettext(
                            'party_personal_data_permission.error_delete'))

                # Store the base64 signed PDF
                res = result[2]

                attach = Attachment()
                attach.name = 'signed.pdf'
                attach.type = 'data'
                attach.data = base64.decodestring(res['DocContent'].encode('ascii'))
                attach.resource = str(permission)
                attach, = Attachment.create([attach._save_values])
                documents_to_write.extend(([permission], {
                            'document': attach.id
                            }))
                permissions_to_sign.append(permission)

        if documents_to_write:
            cls.write(*documents_to_write)
        if permissions_to_sign:
            cls.sign(permissions_to_sign)

    @classmethod
    @ModelView.button
    @Workflow.transition('signed')
    def sign(cls, permissions):
        pool = Pool()
        Attachment = pool.get('ir.attachment')

        to_write = []

        for permission in permissions:
            file_path, file_name = permission.to_jpg(permission.document)

            with open(file_path, 'rb') as f:
                buffer_data = f.read()

            attach = Attachment(
                name='signed.jpg',
                type='data',
                data=buffer_data,
                resource=str(permission))
            attach.save()
            # Remove tmp file of the image
            os.remove(file_path)

            to_write.extend(([permission], {
                    'document_image_attach': attach.id
                    }))
        if to_write:
            cls.write(*to_write)

    @classmethod
    @ModelView.button
    @Workflow.transition('rejected')
    def reject(cls, permissions):
        pass

    @classmethod
    @ModelView.button
    @Workflow.transition('revoked')
    def revoke(cls, permissions):
        Date = Pool().get('ir.date')
        today = Date.today()

        cls.write(permissions, {
                'revocation_date': today
                })


class PersonalDataPermissionReport(JasperReport):
    __name__ = 'party.personal_data.permission.report'


class DeviceConfiguration(ModelView, ModelSQL, MatchMixin):
    'Party Permission Device Configuration'
    __name__ = 'party.permission.device.configuration'

    IP = fields.Char('IP')
    user = fields.Many2One('res.user', 'User')
    device_name = fields.Selection('get_devices', 'Device name', required=True)

    @classmethod
    def get_devices(cls):
        vid_cloud = VidCloudHelper()
        devices = vid_cloud.get_devices()
        res = []
        for device in devices:
            res.append((device['DeviceName'], device['DeviceDescription']))
        return res

    @classmethod
    def get_device(cls, pattern=None):
        records = cls.search([])

        pattern['user'] = pattern['user'].id
        for record in records:
            if record.match(pattern):
                return record.device_name

    def match(self, pattern):
        # If we don't set this the matching will always fail
        # since '' is not considered None
        if self.IP == '':
            self.IP = None

        if self.IP and pattern.get('IP') and self.IP in pattern.get('IP'):
            return True
        return super().match(pattern)
