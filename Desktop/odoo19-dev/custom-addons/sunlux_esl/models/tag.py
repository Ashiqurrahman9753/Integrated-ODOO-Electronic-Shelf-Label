# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Map human-readable size label → SUNLUX resolutionDesc substring
TAG_SIZE_LABELS = [
    ('2.13', '2.13"'),
    ('2.66', '2.66"'),
    ('2.9',  '2.9"'),
    ('4.2',  '4.2"'),
    ('7.5',  '7.5"'),
    ('other', 'Other'),
]


class SunluxEslTag(models.Model):
    _name = 'sunlux.esl.tag'
    _description = 'SUNLUX ESL Price Tag'
    _order = 'tag_code'
    _rec_name = 'tag_code'

    tag_id = fields.Char(string='SUNLUX Tag ID', required=True, index=True, copy=False)
    tag_code = fields.Char(string='Tag Code', required=True, copy=False)
    station_id = fields.Char(
        string='Base Station ID', copy=False,
    )
    station_name = fields.Char(
        string='Base Station', copy=False,
    )
    template_id = fields.Char(
        string='Template ID', copy=False,
    )
    template_name = fields.Char(
        string='Template', copy=False,
    )
    resolution_id = fields.Char(
        string='Resolution ID', copy=False,
    )
    resolution_desc = fields.Char(
        string='Screen Size', copy=False,
    )
    tag_size = fields.Selection(
        selection=TAG_SIZE_LABELS,
        string='Tag Size',
        compute='_compute_tag_size',
        store=True,
    )
    status = fields.Selection(
        selection=[('0', 'Online'), ('1', 'Offline')],
        string='Status',
    )
    bind_mode = fields.Char(string='Bind Mode')
    current_goods_id = fields.Char(string='Bound SUNLUX Goods ID', copy=False)
    current_goods_name = fields.Char(string='Bound Product', copy=False)
    product_id = fields.Many2one(
        'product.template', string='Odoo Product', ondelete='set null', copy=False,
    )
    last_sync = fields.Datetime(
        string='Last Synced from SUNLUX', readonly=True,
    )

    @api.depends('resolution_desc')
    def _compute_tag_size(self):
        for rec in self:
            desc = rec.resolution_desc or ''
            if '2.13' in desc:
                rec.tag_size = '2.13'
            elif '2.66' in desc:
                rec.tag_size = '2.66'
            elif '2.9' in desc:
                rec.tag_size = '2.9'
            elif '4.2' in desc:
                rec.tag_size = '4.2'
            elif '7.5' in desc:
                rec.tag_size = '7.5'
            else:
                rec.tag_size = 'other'

    def action_fetch_tags_from_sunlux(self):
        api = self.env['sunlux.esl.api']
        tags_data = api.fetch_price_tags()
        if tags_data is None:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Fetch Failed"),
                    'message': _("Could not retrieve tags from SUNLUX. Check logs."),
                    'type': 'danger',
                    'sticky': True,
                },
            }

        count = 0
        for item in tags_data:
            tag_id = item.get('tagId') or ''
            if not tag_id:
                continue
            existing = self.search([('tag_id', '=', tag_id)], limit=1)
            vals = {
                'tag_id': tag_id,
                'tag_code': item.get('tagCode') or '',
                'station_id': item.get('stationId') or '',
                'station_name': item.get('stationNum') or item.get('stationName') or '',
                'template_id': item.get('templateId') or '',
                'template_name': item.get('templateName') or '',
                'resolution_id': item.get('resolutionId') or '',
                'resolution_desc': item.get('resolutionDesc') or '',
                'status': str(item.get('status', '1')),
                'bind_mode': str(item.get('bindMode', '')),
                'current_goods_id': (item.get('goodsList') or [{}])[0].get('value') or '',
                'current_goods_name': item.get('goodsName') or '',
                'last_sync': fields.Datetime.now(),
            }
            if existing:
                existing.write(vals)
            else:
                self.create(vals)
            count += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Tags Synced"),
                'message': _("%d tag(s) fetched from SUNLUX.", count),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_bind_to_product(self):
        self.ensure_one()
        if not self.product_id:
            raise UserError(_("Set an Odoo Product on this tag record first."))
        product = self.product_id
        if not product.sunlux_goods_id:
            raise UserError(_(
                "Product '%s' has no SUNLUX Goods ID yet. "
                "Sync it to ESL first.", product.name
            ))
        if not self.template_id:
            raise UserError(_("This tag has no Template ID. Fetch tags again."))
        if not self.station_id:
            raise UserError(_("This tag has no Base Station ID. Fetch tags again."))

        api = self.env['sunlux.esl.api']
        result = api.bind_tag(
            tag_id=self.tag_id,
            template_id=self.template_id,
            station_id=self.station_id,
            goods_id=product.sunlux_goods_id,
        )
        if result:
            self.write({
                'current_goods_id': product.sunlux_goods_id,
                'current_goods_name': product.name,
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Tag Bound"),
                    'message': _("Tag %s bound to '%s'.", self.tag_code, product.name),
                    'type': 'success',
                    'sticky': False,
                },
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Bind Failed"),
                'message': _("SUNLUX returned an error. Check logs."),
                'type': 'danger',
                'sticky': True,
            },
        }
