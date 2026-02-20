# -*- coding: utf-8 -*-
import logging
import threading

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    sunlux_esl_sync_enabled = fields.Boolean(
        string='Sync to ESL', default=False,
        help='Automatically sync this product to SUNLUX Electronic Shelf Labels',
    )
    sunlux_original_price = fields.Float(
        string='Original Price (ESL)', digits='Product Price', default=0,
        help='Set this to the original/retail price to show a discount on ESL tags. '
             'Leave at 0 to use the selling price as both retail and sale price.',
    )
    sunlux_goods_id = fields.Char(
        string='SUNLUX Goods ID', readonly=True, copy=False,
        help='Internal ID assigned by SUNLUX after first successful sync',
    )
    sunlux_last_sync = fields.Datetime(
        string='Last ESL Sync', readonly=True, copy=False,
    )

    # ------------------------------------------------------------------
    # Write override — triggers background ESL sync
    # ------------------------------------------------------------------

    def write(self, vals):
        result = super().write(vals)

        # Skip sync for our own internal field updates (avoid infinite loop)
        esl_internal_fields = {'sunlux_goods_id', 'sunlux_last_sync'}
        changed_fields = set(vals) - esl_internal_fields
        if not changed_fields:
            return result

        # When auto-sync is ON, sync on ANY save (not just specific fields)
        products = self.filtered('sunlux_esl_sync_enabled')
        if products:
            product_ids = products.ids
            product_names = ', '.join(p.name for p in products)
            _logger.info(
                "SUNLUX ESL: auto-sync triggered for %d product(s) — changed: %s",
                len(products), ', '.join(changed_fields),
            )

            # Notify user that auto-sync is happening
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

            # Start sync AFTER the current transaction commits
            # (prevents concurrent update errors)
            def _start_sync():
                import time as _time
                _time.sleep(1)  # small debounce
                thread = threading.Thread(
                    target=self._sync_to_esl_background,
                    args=(product_ids,),
                    daemon=True,
                )
                thread.start()

            self.env.cr.postcommit.add(_start_sync)

        return result

    # ------------------------------------------------------------------
    # Background sync (runs in its own DB cursor)
    # ------------------------------------------------------------------

    def _sync_to_esl_background(self, product_ids):
        """Thread entry-point — opens a fresh cursor and runs sync."""
        try:
            with self.pool.cursor() as cr:
                env = api.Environment(cr, self.env.uid, self.env.context)
                products = env['product.template'].browse(product_ids).exists()
                if products:
                    products._do_esl_sync(env)
                cr.commit()
        except Exception:
            _logger.exception("SUNLUX ESL: background sync failed")

    def _do_esl_sync(self, env):
        """Decide full-sync vs price-sync and call the API."""
        api_client = env['sunlux.esl.api']

        new_products = self.filtered(lambda p: not p.sunlux_goods_id)
        existing_products = self.filtered(lambda p: p.sunlux_goods_id)

        # --- Full sync for products without a SUNLUX goodsId ----
        if new_products:
            payload = [
                new_products._prepare_full_sync_data(p) for p in new_products
            ]
            result = api_client.sync_products_full(
                payload,
                product_ids=new_products.ids,
                product_names=[p.name for p in new_products],
            )
            for item in result.get('suc', []):
                barcode = item.get('barCode')
                goods_id = item.get('goodsId')
                if barcode and goods_id:
                    matched = new_products.filtered(
                        lambda p, bc=barcode: p.barcode == bc
                    )
                    if matched:
                        matched.write({
                            'sunlux_goods_id': goods_id,
                            'sunlux_last_sync': fields.Datetime.now(),
                        })

        # --- Price-only sync for already-synced products ---------
        if existing_products:
            payload = []
            for p in existing_products:
                original = p.sunlux_original_price or 0
                has_discount = original and original > p.list_price
                retail = original if has_discount else p.list_price
                sale = p.list_price
                payload.append({
                    'goodsId': p.sunlux_goods_id,
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
                goods_id = item.get('goodsId')
                if goods_id:
                    matched = existing_products.filtered(
                        lambda p, gid=goods_id: p.sunlux_goods_id == gid
                    )
                    if matched:
                        matched.write({'sunlux_last_sync': fields.Datetime.now()})

    # ------------------------------------------------------------------
    # Field mapping helper
    # ------------------------------------------------------------------

    @staticmethod
    def _prepare_full_sync_data(product):
        """Map an Odoo product to the SUNLUX full-sync payload.

        Price logic:
        - If sunlux_original_price is set and higher than list_price,
          retailPrice = original price, salePrice = list_price (discounted).
        - Otherwise, retailPrice = salePrice = list_price.
        """
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

    # ------------------------------------------------------------------
    # Manual UI actions
    # ------------------------------------------------------------------

    def action_sunlux_sync_now(self):
        """Button on product form — sync this single product."""
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

        thread = threading.Thread(
            target=self._sync_to_esl_background,
            args=(self.ids,),
            daemon=True,
        )
        thread.start()

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

    def action_sunlux_bulk_sync(self):
        """Server action from list view — sync selected products."""
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

        thread = threading.Thread(
            target=self._sync_to_esl_background,
            args=(products.ids,),
            daemon=True,
        )
        thread.start()

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
