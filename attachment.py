from trytond.pool import PoolMeta
from trytond.config import config
from trytond.transaction import Transaction
from trytond.model import fields

import os


__all__ = ['Attachment']


class Attachment(metaclass=PoolMeta):
    __name__ = 'ir.attachment'

    file_path = fields.Function(fields.Char('File path'), 'get_path')

    def get_path(self, name=None):
        db_name = Transaction().database.name
        filename = self.file_id
        filename = os.path.join(config.get('database', 'path'), db_name,
                    filename[0:2], filename[2:4], filename)
        return filename
