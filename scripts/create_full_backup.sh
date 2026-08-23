#!/usr/bin/env bash
set -euo pipefail

DB_NAME="${DB_NAME:-farha_laundry}"
ODOO_SERVICE="${ODOO_SERVICE:-odoo17-farha.service}"
DATA_DIR="${DATA_DIR:-/opt/odoo17/farha-data/.local/share/Odoo}"
FILESTORE_DIR="${FILESTORE_DIR:-$DATA_DIR/filestore/$DB_NAME}"
BACKUP_ROOT="${BACKUP_ROOT:-/opt/odoo17/backups}"
SPLIT_SIZE="${SPLIT_SIZE:-90M}"
TIMESTAMP="${TIMESTAMP:-$(date -u +%Y%m%d_%H%M%S)}"
BACKUP_DIR="$BACKUP_ROOT/${DB_NAME}_${TIMESTAMP}"
PG_TMP_DIR=""

restore_service() {
    if [[ "${SERVICE_WAS_ACTIVE:-no}" == "yes" ]]; then
        systemctl start "$ODOO_SERVICE"
    fi
    if [[ -n "${PG_TMP_DIR:-}" && -d "$PG_TMP_DIR" ]]; then
        rm -rf "$PG_TMP_DIR"
    fi
}

require_path() {
    local path="$1"
    local label="$2"
    if [[ ! -e "$path" ]]; then
        echo "Missing $label: $path" >&2
        exit 1
    fi
}

split_if_needed() {
    local file="$1"
    local marker="$file.parts"
    if [[ ! -s "$file" ]]; then
        echo "Expected non-empty file: $file" >&2
        exit 1
    fi

    if [[ "$(stat -c%s "$file")" -gt $((95 * 1024 * 1024)) ]]; then
        split -b "$SPLIT_SIZE" -d -a 3 "$file" "$file.part-"
        sha256sum "$file" > "$marker"
        rm -f "$file"
    fi
}

require_path "$FILESTORE_DIR" "filestore"
mkdir -p "$BACKUP_DIR/database" "$BACKUP_DIR/filestore" "$BACKUP_DIR/config"
PG_TMP_DIR="$(mktemp -d "/var/tmp/${DB_NAME}_pg_dump.XXXXXX")"
chown postgres:postgres "$PG_TMP_DIR"

SERVICE_WAS_ACTIVE="no"
if systemctl is-active --quiet "$ODOO_SERVICE"; then
    SERVICE_WAS_ACTIVE="yes"
fi
trap restore_service EXIT

if [[ "$SERVICE_WAS_ACTIVE" == "yes" ]]; then
    systemctl stop "$ODOO_SERVICE"
fi

runuser -u postgres -- pg_dump -Fc -Z 9 -f "$PG_TMP_DIR/${DB_NAME}.dump" "$DB_NAME"
mv "$PG_TMP_DIR/${DB_NAME}.dump" "$BACKUP_DIR/database/${DB_NAME}.dump"
chown "$(id -u):$(id -g)" "$BACKUP_DIR/database/${DB_NAME}.dump"
tar --numeric-owner --xattrs --acls -C "$DATA_DIR/filestore" -I 'zstd -19 -T0' -cf "$BACKUP_DIR/filestore/${DB_NAME}_filestore.tar.zst" "$DB_NAME"

if [[ -f /etc/odoo17-farha.conf ]]; then
    sed -E \
        -e 's/^(admin_passwd[[:space:]]*=[[:space:]]*).*/\11234/' \
        -e 's/^(db_password[[:space:]]*=[[:space:]]*).*/\11234/' \
        /etc/odoo17-farha.conf > "$BACKUP_DIR/config/odoo17-farha.conf.example"
fi

split_if_needed "$BACKUP_DIR/database/${DB_NAME}.dump"
split_if_needed "$BACKUP_DIR/filestore/${DB_NAME}_filestore.tar.zst"

cat > "$BACKUP_DIR/restore_farha_laundry.sh" <<'RESTORE'
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
RESTORE
chmod +x "$BACKUP_DIR/restore_farha_laundry.sh"

cat > "$BACKUP_DIR/README_RESTORE.md" <<EOF
# Farha Laundry Backup

Created: $TIMESTAMP UTC
Database: $DB_NAME
Odoo service: $ODOO_SERVICE
Filestore: $FILESTORE_DIR

This backup contains:
- PostgreSQL custom-format dump in \`database/\`
- Odoo filestore archive in \`filestore/\`
- Sanitized config example in \`config/\` with passwords set to \`1234\`
- \`restore_farha_laundry.sh\` for full restore on the same server layout

Restore:

\`\`\`bash
sudo bash restore_farha_laundry.sh
\`\`\`

The script stops Odoo, recreates the database, restores the dump, restores the filestore, fixes ownership, and starts Odoo again.
EOF

{
    echo "backup_dir=$BACKUP_DIR"
    echo "created_utc=$TIMESTAMP"
    echo "database=$DB_NAME"
    echo "odoo_service=$ODOO_SERVICE"
    echo "data_dir=$DATA_DIR"
    echo "filestore_dir=$FILESTORE_DIR"
    echo "split_size=$SPLIT_SIZE"
    echo "postgres_version=$(runuser -u postgres -- psql -Atc 'SHOW server_version;')"
    echo "odoo_version=$(/opt/odoo17/venv/bin/python /opt/odoo17/odoo/odoo-bin --version 2>/dev/null || true)"
} > "$BACKUP_DIR/MANIFEST.txt"

find "$BACKUP_DIR" -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > "$BACKUP_DIR/SHA256SUMS"

echo "$BACKUP_DIR"
