# -*- coding: utf-8 -*-
import hashlib
import json
import logging
import time

import requests
from datetime import datetime, timedelta

from odoo import api, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Timeouts in seconds
AUTH_TIMEOUT = 15
DATA_TIMEOUT = 30


class SunluxEslApi(models.AbstractModel):
    """API client for SUNLUX ESL REST API v1.4."""

    _name = 'sunlux.esl.api'
    _description = 'SUNLUX ESL API Client'

    # -------------------------------------------------------------------------
    # Configuration helpers
    # -------------------------------------------------------------------------

    def _get_api_config(self):
        """Retrieve API credentials from ir.config_parameter."""
        ICP = self.env['ir.config_parameter'].sudo()
        return {
            'base_url': (ICP.get_param('sunlux_esl.base_url', '') or '').rstrip('/'),
            'uid': ICP.get_param('sunlux_esl.uid', ''),
            'sid': ICP.get_param('sunlux_esl.sid', ''),
            'key': ICP.get_param('sunlux_esl.key', ''),
        }

    # -------------------------------------------------------------------------
    # Authentication
    # -------------------------------------------------------------------------

    @staticmethod
    def _generate_sign(sid, key, uid, timestamp):
        """MD5 signature: sid={sid}&key={key}&uid={uid}&timestamp={ts}."""
        raw = f"sid={sid}&key={key}&uid={uid}&timestamp={timestamp}"
        return hashlib.md5(raw.encode('utf-8')).hexdigest()

    def _get_cached_token(self):
        """Return cached (token, expire_dt) or (None, None) if expired."""
        ICP = self.env['ir.config_parameter'].sudo()
        token = ICP.get_param('sunlux_esl.token', '')
        expire_str = ICP.get_param('sunlux_esl.token_expire', '')
        if not token or not expire_str:
            return None, None
        try:
            expire_dt = datetime.fromisoformat(expire_str)
            if datetime.now() >= expire_dt - timedelta(minutes=5):
                return None, None
            return token, expire_dt
        except (ValueError, TypeError):
            return None, None

    def _cache_token(self, token, expire_minutes=1440):
        """Store token + expiry in ir.config_parameter."""
        ICP = self.env['ir.config_parameter'].sudo()
        expire_dt = datetime.now() + timedelta(minutes=expire_minutes)
        ICP.set_param('sunlux_esl.token', token)
        ICP.set_param('sunlux_esl.token_expire', expire_dt.isoformat())

    def _get_token(self, force_refresh=False):
        """Get a valid Bearer token (from cache or fresh request)."""
        if not force_refresh:
            cached, _ = self._get_cached_token()
            if cached:
                return cached

        config = self._get_api_config()
        if not all([config['base_url'], config['uid'], config['sid'], config['key']]):
            raise UserError(_(
                "SUNLUX ESL API credentials not configured.\n"
                "Go to Settings > Point of Sale > SUNLUX ESL Configuration."
            ))

        timestamp = int(time.time() * 1000)
        sign = self._generate_sign(
            config['sid'], config['key'], config['uid'], timestamp,
        )

        endpoint = f"{config['base_url']}/epts-api/v2/sys/api/tToken"
        payload = {
            'uid': config['uid'],
            'sid': config['sid'],
            'timestamp': timestamp,
            'sign': sign,
        }

        start = time.time()
        try:
            resp = requests.post(endpoint, json=payload, timeout=AUTH_TIMEOUT)
            duration_ms = int((time.time() - start) * 1000)
            resp.raise_for_status()
            result = resp.json()

            self.env['sunlux.esl.log'].log_api_call(
                operation='get_token',
                endpoint=endpoint,
                request_data=payload,
                response_code=resp.status_code,
                response_data=result,
                duration_ms=duration_ms,
            )

            if result.get('code') != 200:
                raise UserError(
                    _("SUNLUX auth failed: %s", result.get('msg', 'Unknown'))
                )

            token_data = result.get('data', {})
            token = token_data.get('token')
            if not token:
                raise UserError(_("SUNLUX: No token in response"))

            self._cache_token(token, token_data.get('expire', 1440))
            return token

        except requests.exceptions.Timeout:
            self._log_error('get_token', endpoint, payload, 'Request timed out')
            raise UserError(_("SUNLUX ESL: Auth request timed out"))
        except requests.exceptions.RequestException as exc:
            self._log_error('get_token', endpoint, payload, str(exc))
            raise UserError(_("SUNLUX ESL: Connection error — %s", exc))

    # -------------------------------------------------------------------------
    # Data endpoints
    # -------------------------------------------------------------------------

    def sync_products_full(self, products_data, product_ids=None, product_names=None):
        """POST /goods/goods/batch/edit?light=0 — full product sync."""
        return self._post_data(
            operation='sync_product',
            path='/epts-api/goods/goods/batch/edit?light=0',
            payload=products_data,
            product_ids=product_ids,
            product_names=product_names,
        )

    def sync_prices(self, price_data, product_ids=None, product_names=None):
        """POST /goods/goods/batchPrice — price-only sync."""
        return self._post_data(
            operation='sync_price',
            path='/epts-api/goods/goods/batchPrice',
            payload=price_data,
            product_ids=product_ids,
            product_names=product_names,
        )

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _post_data(self, operation, path, payload, product_ids=None, product_names=None):
        """Generic authenticated POST with logging."""
        config = self._get_api_config()
        token = self._get_token()
        endpoint = f"{config['base_url']}{path}"
        headers = {'Authorization': f'Bearer {token}'}

        # Build product info string for logging
        log_product_id = product_ids[0] if product_ids and len(product_ids) == 1 else None
        log_product_name = ', '.join(product_names) if product_names else ''

        start = time.time()
        try:
            resp = requests.post(
                endpoint, json=payload, headers=headers, timeout=DATA_TIMEOUT,
            )
            duration_ms = int((time.time() - start) * 1000)
            resp.raise_for_status()
            result = resp.json()

            self.env['sunlux.esl.log'].log_api_call(
                operation=operation,
                endpoint=endpoint,
                request_data=payload,
                response_code=resp.status_code,
                response_data=result,
                duration_ms=duration_ms,
                product_id=log_product_id,
                product_name=log_product_name,
            )

            if result.get('code') != 200:
                _logger.error("SUNLUX %s failed: %s", operation, result.get('msg'))
            return result.get('data', {})

        except requests.exceptions.Timeout:
            self._log_error(operation, endpoint, payload, 'Request timed out')
            return {'suc': [], 'msg': ['Request timed out']}
        except requests.exceptions.RequestException as exc:
            self._log_error(operation, endpoint, payload, str(exc))
            return {'suc': [], 'msg': [str(exc)]}

    def _log_error(self, operation, endpoint, payload, message):
        """Shortcut to log a failed API call."""
        _logger.error("SUNLUX ESL %s error: %s", operation, message)
        self.env['sunlux.esl.log'].log_api_call(
            operation=operation,
            endpoint=endpoint,
            request_data=payload,
            response_code=None,
            response_data=None,
            error_message=message,
        )
