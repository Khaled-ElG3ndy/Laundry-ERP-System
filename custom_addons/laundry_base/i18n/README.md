# Translations — الترجمة

Screen labels live in English in the source and in `ar_001.po` / `ar.po` here,
so every user reads the laundry in their own language instead of reading both
at once.

**Printed documents are deliberately not in here.** The receipt, the label, the
Z report and the hotel manifest stay bilingual in their templates: a customer
reads them, not the cashier who printed them.

Records that carry two stored names — branches, item categories, service types,
stages, add-ons — are shown through `models/laundry_naming.py`, which picks
`name_ar` for an Arabic user and `name` for an English one.

After changing a label:

```bash
# export what changed
odoo-bin -c <conf> -d <db> --i18n-export=laundry_base.pot \
         --modules=laundry_base --stop-after-init
# fill the Arabic in ar_001.po and ar.po, then reload
odoo-bin -c <conf> -d <db> -u laundry_base --i18n-overwrite --stop-after-init
```
