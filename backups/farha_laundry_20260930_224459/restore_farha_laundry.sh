#!/usr/bin/env bash
set -euo pipefail

DB_NAME="${DB_NAME:-farha_laundry}"
ODOO_SERVICE="${ODOO_SERVICE:-odoo17-farha.service}"
DATA_DIR="${DATA_DIR:-/opt/odoo17/farha-data/.local/share/Odoo}"
BACKUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="$(mktemp -d)"

cleanup() {
    rm -rf "$WORK_DIR"
}
trap cleanup EXIT

reassemble() {
    local base="$1"
    local output="$2"
    if compgen -G "$base.part-*" > /dev/null; then
        cat "$base".part-* > "$output"
    elif [[ -f "$base" ]]; then
        cp "$base" "$output"
    else
        echo "Missing backup file or parts for $base" >&2
        exit 1
    fi
}

if [[ "$(id -u)" -ne 0 ]]; then
    echo "Run as root." >&2
    exit 1
fi

systemctl stop "$ODOO_SERVICE" || true

reassemble "$BACKUP_DIR/database/${DB_NAME}.dump" "$WORK_DIR/${DB_NAME}.dump"
reassemble "$BACKUP_DIR/filestore/${DB_NAME}_filestore.tar.zst" "$WORK_DIR/${DB_NAME}_filestore.tar.zst"

runuser -u postgres -- dropdb --if-exists "$DB_NAME"
runuser -u postgres -- createdb -O odoo17 "$DB_NAME"
runuser -u postgres -- pg_restore --no-owner --role=odoo17 -d "$DB_NAME" "$WORK_DIR/${DB_NAME}.dump"

mkdir -p "$DATA_DIR/filestore"
rm -rf "$DATA_DIR/filestore/$DB_NAME"
tar --numeric-owner --xattrs --acls -C "$DATA_DIR/filestore" -I zstd -xf "$WORK_DIR/${DB_NAME}_filestore.tar.zst"
chown -R odoo17:odoo17 "$DATA_DIR/filestore/$DB_NAME"

systemctl start "$ODOO_SERVICE"
echo "Restore completed for $DB_NAME."
