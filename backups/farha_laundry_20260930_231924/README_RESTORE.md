# Farha Laundry Backup

Created: 20260930_231924 UTC
Database: farha_laundry
Odoo service: odoo17-farha.service
Filestore: /opt/odoo17/farha-data/.local/share/Odoo/filestore/farha_laundry

This backup contains:
- PostgreSQL custom-format dump in `database/`
- Odoo filestore archive in `filestore/`
- Sanitized config example in `config/` with passwords set to `1234`
- `restore_farha_laundry.sh` for full restore on the same server layout

Restore:

```bash
sudo bash restore_farha_laundry.sh
```

The script stops Odoo, recreates the database, restores the dump, restores the filestore, fixes ownership, and starts Odoo again.
