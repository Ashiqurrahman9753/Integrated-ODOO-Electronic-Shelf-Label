# -*- coding: utf-8 -*-
import logging
import threading
import time

import psycopg2
import psycopg2.errors

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


def _generate_ean13():
    base = str(int(time.time() * 1000))[-11:]
    digits = base.zfill(12)[:12]
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits))
    check = (10 - (total % 10)) % 10
    return digits + str(check)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    sunlux_esl_sync_enabled = fields.Boolean(string='Sync to ESL', default=False)
    sunlux_original_price = fields.Float(
        string='Original Price (ESL)', digits='Product Price', default=0,
        help='Set above list price to show a strikethrough discount on the tag.',
    )
    sunlux_goods_id = fields.Char(string='SUNLUX Goods ID', readonly=True, copy=False)
    sunlux_last_sync = fields.Datetime(string='Last ESL Sync', readonly=True, copy=False)
    sunlux_preferred_tag_size = fields.Selection(
        selection=[('2.13', '2.13"'), ('2.66', '2.66"'), ('2.9', '2.9"'),
                   ('4.2', '4.2"'), ('7.5', '7.5"')],
        string='Preferred Tag Size',
    )
    sunlux_tag_id = fields.Many2one(
        'sunlux.esl.tag', string='Bound ESL Tag',
        ondelete='set null', copy=False, readonly=True,
    )
    sunlux_tag_status = fields.Selection(
        selection=[
            ('bound', 'Tag Bound'),
            ('waiting', 'Waiting for Tag'),
            ('not_synced', 'Not Synced'),
        ],
        string='ESL Tag Status',
        compute='_compute_sunlux_tag_status',
        store=False,
    )

    @api.depends('sunlux_esl_sync_enabled', 'sunlux_goods_id', 'sunlux_tag_id', 'sunlux_preferred_tag_size')
    def _compute_sunlux_tag_status(self):
        for product in self:
            if not product.sunlux_esl_sync_enabled:
                product.sunlux_tag_status = 'not_synced'
            elif product.sunlux_tag_id:
                product.sunlux_tag_status = 'bound'
            elif product.sunlux_goods_id and product.sunlux_preferred_tag_size:
                product.sunlux_tag_status = 'waiting'
            else:
                product.sunlux_tag_status = 'not_synced'

    def action_open_reassign_wizard(self):
        self.ensure_one()
        wizard = self.env['sunlux.esl.reassign.wizard'].create({
            'product_id': self.id,
            'requested_size': self.sunlux_preferred_tag_size or False,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Change Tag Size'),
            'res_model': 'sunlux.esl.reassign.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
            'views': [(False, 'form')],
        }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('barcode'):
                vals['barcode'] = _generate_ean13()
        return super().create(vals_list)

    def write(self, vals):
        if 'sunlux_preferred_tag_size' in vals:
            new_size = vals['sunlux_preferred_tag_size']
            for product in self.filtered('sunlux_tag_id'):
                old_tag = product.sunlux_tag_id
                if old_tag and old_tag.tag_size != new_size:
                    self.env.cr.execute(
                        "UPDATE sunlux_esl_tag SET product_id = NULL WHERE id = %s",
                        (old_tag.id,)
                    )
                    self.env.cr.execute(
                        "UPDATE product_template SET sunlux_tag_id = NULL WHERE id = %s",
                        (product.id,)
                    )
                    _logger.info(
                        "SUNLUX ESL: released tag %s from '%s' — size changed %s → %s",
                        old_tag.tag_code, product.name, old_tag.tag_size, new_size,
                    )
            vals['sunlux_goods_id'] = False
            vals['sunlux_tag_id'] = False

        if 'barcode' in vals:
            for product in self.filtered('sunlux_tag_id'):
                self.env.cr.execute(
                    "UPDATE sunlux_esl_tag SET product_id = NULL WHERE id = %s",
                    (product.sunlux_tag_id.id,)
                )
            vals['sunlux_goods_id'] = False
            vals['sunlux_tag_id'] = False

        result = super().write(vals)

        esl_internal = {'sunlux_goods_id', 'sunlux_last_sync', 'sunlux_tag_id'}
        if not (set(vals) - esl_internal):
            return result

        products = self.filtered('sunlux_esl_sync_enabled')
        if products:
            product_ids = products.ids
            product_names = ', '.join(p.name for p in products)
            _logger.info(
                "SUNLUX ESL: auto-sync triggered for %d product(s) — changed: %s",
                len(products), ', '.join(set(vals) - esl_internal),
            )
            self.env['bus.bus']._sendone(
                self.env.user.partner_id,
                'simple_notification',
                {
                    'title': _("ESL Auto-Sync"),
                    'message': _("Syncing %s to ESL...", product_names),
                    'type': 'info',
                    'sticky': False,
                },
            )

            def _start_sync():
                time.sleep(4)
                threading.Thread(
                    target=self._sync_to_esl_background,
                    args=(product_ids,),
                    daemon=True,
                ).start()

            self.env.cr.postcommit.add(_start_sync)

        return result

    def _sync_to_esl_background(self, product_ids):
        for attempt in range(4):
            try:
                with self.pool.cursor() as cr:
                    cr.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                    env = api.Environment(cr, self.env.uid, self.env.context)
                    products = env['product.template'].browse(product_ids).exists()
                    if products:
                        products._do_esl_sync(env)
                    cr.commit()
                return
            except (
                psycopg2.errors.LockNotAvailable,
                psycopg2.errors.DeadlockDetected,
                psycopg2.errors.SerializationFailure,
            ) as e:
                _logger.warning(
                    "SUNLUX ESL: concurrency error on attempt %d (%s), retrying...",
                    attempt + 1, type(e).__name__,
                )
                time.sleep(5)
            except Exception:
                _logger.exception("SUNLUX ESL: background sync failed")
                return

    def _do_esl_sync(self, env):
        api_client = env['sunlux.esl.api']

        env.cr.execute(
            "SELECT id, sunlux_goods_id FROM product_template WHERE id = ANY(%s)",
            (list(self.ids),)
        )
        goods_id_map = {r[0]: r[1] for r in env.cr.fetchall()}

        new_products = self.filtered(lambda p: not goods_id_map.get(p.id))
        existing_products = self.filtered(lambda p: goods_id_map.get(p.id))
        for p in existing_products:
            p.sunlux_goods_id = goods_id_map[p.id]

        if new_products:
            payload = [new_products._prepare_full_sync_data(p) for p in new_products]
            result = api_client.sync_products_full(
                payload,
                product_ids=new_products.ids,
                product_names=[p.name for p in new_products],
            )
            success_map = {
                item['barCode']: item['goodsId']
                for item in result.get('suc', [])
                if item.get('barCode') and item.get('goodsId')
            }
            for item in result.get('msg', []):
                tip = item.get('tip') or ''
                code = item.get('code') or ''
                if 'WRITE TO DB' in tip or 'INVALID_KEY' in code:
                    row_idx = item.get('row', 'ROW_1')
                    try:
                        idx = int(row_idx.replace('ROW_', '')) - 1
                        bc = payload[idx].get('barCode') if idx < len(payload) else None
                    except Exception:
                        bc = None
                    if bc and bc not in success_map:
                        recovered = api_client._fetch_goods_id_by_barcode(bc)
                        if recovered:
                            success_map[bc] = recovered
                            _logger.info("SUNLUX ESL: recovered goodsId %s for barcode %s", recovered, bc)
                        else:
                            _logger.warning("SUNLUX ESL: could not recover goodsId for barcode %s", bc)

            for barcode, goods_id in success_map.items():
                matched = new_products.filtered(lambda p, bc=barcode: p.barcode == bc)
                if matched:
                    env.cr.execute(
                        "UPDATE product_template SET sunlux_goods_id = %s, "
                        "sunlux_last_sync = NOW() AT TIME ZONE 'UTC' WHERE id = ANY(%s)",
                        (goods_id, list(matched.ids))
                    )
                    for product in matched:
                        if product.sunlux_preferred_tag_size:
                            product._auto_bind_tag(env, goods_id)

        if existing_products:
            payload = []
            for p in existing_products:
                original = p.sunlux_original_price or 0
                has_discount = original and original > p.list_price
                retail = original if has_discount else p.list_price
                sale = p.list_price
                payload.append({
                    'barCode': p.barcode or '',
                    'retailPrice': retail,
                    'memberPrice': sale,
                    'salePrice': sale,
                })
            result = api_client.sync_prices(
                payload,
                product_ids=existing_products.ids,
                product_names=[p.name for p in existing_products],
            )
            for item in result.get('suc', []):
                barcode = item.get('barCode')
                if barcode:
                    matched = existing_products.filtered(lambda p, bc=barcode: p.barcode == bc)
                    if matched:
                        env.cr.execute(
                            "UPDATE product_template SET sunlux_last_sync = NOW() AT TIME ZONE 'UTC' "
                            "WHERE id = ANY(%s)",
                            (list(matched.ids),)
                        )
                        for product in matched:
                            if product.sunlux_preferred_tag_size and not product.sunlux_tag_id:
                                product._auto_bind_tag(env, product.sunlux_goods_id)

        internal_users = env['res.users'].search([('share', '=', False)])
        for user in internal_users:
            env['bus.bus']._sendone(user.partner_id, 'sunlux_esl_refresh', {})

    def _auto_bind_tag(self, env, goods_id):
        size = self.sunlux_preferred_tag_size
        if not size or not goods_id:
            return

        env.cr.execute(
            "SELECT t.id FROM sunlux_esl_tag t WHERE t.product_id = %s AND t.tag_size = %s LIMIT 1",
            (self.id, size)
        )
        if env.cr.fetchone():
            return

        env.cr.execute(
            "SELECT id, tag_id, tag_code, template_id, station_id, status "
            "FROM sunlux_esl_tag "
            "WHERE tag_size = %s AND product_id IS NULL "
            "AND template_id IS NOT NULL AND template_id != '' "
            "AND station_id IS NOT NULL AND station_id != '' "
            "ORDER BY status ASC, id ASC "
            "LIMIT 1 FOR UPDATE SKIP LOCKED",
            (size,)
        )
        row = env.cr.fetchone()

        if not row:
            env.cr.execute("SELECT COUNT(*) FROM sunlux_esl_tag WHERE tag_size = %s", (size,))
            total = env.cr.fetchone()[0]
            if total == 0:
                _logger.warning(
                    "SUNLUX ESL: no %s tags in system for '%s' — run Fetch Tags first.",
                    size, self.name,
                )
            else:
                _logger.warning(
                    "SUNLUX ESL: all %d tag(s) of size %s occupied — cannot bind '%s'.",
                    total, size, self.name,
                )
            return

        tag_db_id, tag_id, tag_code, template_id, station_id, status = row
        success = env['sunlux.esl.api'].bind_tag(
            tag_id=tag_id, template_id=template_id,
            station_id=station_id, goods_id=goods_id,
        )
        if success:
            env.cr.execute(
                "UPDATE sunlux_esl_tag SET product_id = %s, "
                "current_goods_id = %s, current_goods_name = %s WHERE id = %s",
                (self.id, goods_id, self.name, tag_db_id)
            )
            env.cr.execute(
                "UPDATE product_template SET sunlux_tag_id = %s WHERE id = %s",
                (tag_db_id, self.id)
            )
            _logger.info(
                "SUNLUX ESL: bound tag %s (%s) to '%s'", tag_code, size, self.name,
            )
        else:
            _logger.error(
                "SUNLUX ESL: bind API failed for tag %s / '%s'", tag_code, self.name,
            )

    @staticmethod
    def _prepare_full_sync_data(product):
        original = product.sunlux_original_price or 0
        has_discount = original and original > product.list_price
        retail_price = original if has_discount else product.list_price
        sale_price = product.list_price

        return {
            'goodsName': product.name or '',
            'barCode': product.barcode or '',
            'retailPrice': retail_price,
            'memberPrice': sale_price,
            'salePrice': sale_price,
            'salesUnit': product.uom_id.name if product.uom_id else 'Unit',
            'sku': product.default_code or '',
            'itemNo': product.default_code or '',
            'category': product.categ_id.name if product.categ_id else '',
            'stock': int(product.qty_available) if hasattr(product, 'qty_available') else 0,
            'qrcodeUrl': '',
            'goodsPhoto': '',
            'specif': '',
            'grade': '',
            'origin': '',
            'model': '',
            'promotionBegin': '',
            'promotionEnd': '',
            'productionDate': '',
            'warehouse': '',
            'freightSpace': '',
            'shelfLife': '',
            'mode': '',
            'supplier': '',
            'department': '',
            'extendParams': '',
        }

    def action_sunlux_sync_now(self):
        self.ensure_one()
        if not self.sunlux_esl_sync_enabled:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("ESL Sync Disabled"),
                    'message': _('Enable "Sync to ESL" on this product first.'),
                    'type': 'warning',
                    'sticky': False,
                },
            }
        threading.Thread(
            target=self._sync_to_esl_background, args=(self.ids,), daemon=True,
        ).start()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("ESL Sync Started"),
                'message': _("Background sync started. Check logs for results."),
                'type': 'info',
                'sticky': False,
            },
        }

    def action_sunlux_generate_barcodes(self):
        products_without = self.filtered(lambda p: not p.barcode)
        if not products_without:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("No Action Needed"),
                    'message': _("All selected products already have barcodes."),
                    'type': 'info',
                    'sticky': False,
                },
            }
        for product in products_without:
            product.barcode = _generate_ean13()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Barcodes Generated"),
                'message': _("%d product(s) assigned new EAN-13 barcodes.", len(products_without)),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_sunlux_bulk_sync(self):
        products = self.filtered('sunlux_esl_sync_enabled')
        if not products:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("No Products"),
                    'message': _('None of the selected products have "Sync to ESL" enabled.'),
                    'type': 'warning',
                    'sticky': False,
                },
            }
        threading.Thread(
            target=self._sync_to_esl_background, args=(products.ids,), daemon=True,
        ).start()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Bulk Sync Started"),
                'message': _("%d product(s) queued for ESL sync.", len(products)),
                'type': 'success',
                'sticky': False,
            },
        }
