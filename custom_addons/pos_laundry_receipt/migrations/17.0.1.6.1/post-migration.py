from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    # Existing historical orders keep their deadline as a snapshot.  Only old
    # linked laundry orders that never had an SLA deadline get one calculated
    # from their current branch/company calendar during this explicit upgrade.
    env["pos.order"].search(
        [
            ("x_laundry_intake_id", "!=", False),
            ("x_laundry_sla_deadline", "=", False),
        ]
    )._ensure_laundry_sla_deadline_snapshot()

    # Worker attribution is the authenticated user who performed the delivered
    # transition, not the creator/cashier/default user.  Repair data populated
    # by the earlier default-field implementation.
    cr.execute(
        """
        UPDATE pos_order po
           SET x_laundry_worker_id = delivered_history.changed_by_id
          FROM (
                SELECT DISTINCT ON (order_id)
                       order_id,
                       changed_by_id
                  FROM pos_order_laundry_status_history
                 WHERE new_status = 'delivered'
                   AND changed_by_id IS NOT NULL
                 ORDER BY order_id, changed_on DESC, id DESC
               ) AS delivered_history
         WHERE po.id = delivered_history.order_id
           AND po.x_laundry_status = 'delivered'
        """
    )
    cr.execute(
        """
        UPDATE pos_order
           SET x_laundry_worker_id = NULL
         WHERE COALESCE(x_laundry_status, '') != 'delivered'
        """
    )
