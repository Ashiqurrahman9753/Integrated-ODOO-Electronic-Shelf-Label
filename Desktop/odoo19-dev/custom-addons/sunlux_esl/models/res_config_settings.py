# -*- coding: utf-8 -*-
from odoo import fields, models, _


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    sunlux_base_url = fields.Char(
        string='SUNLUX API Base URL',
        config_parameter='sunlux_esl.base_url',
    )
    sunlux_uid = fields.Char(
        string='Merchant UID',
        config_parameter='sunlux_esl.uid',
    )
    sunlux_sid = fields.Char(
        string='Platform SID',
        config_parameter='sunlux_esl.sid',
    )
    sunlux_key = fields.Char(
        string='Secret Key',
        config_parameter='sunlux_esl.key',
    )

    sunlux_token_preview = fields.Char(
        string='Cached Token', compute='_compute_sunlux_token_status',
    )
    sunlux_token_expires = fields.Char(
        string='Token Expires', compute='_compute_sunlux_token_status',
    )

    def _compute_sunlux_token_status(self):
        ICP = self.env['ir.config_parameter'].sudo()
        token = ICP.get_param('sunlux_esl.token', '')
        expire_str = ICP.get_param('sunlux_esl.token_expire', '')
        for rec in self:
            rec.sunlux_token_preview = (
                token[:20] + '...' if len(token) > 20 else token or 'No token'
            )
            rec.sunlux_token_expires = expire_str or 'N/A'

    def action_sunlux_test_connection(self):
        try:
            token = self.env['sunlux.esl.api']._get_token(force_refresh=True)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Connection Successful"),
                    'message': _("Authenticated. Token: %s...", token[:20]),
                    'type': 'success',
                    'sticky': False,
                },
            }
        except Exception as exc:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Connection Failed"),
                    'message': str(exc),
                    'type': 'danger',
                    'sticky': True,
                },
            }

    def action_sunlux_clear_token(self):
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('sunlux_esl.token', '')
        ICP.set_param('sunlux_esl.token_expire', '')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Token Cleared"),
                'message': _("A new token will be requested on the next sync."),
                'type': 'info',
                'sticky': False,
            },
        }

    def action_sunlux_fetch_tags(self):
        return self.env['sunlux.esl.tag'].action_fetch_tags_from_sunlux()
