# -*- coding: utf-8 -*-
import json
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class SunluxEslLog(models.Model):
    _name = 'sunlux.esl.log'
    _description = 'SUNLUX ESL API Log'
    _order = 'create_date desc'
    _rec_name = 'operation'

    operation = fields.Selection([
        ('get_token', 'Get Token'),
        ('refresh_token', 'Refresh Token'),
        ('sync_product', 'Sync Product'),
        ('sync_price', 'Sync Price'),
        ('delete_product', 'Delete Product'),
        ('bulk_sync', 'Bulk Sync'),
    ], string='Operation', required=True, index=True)

    product_id = fields.Many2one(
        'product.template', string='Product', ondelete='set null',
    )
    product_name = fields.Char(string='Product Name')

    endpoint = fields.Char(string='API Endpoint')
    request_data = fields.Text(string='Request Data')
    response_code = fields.Integer(string='HTTP Status Code')
    response_data = fields.Text(string='Response Data')

    status = fields.Selection([
        ('success', 'Success'),
        ('warning', 'Warning'),
        ('error', 'Error'),
    ], string='Status', required=True, default='success', index=True)

    error_message = fields.Text(string='Error Message')
    duration_ms = fields.Integer(string='Duration (ms)')

    @api.model
    def log_api_call(self, operation, endpoint, request_data, response_code,
                     response_data, product_id=None, product_name=None,
                     error_message=None, duration_ms=None):
        """Create a log entry for an API call."""
        if error_message:
            status = 'error'
        elif response_code and 200 <= response_code < 300:
            status = 'success'
        else:
            status = 'error'

        # Use provided product_name, or look up from product_id,
        # or extract from request payload
        if not product_name and product_id:
            product = self.env['product.template'].browse(product_id)
            if product.exists():
                product_name = product.name
        if not product_name and request_data:
            # Extract goodsName from sync payload
            raw = request_data
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    raw = None
            if isinstance(raw, list):
                names = [
                    item.get('goodsName', '')
                    for item in raw
                    if isinstance(item, dict) and item.get('goodsName')
                ]
                if names:
                    product_name = ', '.join(names)

        if isinstance(request_data, (dict, list)):
            request_data = json.dumps(request_data, indent=2, default=str)
        if isinstance(response_data, (dict, list)):
            response_data = json.dumps(response_data, indent=2, default=str)

        return self.create({
            'operation': operation,
            'product_id': product_id,
            'product_name': product_name or '',
            'endpoint': endpoint,
            'request_data': request_data,
            'response_code': response_code,
            'response_data': response_data,
            'status': status,
            'error_message': error_message,
            'duration_ms': duration_ms,
        })
