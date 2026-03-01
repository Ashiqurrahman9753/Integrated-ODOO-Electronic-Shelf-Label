# -*- coding: utf-8 -*-
import hashlib
import json
import logging
import time
from datetime import datetime, timedelta

import requests

from odoo import api, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

AUTH_TIMEOUT = 15
DATA_TIMEOUT = 30


class SunluxEslApi(models.AbstractModel):
    _name = 'sunlux.esl.api'
    _description = 'SUNLUX ESL API Client'

    def _get_api_config(self):
        ICP = self.env['ir.config_parameter'].sudo()
        return {
            'base_url': (ICP.get_param('sunlux_esl.base_url', '') or '').rstrip('/'),
            'uid': ICP.get_param('sunlux_esl.uid', ''),
            'sid': ICP.get_param('sunlux_esl.sid', ''),
            'key': ICP.get_param('sunlux_esl.key', ''),
        }

    @staticmethod
    def _generate_sign(sid, key, uid, timestamp):
        raw = f"sid={sid}&key={key}&uid={uid}&timestamp={timestamp}"
        return hashlib.md5(raw.encode('utf-8')).hexdigest()

    def _get_cached_token(self):
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
        ICP = self.env['ir.config_parameter'].sudo()
        expire_dt = datetime.now() + timedelta(minutes=expire_minutes)
        ICP.set_param('sunlux_esl.token', token)
        ICP.set_param('sunlux_esl.token_expire', expire_dt.isoformat())

    def _get_token(self, force_refresh=False):
        if not force_refresh:
            cached, _ = self._get_cached_token()
            if cached:
                return cached

        config = self._get_api_config()
        if not all([config['base_url'], config['uid'], config['sid'], config['key']]):
            raise UserError(_(
                "SUNLUX API credentials not configured. "
                "Go to Settings > Point of Sale > Tag Display."
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
                raise UserError(_("SUNLUX auth failed: %s", result.get('msg', 'Unknown')))

            token_data = result.get('data', {})
            token = token_data.get('token')
            if not token:
                raise UserError(_("SUNLUX: no token in response"))

            self._cache_token(token, token_data.get('expire', 1440))
            return token

        except requests.exceptions.Timeout:
            self._log_error('get_token', endpoint, payload, 'Request timed out')
            raise UserError(_("SUNLUX: auth request timed out"))
        except requests.exceptions.RequestException as exc:
            self._log_error('get_token', endpoint, payload, str(exc))
            raise UserError(_("SUNLUX: connection error — %s", exc))

    def sync_products_full(self, products_data, product_ids=None, product_names=None):
        return self._post_data(
            operation='sync_product',
            path='/epts-api/goods/goods/batch/edit?light=0',
            payload=products_data,
            product_ids=product_ids,
            product_names=product_names,
        )

    def sync_prices(self, price_data, product_ids=None, product_names=None):
        return self._post_data(
            operation='sync_price',
            path='/epts-api/goods/goods/batchPrice',
            payload=price_data,
            product_ids=product_ids,
            product_names=product_names,
        )

    def _fetch_goods_id_by_barcode(self, barcode):
        try:
            config = self._get_api_config()
            token = self._get_token()
            endpoint = f"{config['base_url']}/epts-api/goods/goods/list?barCode={barcode}&pageNum=1&pageSize=5"
            headers = {'Authorization': f'Bearer {token}'}
            resp = requests.get(endpoint, headers=headers, timeout=DATA_TIMEOUT)
            resp.raise_for_status()
            result = resp.json()
            if result.get('code') != 200:
                return None
            rows = result.get('rows') or result.get('data') or []
            for item in rows:
                if item.get('barCode') == barcode and item.get('goodsId'):
                    return item['goodsId']
        except Exception as exc:
            _logger.warning("SUNLUX ESL: _fetch_goods_id_by_barcode failed: %s", exc)
        return None

    def fetch_price_tags(self, page_size=200):
        config = self._get_api_config()
        token = self._get_token()
        headers = {'Authorization': f'Bearer {token}'}
        all_tags = []
        page = 1
        while True:
            endpoint = (
                f"{config['base_url']}/epts-api/priceTag/priceTag/list"
                f"?pageNum={page}&pageSize={page_size}"
            )
            start = time.time()
            try:
                resp = requests.get(endpoint, headers=headers, timeout=DATA_TIMEOUT)
                duration_ms = int((time.time() - start) * 1000)
                resp.raise_for_status()
                result = resp.json()
                self.env['sunlux.esl.log'].log_api_call(
                    operation='fetch_tags',
                    endpoint=endpoint,
                    request_data={'page': page, 'pageSize': page_size},
                    response_code=resp.status_code,
                    response_data=result,
                    duration_ms=duration_ms,
                )
                if result.get('code') != 200:
                    _logger.error("SUNLUX fetch_tags failed: %s", result.get('msg'))
                    return None
                batch = result.get('rows') or result.get('data') or []
                all_tags.extend(batch)
                if len(batch) < page_size:
                    break
                page += 1
            except requests.exceptions.RequestException as exc:
                self._log_error('fetch_tags', endpoint, {}, str(exc))
                return None
        return all_tags

    def bind_tag(self, tag_id, template_id, station_id, goods_id):
        config = self._get_api_config()
        token = self._get_token()
        endpoint = f"{config['base_url']}/epts-api/priceTag/priceTag/bound"
        headers = {'Authorization': f'Bearer {token}'}
        payload = {
            'tagId': tag_id,
            'templateId': template_id,
            'stationId': station_id,
            'goodsList': [{'label': 'a', 'value': goods_id}],
        }
        start = time.time()
        try:
            resp = requests.put(
                endpoint, json=payload, headers=headers, timeout=DATA_TIMEOUT,
            )
            duration_ms = int((time.time() - start) * 1000)
            resp.raise_for_status()
            result = resp.json()
            self.env['sunlux.esl.log'].log_api_call(
                operation='bind_tag',
                endpoint=endpoint,
                request_data=payload,
                response_code=resp.status_code,
                response_data=result,
                duration_ms=duration_ms,
            )
            if result.get('code') != 200:
                _logger.error("SUNLUX bind_tag failed: %s", result.get('msg'))
                return False
            return True
        except requests.exceptions.RequestException as exc:
            self._log_error('bind_tag', endpoint, payload, str(exc))
            return False

    def _post_data(self, operation, path, payload, product_ids=None, product_names=None):
        config = self._get_api_config()
        token = self._get_token()
        endpoint = f"{config['base_url']}{path}"
        headers = {'Authorization': f'Bearer {token}'}
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
        _logger.error("SUNLUX ESL %s error: %s", operation, message)
        self.env['sunlux.esl.log'].log_api_call(
            operation=operation,
            endpoint=endpoint,
            request_data=payload,
            response_code=None,
            response_data=None,
            error_message=message,
        )
