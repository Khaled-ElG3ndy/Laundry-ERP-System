#!/usr/bin/env bash
#
# Deploy pos_laundry_variant_popup to the live Farha Laundry Odoo 17 instance.
#
# The script is deliberately conservative: it takes a database dump it can roll
# back to, syncs the reviewed addon, upgrades the module, and restarts the
# service. Every step is fatal on error, and the rollback command is printed
# before anything is touched.
#
# Usage:  sudo scripts/deploy_laundry_addons.sh
#         sudo DRY_RUN=1 scripts/deploy_laundry_addons.sh   # show, do not act
#
set -euo pipefail

# Both modules take part in this feature: the popup itself, and the watchdog in
# pos_laundry_receipt that gets an already open till onto the new build. They
# are upgraded in one stop so the tills only see a single restart.
MODULES="${MODULES:-pos_laundry_receipt pos_laundry_variant_popup}"
DB_NAME="${DB_NAME:-farha_laundry}"
SERVICE="${SERVICE:-odoo17-farha.service}"
ODOO_USER="${ODOO_USER:-odoo17}"
# Use the very binary the service runs, so the deploy exercises the production path.
ODOO_BIN="${ODOO_BIN:-/opt/odoo17/venv/bin/python /opt/odoo17/odoo/odoo-bin}"
ODOO_CONF="${ODOO_CONF:-/etc/odoo17-farha.conf}"
SOURCE_ROOT="${SOURCE_ROOT:-/opt/Farha-Laundry-Project/custom_addons}"
TARGET_ROOT="${TARGET_ROOT:-/opt/odoo17/custom_addons}"
# Not under /opt/odoo17: that tree is 0750 odoo17, which the postgres role that
# runs pg_dump cannot even traverse.
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/farha-deploy}"
REBUILD_SCRIPT="${REBUILD_SCRIPT:-/opt/Farha-Laundry-Project/scripts/rebuild_pos_assets.py}"
DRY_RUN="${DRY_RUN:-0}"
STAMP="$(date -u +%Y%m%d_%H%M%S)"
DUMP_FILE="$BACKUP_ROOT/${DB_NAME}_predeploy_${STAMP}.dump"
ADDON_BACKUP="$BACKUP_ROOT/addons_predeploy_${STAMP}.tar.gz"

log()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
run()  { if [[ "$DRY_RUN" == "1" ]]; then printf '   [dry-run] %s\n' "$*"; else eval "$@"; fi; }

[[ $EUID -eq 0 ]] || { echo "Run as root (sudo)." >&2; exit 1; }
for module in $MODULES; do
    [[ -d "$SOURCE_ROOT/$module" ]] || {
        echo "Missing source: $SOURCE_ROOT/$module" >&2; exit 1; }
done

log "Pre-flight"
echo "    modules      : $MODULES"
echo "    database     : $DB_NAME"
echo "    service      : $SERVICE"
echo "    source       : $SOURCE_ROOT"
echo "    target       : $TARGET_ROOT"
echo "    dry run      : $DRY_RUN"

log "1/7 Backing up the database and the current addon"
run "mkdir -p '$BACKUP_ROOT'"
# pg_dump runs as the postgres role, so it needs to be able to write here.
run "chown postgres:postgres '$BACKUP_ROOT'"
run "chmod 750 '$BACKUP_ROOT'"
run "sudo -u postgres pg_dump -Fc -d '$DB_NAME' -f '$DUMP_FILE'"
run "test -s '$DUMP_FILE'"
run "tar -czf '$ADDON_BACKUP' -C '$TARGET_ROOT' $MODULES"
echo
echo "    Roll back with:"
echo "      systemctl stop $SERVICE"
echo "      sudo -u postgres dropdb $DB_NAME && sudo -u postgres createdb -O $ODOO_USER $DB_NAME"
echo "      sudo -u postgres pg_restore -d $DB_NAME '$DUMP_FILE'"
echo "      tar -xzf '$ADDON_BACKUP' -C '$TARGET_ROOT'"
echo "      systemctl start $SERVICE"

log "2/7 Stopping $SERVICE"
run "systemctl stop '$SERVICE'"

log "3/7 Syncing the addon source"
for module in $MODULES; do
    run "rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' \
          '$SOURCE_ROOT/$module/' '$TARGET_ROOT/$module/'"
    run "chown -R $ODOO_USER:$ODOO_USER '$TARGET_ROOT/$module'"
done

log "4/7 Upgrading $MODULES"
run "sudo -u $ODOO_USER $ODOO_BIN -c '$ODOO_CONF' -d '$DB_NAME' -u '${MODULES// /,}' \
      --no-http --workers=0 --max-cron-threads=0 --stop-after-init --log-level=warn"

log "5/7 Starting $SERVICE"
run "systemctl start '$SERVICE'"
run "systemctl is-active '$SERVICE'"

log "6/7 Rebuilding the POS asset bundles"
# This is what tells the tills that are already open to reload. Doing it here,
# with the cashiers reconnected, is deterministic; leaving it to whoever opens
# the POS next is not.
run "sudo -u $ODOO_USER $ODOO_BIN shell -c '$ODOO_CONF' -d '$DB_NAME' \
      --no-http --workers=0 --max-cron-threads=0 --log-level=warn \
      < '$REBUILD_SCRIPT'"

log "7/7 Post-deploy check"
if [[ "$DRY_RUN" != "1" ]]; then
    sudo -u postgres psql -d "$DB_NAME" -tAc "
      select 'module      : ' || name || ' ' || state || ' ' || latest_version
        from ir_module_module where name in ('${MODULES// /\',\'}')
      union all
      select 'addon lines : ' || count(*)::text
        from product_template_attribute_line l
        join product_attribute a on a.id = l.attribute_id
       where a.laundry_addon_code is not null
      union all
      select 'stain prices: ' || string_agg(v.name->>'en_US' || '=' || ptav.price_extra::text, ', ' order by v.sequence)
        from product_template_attribute_value ptav
        join product_attribute_value v on v.id = ptav.product_attribute_value_id
        join product_attribute a on a.id = ptav.attribute_id
       where a.laundry_addon_code = 'stain_removal'
         and ptav.product_tmpl_id = (
             select min(product_tmpl_id) from product_template_attribute_value x
             join product_attribute y on y.id = x.attribute_id
             where y.laundry_addon_code = 'stain_removal')"
fi

log "Done. Open POS tabs are told to reload once the cashier is idle."
