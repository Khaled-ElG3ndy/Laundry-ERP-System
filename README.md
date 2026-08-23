# Farha Laundry Project

Odoo 17 deployment snapshot for Farha Laundry.

Included:
- `odoo/`: Odoo 17 source tree used by the deployment
- `custom_addons/`: project-specific and third-party addons
- `scripts/`: maintenance scripts
- `backups/`: verified full backup of the `farha_laundry` database and Odoo filestore

The current full backup is stored at:

`backups/farha_laundry_20260823_221459/`

Restore notes are inside that folder in `README_RESTORE.md`. The restore script is:

```bash
sudo bash backups/farha_laundry_20260823_221459/restore_farha_laundry.sh
```

The backup was verified with SHA-256 checksums, `pg_restore -l`, and a full zstd stream test for the filestore archive parts.
