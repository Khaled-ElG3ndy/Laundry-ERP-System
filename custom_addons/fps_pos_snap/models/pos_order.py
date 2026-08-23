from odoo import models, api, fields
import logging

_logger = logging.getLogger(__name__)


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    snap_tax_exempt = fields.Boolean(
        string="SNAP Tax Exempt",
        default=False,
        help="True if this line's tax was exempted due to EBT payment"
    )
    snap_tax_exempted_amount = fields.Float(
        string="Tax Exempted",
        default=0.0,
        help="Amount of tax exempted for this line"
    )


class PosOrder(models.Model):
    _inherit = "pos.order"

    snap_ebt_amount = fields.Float(
        string="EBT SNAP Amount",
        default=0.0,
        readonly=True,
        help="Amount paid with EBT SNAP"
    )
    snap_tax_exempted = fields.Float(
        string="SNAP Tax Exempted",
        default=0.0,
        readonly=True,
        help="Total tax exempted due to EBT payment"
    )

    @api.model
    def _process_order(self, order, draft, existing_order):
        """
        Override to handle SNAP tax exemption.
        When EBT is used, food items paid with EBT are tax exempt.
        """
        # First, let the parent create the order and handle invoice creation
        pos_order_id = super()._process_order(order, draft, existing_order)
        
        if not pos_order_id:
            return pos_order_id
        
        try:
            pos_order = self.browse(pos_order_id)
            self._apply_snap_tax_exemption(pos_order)
        except Exception as e:
            _logger.error(f"[SNAP TAX] Error applying tax exemption: {e}")
        
        return pos_order_id

    def _apply_snap_tax_exemption(self, order):
        """
        Apply SNAP tax exemption logic to the order.
        """
        # Calculate total EBT payment
        ebt_total = 0.0
        for payment in order.payment_ids:
            if payment.payment_method_id.is_snap_ebt:
                ebt_total += payment.amount
        
        if ebt_total <= 0:
            return  # No EBT payment, nothing to do
        
        _logger.info(f"[SNAP TAX] Order {order.name}: EBT payment ${ebt_total:.2f}")
        
        # Calculate SNAP eligible subtotal (price without tax)
        snap_subtotal = 0.0
        snap_lines = []
        
        for line in order.lines:
            if line.product_id.snap_eligible:
                snap_subtotal += line.price_subtotal
                snap_lines.append(line)
        
        if snap_subtotal <= 0:
            _logger.info(f"[SNAP TAX] No SNAP eligible items")
            return
        
        _logger.info(f"[SNAP TAX] SNAP eligible subtotal: ${snap_subtotal:.2f}")
        
        # Calculate how much EBT covers food (capped at food total)
        ebt_for_food = min(ebt_total, snap_subtotal)
        coverage_ratio = ebt_for_food / snap_subtotal
        
        _logger.info(f"[SNAP TAX] EBT covers {coverage_ratio*100:.1f}% of food")
        
        # Calculate tax to exempt
        total_tax_exempted = 0.0
        
        for line in snap_lines:
            # Tax on this line
            line_tax = line.price_subtotal_incl - line.price_subtotal
            # Tax to exempt (proportional to EBT coverage)
            tax_to_exempt = line_tax * coverage_ratio
            total_tax_exempted += tax_to_exempt
            
            # Update line
            line.write({
                'snap_tax_exempt': True,
                'snap_tax_exempted_amount': tax_to_exempt,
            })
        
        _logger.info(f"[SNAP TAX] Total tax exempted: ${total_tax_exempted:.2f}")
        
        if total_tax_exempted > 0:
            # Update order totals
            new_tax = order.amount_tax - total_tax_exempted
            new_total = order.amount_total - total_tax_exempted
            
            order.write({
                'snap_ebt_amount': ebt_total,
                'snap_tax_exempted': total_tax_exempted,
                'amount_tax': max(0, new_tax),
                'amount_total': new_total,
            })
            
            _logger.info(f"[SNAP TAX] Order updated: tax ${order.amount_tax:.2f}, total ${order.amount_total:.2f}")

    def _export_for_ui(self, order):
        """Add SNAP info to order export for receipts"""
        result = super()._export_for_ui(order)
        result['snap_ebt_amount'] = order.snap_ebt_amount
        result['snap_tax_exempted'] = order.snap_tax_exempted
        return result
