# -*- coding: utf-8 -*-
import logging
import threading
import time

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

TAG_SIZE_SELECTION = [
    ('2.13', '2.13"'),
    ('2.66', '2.66"'),
    ('2.9',  '2.9"'),
    ('4.2',  '4.2"'),
    ('7.5',  '7.5"'),
]


class SunluxEslReassignWizard(models.TransientModel):
    _name = 'sunlux.esl.reassign.wizard'
    _description = 'SUNLUX ESL Tag Reassignment Wizard'

    product_id = fields.Many2one(
        'product.template', string='Product', required=True, readonly=True,
    )
    requested_size = fields.Selection(
        selection=TAG_SIZE_SELECTION,
        string='Preferred Tag Size',
    )

    has_conflict = fields.Boolean(default=False)
    conflict_summary = fields.Text(string='Conflict Details', readonly=True)
    tag_to_reassign_id = fields.Many2one(
        'sunlux.esl.tag', string='Tag to Reassign', readonly=True,
    )
    current_owner_id = fields.Many2one(
        'product.template', string='Current Owner', readonly=True,
    )

    @api.onchange('requested_size')
    def _onchange_requested_size(self):
        self.has_conflict = False
        self.conflict_summary = ''
        self.tag_to_reassign_id = False
        self.current_owner_id = False

        size = self.requested_size
        if not size:
            return

        Tag = self.env['sunlux.esl.tag']
        product_id = self.product_id.id or False
        total = Tag.search_count([('tag_size', '=', size)])

        if total == 0:
            return {
                'warning': {
                    'title': _('No Tags Available'),
                    'message': _(
                        'There are no %s" tags in the system yet.\n'
                        'Run "Fetch Tags" from the ESL Tag list first.',
                        size,
                    ),
                }
            }

        free_tags = Tag.search([
            ('tag_size', '=', size),
            '|',
            ('product_id', '=', False),
            ('product_id', '=', product_id),
        ], limit=1)
        if free_tags:
            return

        taken_tags = Tag.search([
            ('tag_size', '=', size),
            ('product_id', '!=', False),
            ('product_id', '!=', product_id),
        ])
        best_tag = Tag.search([
            ('tag_size', '=', size),
            ('product_id', '!=', False),
            ('product_id', '!=', product_id),
            ('template_id', '!=', False),
            ('station_id', '!=', False),
        ], order='status asc, id asc', limit=1) or Tag.search([
            ('tag_size', '=', size),
            ('product_id', '!=', False),
            ('product_id', '!=', product_id),
        ], order='status asc, id asc', limit=1)

        lines = [
            f'All {total} tag(s) of size {size}" are currently assigned to:',
        ]
        for t in taken_tags:
            lines.append(f'  \u2022 Tag {t.tag_code}  \u2192  {t.product_id.name}')
        lines += [
            '',
            'Clicking "Yes, Reassign" will:',
            f'  1. Release tag {best_tag.tag_code if best_tag else "?"}'
            f' from {best_tag.product_id.name if best_tag else "?"}',
            f'  2. Bind it to {self.product_id.name}',
            '  3. Re-sync both products to SUNLUX automatically',
            '',
            'The displaced product keeps its SUNLUX goods record',
            'but will have NO physical tag until one becomes free.',
        ]

        self.has_conflict = True
        self.conflict_summary = '\n'.join(lines)
        self.tag_to_reassign_id = best_tag.id if best_tag else False
        self.current_owner_id = best_tag.product_id.id if best_tag and best_tag.product_id else False

    def action_assign(self):
        self.ensure_one()
        product = self.product_id
        size = self.requested_size
        if not product or not size:
            return {'type': 'ir.actions.act_window_close'}

        self.env.cr.execute(
            "SELECT sunlux_tag_id FROM product_template WHERE id = %s", (product.id,)
        )
        row = self.env.cr.fetchone()
        current_tag_id = row[0] if row else None

        if current_tag_id:
            current_tag = self.env['sunlux.esl.tag'].browse(current_tag_id)
            if current_tag.tag_size != size:
                self.env.cr.execute(
                    "UPDATE sunlux_esl_tag SET product_id = NULL WHERE id = %s",
                    (current_tag_id,)
                )

        self.env.cr.execute(
            "UPDATE product_template SET "
            "sunlux_preferred_tag_size = %s, "
            "sunlux_goods_id = NULL, "
            "sunlux_tag_id = NULL "
            "WHERE id = %s",
            (size, product.id)
        )

        product_ids = [product.id]
        self.env['bus.bus']._sendone(
            self.env.user.partner_id,
            'simple_notification',
            {
                'title': _("Tag Size Updated"),
                'message': _("Tag size set to %s\" for %s. Syncing...", size, product.name),
                'type': 'info',
                'sticky': False,
            },
        )

        def _start_sync():
            time.sleep(4)
            threading.Thread(
                target=product._sync_to_esl_background,
                args=(product_ids,),
                daemon=True,
            ).start()

        self.env.cr.postcommit.add(_start_sync)
        return {'type': 'ir.actions.act_window_close'}

    def action_confirm_reassign(self):
        self.ensure_one()
        product = self.product_id
        size = self.requested_size

        if not product or not size:
            return {'type': 'ir.actions.act_window_close'}

        Tag = self.env['sunlux.esl.tag']
        tag = Tag.search([
            ('tag_size', '=', size),
            ('product_id', '!=', False),
            ('product_id', '!=', product.id),
            ('template_id', '!=', False),
            ('station_id', '!=', False),
        ], order='status asc, id asc', limit=1) or Tag.search([
            ('tag_size', '=', size),
            ('product_id', '!=', False),
            ('product_id', '!=', product.id),
        ], order='status asc, id asc', limit=1)

        old_owner = tag.product_id if tag else False
        if old_owner:
            self.env.cr.execute(
                "UPDATE product_template SET sunlux_tag_id = NULL WHERE id = %s",
                (old_owner.id,)
            )
        if tag:
            self.env.cr.execute(
                "UPDATE sunlux_esl_tag SET product_id = NULL WHERE id = %s",
                (tag.id,)
            )

        if product.sunlux_tag_id and product.sunlux_tag_id != tag:
            self.env.cr.execute(
                "UPDATE sunlux_esl_tag SET product_id = NULL WHERE id = %s",
                (product.sunlux_tag_id.id,)
            )

        self.env.cr.execute(
            "UPDATE product_template SET "
            "sunlux_preferred_tag_size = %s, "
            "sunlux_goods_id = NULL, "
            "sunlux_tag_id = NULL "
            "WHERE id = %s",
            (size, product.id)
        )

        self.env['bus.bus']._sendone(
            self.env.user.partner_id,
            'simple_notification',
            {
                'title': _("ESL Tag Reassigned"),
                'message': _("Tag reassigned to %s. Syncing...", product.name),
                'type': 'info',
                'sticky': False,
            },
        )

        product_ids = [product.id]

        def _start_sync():
            time.sleep(4)
            threading.Thread(
                target=product._sync_to_esl_background,
                args=(product_ids,),
                daemon=True,
            ).start()

        self.env.cr.postcommit.add(_start_sync)

        if old_owner and old_owner.sunlux_esl_sync_enabled:
            old_ids = [old_owner.id]

            def _start_old_sync():
                time.sleep(2)
                threading.Thread(
                    target=old_owner._sync_to_esl_background,
                    args=(old_ids,),
                    daemon=True,
                ).start()

            self.env.cr.postcommit.add(_start_old_sync)

        return {'type': 'ir.actions.act_window_close'}

    def action_cancel(self):
        return {'type': 'ir.actions.act_window_close'}
