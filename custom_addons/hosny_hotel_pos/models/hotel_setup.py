# -*- coding: utf-8 -*-
"""Setting up hotel contract pricing, and importing the agreed price sheet.

Two separate jobs, deliberately kept apart:

``sync_structure()`` makes sure the scaffolding exists -- categories,
pricelists, products, customers, the POS and its payment methods. It runs on
install and on every ``-u hosny_hotel_pos``, and it **never writes a price**.
It also never rewrites a record that already exists, so a product renamed in
the backend stays renamed.

``import_prices()`` is the only thing that touches money, and it only runs when
somebody asks for it through the import wizard. Prices therefore live in the
database as ordinary pricelist rules that staff can edit, rather than being
overwritten from the spreadsheet behind their backs on every upgrade.

Nothing is matched by name at runtime -- products key on ``default_code``,
pricelists on ``hotel_tier``, the POS on ``is_hotel_pos``, and partners on
explicit reviewed ids -- so repeat runs update in place and never duplicate.
"""

import logging

from odoo import api, models
from odoo.exceptions import UserError

from ..data import price_book

_logger = logging.getLogger(__name__)

# --- Pricelists -------------------------------------------------------------

TIER_NAMES = {
    'base': ('أسعار الفنادق - الأساسية', 'Hotel Contract - Base'),
    'fann': ('أسعار الفنادق - فنن سويت', 'Hotel Contract - Fann Suites'),
    'naseem': ('أسعار الفنادق - النسمة الهادئ', 'Hotel Contract - Al Nasma Al Hadi'),
    'lulua': ('أسعار الفنادق - لؤلؤة الحمدانية', 'Hotel Contract - Lulua Al Hamdaniya'),
}
CONTRACT_TIERS = tuple(TIER_NAMES)

# The POS needs a default pricelist, and it must not be a contract tier: a
# customer who is not configured would otherwise be charged real agreed prices
# by accident. This one carries no rules, so an unconfigured order prices at the
# products' own 0.00 -- obviously wrong on screen rather than plausibly wrong,
# and the till refuses to take payment for it anyway.
NO_CONTRACT_TIER = 'none'
NO_CONTRACT_NAMES = ('بدون عقد - يجب اختيار العميل',
                     'No Contract - Select a Customer')

# Created by an earlier revision that put hotel pricing on the retail POS. That
# approach is gone -- hotels get their own POS now -- so the pricelist is
# archived rather than deleted, in case anything was pointed at it by hand.
RETIRED_RETAIL_TIER = 'retail'

# Inside the hotel POS every product is a hotel product, so a single "فنادق"
# filter grouped nothing and left the cashier scrolling one flat list of 36.
# These are the real groups, kept flat and top-level like the retail POS's own
# categories so the filter bar is one tap deep.
HOTEL_POS_CATEGORIES = [
    ('bed', 'مفروشات السرير', 'Bed Linen', 10),
    ('bath', 'مناشف وروب', 'Towels & Robes', 20),
    ('rugs', 'سجاد ودواسات', 'Rugs & Mats', 30),
    ('table', 'مفروشات الطاولات', 'Table Linen', 40),
    ('curtains', 'ستائر', 'Curtains', 50),
    ('clothing', 'ملابس', 'Clothing', 60),
]

# Which group each catalogue product belongs in.
HOTEL_PRODUCT_GROUPS = {
    'HTL-01': 'bed', 'HTL-02': 'bed', 'HTL-03': 'bed', 'HTL-04': 'bed',
    'HTL-05': 'bed', 'HTL-06': 'bed', 'HTL-07': 'bed', 'HTL-08': 'bed',
    'HTL-09': 'bed', 'HTL-10': 'bed', 'HTL-11': 'bed',
    'HTL-17': 'bed', 'HTL-18': 'bed',
    'HTL-12': 'bath', 'HTL-13': 'bath', 'HTL-14': 'bath', 'HTL-16': 'bath',
    'HTL-15': 'rugs', 'HTL-35': 'rugs',
    'HTL-19': 'table', 'HTL-20': 'table', 'HTL-21': 'table',
    'HTL-22': 'table', 'HTL-23': 'table', 'HTL-24': 'table',
    'HTL-32': 'curtains', 'HTL-33': 'curtains', 'HTL-34': 'curtains',
    'HTL-25': 'clothing', 'HTL-26': 'clothing', 'HTL-27': 'clothing',
    'HTL-28': 'clothing', 'HTL-29': 'clothing', 'HTL-30': 'clothing',
    'HTL-31': 'clothing', 'HTL-36': 'clothing',
}

# The original catch-all. pos.category has no ``active`` field and cannot be
# deleted while any session is open, so it is left in the database and simply
# no longer offered by either POS.
LEGACY_HOTEL_POS_CATEGORY = ('فنادق', 'Hotels')
HOTEL_POS_NAMES = ('مبيعات الفنادق والشركات', 'Hotel & Company Sales')

# The hotel till needs a cash drawer that is counted independently of retail's.
# That means its own journal, which Odoo backs with its own freshly created
# liquidity account -- so the two registers never share a balance. The journal
# code is the natural key the sync matches on (codes are unique per company).
HOTEL_CASH_JOURNAL_CODE = 'CSHH'
HOTEL_CASH_JOURNAL_NAMES = ('نقدية الفنادق والشركات', 'Hotel & Company Cash')
HOTEL_CASH_METHOD_NAMES = ('نقدي - الفنادق والشركات', 'Cash (Hotel & Company)')
HOTEL_PRODUCT_CATEGORY = 'فنادق'
PARENT_PRODUCT_CATEGORY = 'Laundry Services'

# --- Customers --------------------------------------------------------------
# Reviewed mapping from each price-sheet customer to real partner records.
# ``partner_ids`` are the ids confirmed during the import review; ``expect``
# is the partner name as it read at that moment. The sync refuses to touch a
# partner whose name no longer matches, so an id reused by a different record
# can never be silently mispriced.
#
# ``create`` entries have no acceptable existing partner and are created once,
# then found again on later runs via ``hotel_excel_name``.
CUSTOMER_MAP = [
    # -- base tier -----------------------------------------------------------
    {
        'tier': 'base',
        'sheet_name': 'مجموعة ابداع الخليج العقارية ( كوخ 1)',
        'display_name': 'مجموعة ابداع الخليج العقارية (كوخ 1)',
        # Only one generic "الكوخ" record exists; taken as unit 1 per review.
        'partners': [(8726, 'مجموعة ابداع الخليخ العقارية الكوخ')],
    },
    {
        'tier': 'base',
        'sheet_name': 'مجموعة ابداع الخليج العقارية (كوخ 2)',
        'display_name': 'مجموعة ابداع الخليج العقارية (كوخ 2)',
    },
    {
        'tier': 'base',
        'sheet_name': 'مجموعة ابداع الخليج العقارية( كوخ 4)',
        'display_name': 'مجموعة ابداع الخليج العقارية (كوخ 4)',
    },
    {
        'tier': 'base',
        'sheet_name': 'مجموعة ابداع الخليج العقارية (طيبة)',
        'display_name': 'مجموعة ابداع الخليج العقارية (طيبة)',
        # Differs from the sheet only in ة/ه.
        'partners': [(8652, 'مجموعة ابداع الخليج العقارية (طيبه)')],
    },
    {
        'tier': 'base',
        'sheet_name': 'شقق السمحة',
        'display_name': 'شقق السمحة',
        # Duplicate pair 8720/9872; the ref-coded record wins.
        'partners': [(8720, 'شقق السمحة')],
    },
    {
        'tier': 'base',
        'sheet_name': 'شقق اجنحة المنزل',
        'display_name': 'شقق اجنحة المنزل',
        # Duplicate pair 8718/9870; the ref-coded record wins.
        'partners': [(8718, 'شقق اجنحة المنزل')],
    },
    {
        'tier': 'base',
        'sheet_name': 'شقق سعيد العمري',
        'display_name': 'شقق سعيد العمري',
    },
    {
        'tier': 'base',
        'sheet_name': 'شقق قصر بوني',
        'display_name': 'شقق قصر بوني',
    },
    {
        'tier': 'base',
        'sheet_name': 'شقق سليم',
        'display_name': 'شقق سليم',
        # Resolved on review to the الحريري apartments record.
        'partners': [(9871, 'شقق الحريري')],
    },
    {
        'tier': 'base',
        'sheet_name': 'شقق سحاب',
        'display_name': 'شقق سحاب',
        # "اسحاب" is a typo for "سحاب"; the (ابحر) suffix is a district note.
        'partners': [(8719, 'شقق اسحاب ( ابحر)')],
    },
    {
        'tier': 'base',
        'sheet_name': 'شاطي جيمي',
        'display_name': 'شاطي جيمي',
    },
    # -- other tiers ---------------------------------------------------------
    {
        'tier': 'fann',
        'sheet_name': 'شقق فنن سويت',
        'display_name': 'شقق فنن سويت',
        # Four فنن سويت records exist; the ref-coded one wins.
        'partners': [(9890, 'فنن سويت للشقق المخدومه')],
    },
    {
        'tier': 'naseem',
        'sheet_name': 'مؤسسة محمد سالم علي الغامدي الفندقية (النسمه الهادي )',
        'display_name': 'مؤسسة محمد سالم علي الغامدي الفندقية (النسمه الهادي)',
        # The sheet name is the legal entity plus its property. The entity is
        # the primary and takes the sheet's name; the property keeps its own,
        # and is priced too so staff get the contract rate either way.
        'partners': [
            (8651, 'مؤسسة محمد سالم علي الغامدي الفندقية'),
            (9873, 'شقق النسمة الهادئه'),
        ],
    },
    {
        'tier': 'lulua',
        'sheet_name': 'شقق لؤلؤة الحمدانية',
        'display_name': 'شقق لؤلؤة الحمدانية',
        # Duplicate pair 8721/9877; the ref-coded record wins.
        'partners': [(8721, 'شقق لؤلؤة الحمدانية')],
    },
]


def _normalise(value):
    """Fold the spelling drift between the sheet and the partner table."""
    if not value:
        return ''
    text = str(value)
    for source, target in (('أ', 'ا'), ('إ', 'ا'), ('آ', 'ا'), ('ى', 'ي'),
                           ('ة', 'ه'), ('ؤ', 'و'), ('ئ', 'ي')):
        text = text.replace(source, target)
    return ' '.join(text.split()).lower()


class HotelPricingSetup(models.AbstractModel):
    _name = 'hotel.pricing.setup'
    _description = 'Hotel Contract Pricing Setup'

    # -- entry point ---------------------------------------------------------

    @api.model
    def sync_structure(self):
        """Ensure the scaffolding exists. Never writes a price.

        Runs on install and on every module upgrade. Existing records are left
        as they are -- only missing ones are created -- so manual backend edits
        survive an upgrade.
        """
        # Searches on a translated field compare against the *active language's*
        # value, so an Arabic session would miss records this sync created under
        # an English one and duplicate them. Pinning to en_US -- the language
        # Odoo stores translated fields' source terms in -- makes the sync
        # behave identically whoever triggers it.
        self = self.with_context(lang='en_US')

        _logger.info('Hotel pricing: structure sync starting (%d catalogue '
                     'products, %d tiers)',
                     len(price_book.PRODUCTS), len(CONTRACT_TIERS))

        self._retire_abandoned_views()
        self._retire_abandoned_access_rules()
        pos_categories = self._sync_pos_category()
        product_category = self._sync_product_category()
        pricelists = self._sync_pricelists()
        products = self._sync_products(pos_categories, product_category)
        self._assign_product_categories(pos_categories, products)
        customer_stats, _notes = self._sync_customers(
            pricelists, assign_pricelists=False)
        pos_stats = self._sync_pos_configs(pricelists, pos_categories)

        _logger.info(
            'Hotel pricing: structure sync done. products=%s customers=%s pos=%s',
            len(products), customer_stats, pos_stats)
        return True

    @api.model
    def bootstrap(self):
        """First-install setup: structure plus the initial price import."""
        self.sync_structure()
        summary = self.env['hotel.price.import'].run_import(
            mode='update_all', dry_run=False, assign_pricelists=True)
        _logger.info('Hotel pricing: bootstrap import %s', summary)
        return True

    # -- helpers -------------------------------------------------------------

    def _translate(self, record, field, arabic):
        """Attach the Arabic term to an already-written English one.

        Assigning a ``{lang: value}`` dict to a translated field does not work
        on create -- Odoo stringifies the dict into the source term -- so the
        English name is written normally and the Arabic one is layered on here.
        """
        record.ensure_one()
        if record.with_context(lang='ar_001')[field] != arabic:
            record.update_field_translations(field, {'ar_001': arabic})

    # -- residue from the abandoned first attempt ----------------------------

    # An earlier attempt at this feature added these fields to the database and
    # built views against them, but was never finished or packaged as a module.
    # The fields are gone from the registry, so every view referencing them
    # fails validation and Odoo disables it -- noisily -- on each load.
    # ``is_hotel_pos`` is deliberately absent: this module declares it again on
    # pos.config, so views using it are valid rather than abandoned.
    ABANDONED_FIELDS = (
        'hotel_pricelist_id',
        'hotel_pricelist_ids',
        'is_hotel_pricelist',
    )

    def _retire_abandoned_views(self):
        """Archive views left behind by the abandoned attempt.

        Only views with no XML id are considered, so nothing another module
        owns can be caught. They are archived rather than deleted: the arch
        stays readable and a mistake is one click to undo.
        """
        candidates = self.env['ir.ui.view'].search([('active', '=', True)])
        if not candidates:
            return
        owned = set(self.env['ir.model.data'].search([
            ('model', '=', 'ir.ui.view'),
            ('res_id', 'in', candidates.ids),
        ]).mapped('res_id'))

        stale = candidates.filtered(
            lambda view: view.id not in owned and any(
                field in (view.arch_db or '') for field in self.ABANDONED_FIELDS
            )
        )
        if stale:
            stale.write({'active': False})
            _logger.info('Hotel pricing: archived %d abandoned view(s): %s',
                         len(stale), ', '.join(stale.mapped('name')))

    # The same abandoned attempt also wrote these access rules straight into the
    # database, each granting *every internal user* create, write and unlink on
    # a core model. Nothing should hand out blanket rights on partners, POS
    # configs, POS orders or pricelists, so they are switched off. Deactivated
    # rather than deleted, and matched on name + model + the absence of an XML
    # id together, so a rule any real module owns can never be caught.
    ABANDONED_ACCESS_RULES = {
        'Hotel POS Config': 'pos.config',
        'Hotel POS Order': 'pos.order',
        'Hotel Partner': 'res.partner',
        'Hotel Pricelist': 'product.pricelist',
    }

    def _retire_abandoned_access_rules(self):
        Access = self.env['ir.model.access'].sudo()
        candidates = Access.search([
            ('active', '=', True),
            ('name', 'in', list(self.ABANDONED_ACCESS_RULES)),
        ])
        if not candidates:
            return
        owned = set(self.env['ir.model.data'].search([
            ('model', '=', 'ir.model.access'),
            ('res_id', 'in', candidates.ids),
        ]).mapped('res_id'))

        stale = candidates.filtered(
            lambda rule: rule.id not in owned
            and rule.model_id.model == self.ABANDONED_ACCESS_RULES.get(rule.name))
        if stale:
            stale.write({'active': False})
            _logger.warning(
                'Hotel pricing: deactivated %d unowned access rule(s) that gave '
                'every internal user full rights on core models: %s',
                len(stale),
                ', '.join('%s on %s' % (r.name, r.model_id.model) for r in stale))

    # -- categories ----------------------------------------------------------

    def _sync_pos_category(self):
        """The hotel POS categories, keyed by group.

        Matched on the English name, which is the source term Odoo stores for a
        translated field -- the whole sync runs pinned to en_US so this lookup
        cannot drift with the reader's language.
        """
        Category = self.env['pos.category']
        categories = {}
        for key, arabic, english, sequence in HOTEL_POS_CATEGORIES:
            category = Category.search([('name', '=', english)], limit=1)
            if not category:
                category = Category.create({
                    'name': english,
                    'sequence': sequence,
                })
                _logger.info('Hotel pricing: created POS category %s', english)
            self._translate(category, 'name', arabic)
            categories[key] = category
        return categories

    def _legacy_pos_category(self):
        arabic, english = LEGACY_HOTEL_POS_CATEGORY
        return self.env['pos.category'].search(
            ['|', ('name', '=', english), ('name', '=', arabic)], limit=1)

    def _hotel_pos_categories(self):
        """Every POS category the hotel catalogue occupies.

        Derived from the products rather than from a flag, so a group added or
        renamed later is still recognised -- and so the retail POS keeps
        excluding it without anyone remembering to update a list.
        """
        products = self.env['product.template'].with_context(
            active_test=False).search([('default_code', 'like', 'HTL-')])
        return products.pos_categ_ids | self._legacy_pos_category()

    def _assign_product_categories(self, categories, products):
        """Put each catalogue product in its group.

        Only moves a product that is still uncategorised or sitting in the old
        catch-all: a product deliberately regrouped in the backend keeps where
        it was put.
        """
        legacy = self._legacy_pos_category()
        moved = 0
        for code, key in HOTEL_PRODUCT_GROUPS.items():
            template = products.get(code)
            target = categories.get(key)
            if not template or not target:
                continue
            current = template.pos_categ_ids
            if current and current != legacy:
                continue
            if current == target:
                continue
            template.pos_categ_ids = [(6, 0, target.ids)]
            moved += 1
        if moved:
            _logger.info('Hotel pricing: grouped %d product(s) into %d POS '
                         'categories', moved, len(categories))
        return moved

    def _sync_product_category(self):
        Category = self.env['product.category']
        parent = Category.search([('name', '=', PARENT_PRODUCT_CATEGORY)], limit=1)
        category = Category.search([
            ('name', '=', HOTEL_PRODUCT_CATEGORY),
            ('parent_id', '=', parent.id if parent else False),
        ], limit=1)
        if not category:
            category = Category.create({
                'name': HOTEL_PRODUCT_CATEGORY,
                'parent_id': parent.id if parent else False,
            })
            _logger.info('Hotel pricing: created product category %s',
                         category.complete_name)
        return category

    # -- pricelists ----------------------------------------------------------

    def _sync_pricelists(self):
        Pricelist = self.env['product.pricelist']
        company = self.env.company
        pricelists = {}

        wanted = dict(TIER_NAMES)
        wanted[NO_CONTRACT_TIER] = NO_CONTRACT_NAMES

        for tier, (arabic, english) in wanted.items():
            is_contract = tier in CONTRACT_TIERS
            pricelist = Pricelist.with_context(active_test=False).search(
                [('hotel_tier', '=', tier)], limit=1)
            if pricelist:
                # Leave the name alone once it exists -- staff may have renamed
                # it, and hotel_tier is what the sync keys on.
                pricelist.write({
                    'active': True,
                    'currency_id': company.currency_id.id,
                    'is_hotel_contract': is_contract,
                })
            else:
                pricelist = Pricelist.create({
                    'name': english,
                    'currency_id': company.currency_id.id,
                    'company_id': company.id,
                    'hotel_tier': tier,
                    'is_hotel_contract': is_contract,
                })
                self._translate(pricelist, 'name', arabic)
                _logger.info('Hotel pricing: created pricelist %s (%s)', english, tier)
            pricelists[tier] = pricelist
        return pricelists

    def _contract_pricelists(self):
        """Every pricelist a hotel customer may legitimately be on.

        Includes customer-specific copies, which have no ``hotel_tier`` but are
        flagged as contracts -- without them the POS would not load a copied
        pricelist and that customer would silently fall back at the till.
        """
        return self.env['product.pricelist'].search(
            [('is_hotel_contract', '=', True)])

    # -- products ------------------------------------------------------------

    def _hotel_taxes(self):
        """Reuse whatever sale tax the existing catalogue already uses.

        Every retail product on this database carries the same VAT-inclusive
        sale tax; matching it keeps hotel receipts arithmetically consistent
        with retail ones instead of introducing a second tax treatment.
        """
        reference = self.env['product.template'].search(
            [('available_in_pos', '=', True), ('taxes_id', '!=', False)], limit=1)
        if reference:
            return reference.taxes_id
        return self.env['account.tax'].search([
            ('type_tax_use', '=', 'sale'),
            ('company_id', '=', self.env.company.id),
        ], limit=1)

    def _sync_products(self, pos_categories, product_category):
        """Create any catalogue product that is missing. Never rewrites one.

        An existing product is left exactly as it is -- renamed, recategorised
        or retaxed by hand in the backend -- because a module upgrade has no
        business undoing a deliberate change. Only its presence is guaranteed.
        """
        Template = self.env['product.template']
        taxes = self._hotel_taxes()
        products = {}
        created = existing = 0

        for code, arabic, english, _prices in price_book.PRODUCTS:
            template = Template.with_context(active_test=False).search(
                [('default_code', '=', code)], limit=1)
            if template:
                products[code] = template
                existing += 1
                continue
            template = Template.create({
                'name': english,
                'default_code': code,
                'type': 'service',
                'categ_id': product_category.id,
                'pos_categ_ids': [(6, 0, pos_categories[
                    HOTEL_PRODUCT_GROUPS.get(code, 'bed')].ids)],
                'available_in_pos': True,
                'sale_ok': True,
                'purchase_ok': False,
                'active': True,
                # Contract prices live in the pricelists; a fixed pricelist rule
                # replaces the sales price outright, so this stays at zero.
                'list_price': 0.0,
                'taxes_id': [(6, 0, taxes.ids)],
            })
            self._translate(template, 'name', arabic)
            products[code] = template
            created += 1

        _logger.info('Hotel pricing: products created=%d already present=%d',
                     created, existing)
        return products

    # -- customers -----------------------------------------------------------

    def _resolve_customer(self, entry):
        """Find (or create) the partners behind one price-sheet customer.

        Returns ``(partners, note)``. The first partner is the primary and is
        the one given the sheet's canonical name; any others are related records
        that keep their own names but are priced too, so staff get the contract
        rate whichever they pick.

        A partner whose name no longer matches what the review recorded is
        reported as ambiguous and left alone -- an id reused by a different
        record must never be silently mispriced. The canonical name counts as a
        match as well, so renaming during import does not break later runs.
        """
        Partner = self.env['res.partner']
        sheet_name = entry['sheet_name']
        canonical = entry['display_name']

        if not entry.get('partners'):
            partner = Partner.with_context(active_test=False).search(
                [('hotel_excel_name', '=', sheet_name)], limit=1)
            if partner:
                return partner, 'existing'
            partner = Partner.create({
                'name': canonical,
                'company_type': 'company',
                'customer_rank': 1,
                'hotel_excel_name': sheet_name,
            })
            return partner, 'created'

        partners = Partner.browse()
        ambiguous = []
        for partner_id, expected_name in entry['partners']:
            partner = Partner.browse(partner_id).exists()
            if not partner:
                ambiguous.append('partner %s (%s) no longer exists'
                                 % (partner_id, expected_name))
                continue
            current = _normalise(partner.name)
            if current not in (_normalise(expected_name), _normalise(canonical)):
                ambiguous.append(
                    'partner %s is now %r, review recorded %r'
                    % (partner_id, partner.name, expected_name))
                continue
            partners |= partner
        return partners, ('ambiguous: ' + '; '.join(ambiguous)) if ambiguous else 'existing'

    def _sync_customers(self, pricelists, assign_pricelists=True,
                        rename=False, dry_run=False):
        """Make sure every price-sheet customer exists and is marked.

        ``assign_pricelists`` is off during a plain module upgrade: a customer
        moved onto their own copied pricelist must not be dragged back to the
        shared tier. Even when on, an existing contract pricelist is respected --
        only customers with no contract at all are placed on their tier.
        """
        Partner = self.env['res.partner']
        stats = {'created': 0, 'linked': 0, 'renamed': 0, 'unchanged': 0,
                 'ambiguous': 0, 'failed': 0}
        notes = []

        for entry in CUSTOMER_MAP:
            pricelist = pricelists.get(entry['tier'])
            sheet_name = entry['sheet_name']
            canonical = entry['display_name']

            try:
                if dry_run and not entry.get('partners'):
                    existing = Partner.with_context(active_test=False).search(
                        [('hotel_excel_name', '=', sheet_name)], limit=1)
                    if not existing:
                        stats['created'] += 1
                        notes.append('would create %r' % canonical)
                        continue
                    partners, state = existing, 'existing'
                else:
                    partners, state = self._resolve_customer(entry)
            except Exception as error:                      # pragma: no cover
                stats['failed'] += 1
                notes.append('%s: %s' % (sheet_name, error))
                _logger.exception('Hotel pricing: customer %r failed', sheet_name)
                continue

            if state == 'created':
                stats['created'] += 1
            elif state.startswith('ambiguous'):
                stats['ambiguous'] += 1
                notes.append('%s -> %s' % (sheet_name, state))
                _logger.warning('Hotel pricing: %s -> %s', sheet_name, state)

            if not partners:
                continue

            for index, partner in enumerate(partners):
                values = {}
                if not partner.is_hotel_customer:
                    values['is_hotel_customer'] = True
                if partner.hotel_excel_name != sheet_name:
                    values['hotel_excel_name'] = sheet_name
                if partner.customer_rank < 1:
                    values['customer_rank'] = 1
                # Only the primary carries the sheet's canonical name; the
                # others are distinct real records that keep their own.
                if rename and index == 0 and partner.name != canonical:
                    values['name'] = canonical
                    stats['renamed'] += 1
                    notes.append('renamed %r -> %r' % (partner.name, canonical))
                if assign_pricelists and pricelist and \
                        not partner.property_product_pricelist.is_hotel_contract:
                    values['property_product_pricelist'] = pricelist.id
                    stats['linked'] += 1

                if not values:
                    stats['unchanged'] += 1
                elif not dry_run:
                    partner.write(values)

        _logger.info('Hotel pricing: customers %s', stats)
        return stats, notes

    # -- point of sale -------------------------------------------------------

    def _sync_pos_configs(self, pricelists, pos_categories):
        """Give hotels their own POS and keep the retail one out of it."""
        hotel_config = self._sync_hotel_pos_config(pricelists, pos_categories)
        retail_stats = self._restore_retail_pos_configs()
        self._retire_obsolete_retail_pricelist()
        return {'hotel_pos': hotel_config.name, 'retail': retail_stats}

    def _retire_obsolete_retail_pricelist(self):
        """Archive the placeholder pricelist an earlier revision created.

        It existed only to be the retail POS default while hotel pricing lived
        there. Archiving it while a config still points at it would leave that
        config defaulting to a record the POS loader cannot see, so it waits
        until nothing references it -- which, when an open session blocks the
        retail cleanup, means the next sync after that session closes.
        """
        Pricelist = self.env['product.pricelist']
        obsolete = Pricelist.search([('hotel_tier', '=', RETIRED_RETAIL_TIER),
                                     ('active', '=', True)])
        if not obsolete:
            return
        referencing = self.env['pos.config'].with_context(active_test=False).search([
            '|', ('pricelist_id', 'in', obsolete.ids),
            ('available_pricelist_ids', 'in', obsolete.ids),
        ])
        if referencing:
            _logger.info(
                'Hotel pricing: keeping obsolete pricelist %s active -- still '
                'referenced by %s', ', '.join(obsolete.mapped('name')),
                ', '.join(referencing.mapped('name')))
            return
        obsolete.write({'active': False})
        _logger.info('Hotel pricing: archived obsolete retail pricelist %s',
                     ', '.join(obsolete.mapped('name')))

    def _changed_values(self, config, values):
        """Drop keys already at the wanted value.

        pos.config refuses several fields while a session is open. Writing only
        what genuinely differs means a repeat sync sends nothing and never trips
        that guard, instead of relying on bypass flags to force a no-op through.
        """
        changed = {}
        for field_name, value in values.items():
            current = config[field_name]
            if isinstance(value, list):  # (6, 0, ids) command
                if sorted(current.ids) != sorted(value[0][2]):
                    changed[field_name] = value
            elif hasattr(current, 'ids'):  # many2one
                if current.id != value:
                    changed[field_name] = value
            elif current != value:
                changed[field_name] = value
        return changed

    def _sync_hotel_cash_journal(self):
        """A cash journal exclusive to the hotel POS.

        Odoo creates a fresh liquidity account for any new cash journal, so the
        hotel drawer gets its own balance rather than sharing retail's. Cash
        difference profit/loss accounts come from the company defaults, which is
        what the retail journal uses too -- those are P&L accounts and carry no
        register balance, so sharing them is harmless.
        """
        Journal = self.env['account.journal']
        company = self.env.company
        journal = Journal.with_context(active_test=False).search([
            ('code', '=', HOTEL_CASH_JOURNAL_CODE),
            ('company_id', '=', company.id),
        ], limit=1)
        if journal:
            if not journal.active:
                journal.active = True
            return journal

        arabic, english = HOTEL_CASH_JOURNAL_NAMES
        journal = Journal.create({
            'name': english,
            'code': HOTEL_CASH_JOURNAL_CODE,
            'type': 'cash',
            'company_id': company.id,
        })
        self._translate(journal, 'name', arabic)
        _logger.info(
            'Hotel pricing: created cash journal %s (%s) with its own liquidity '
            'account %s', english, HOTEL_CASH_JOURNAL_CODE,
            journal.default_account_id.code)
        return journal

    def _sync_hotel_payment_methods(self, template):
        """Bank, Customer Account and a hotel-only Cash method.

        Non-cash methods are shared with the retail POS: bank and pay-later
        methods hold no per-session register, so two configs can use the same
        one safely. Cash cannot be shared -- its register is opened and counted
        per session, and Odoo's own default deliberately picks cash methods with
        ``config_ids = False`` to avoid handing one to two tills -- so the hotel
        POS gets its own, backed by its own journal.
        """
        Method = self.env['pos.payment.method']
        company = self.env.company
        journal = self._sync_hotel_cash_journal()

        cash = Method.with_context(active_test=False).search([
            ('journal_id', '=', journal.id)], limit=1)
        if cash:
            if not cash.active:
                cash.active = True
        else:
            arabic, english = HOTEL_CASH_METHOD_NAMES
            cash = Method.create({
                'name': english,
                'journal_id': journal.id,
                'company_id': company.id,
            })
            self._translate(cash, 'name', arabic)
            _logger.info('Hotel pricing: created cash payment method %s on '
                         'journal %s', english, journal.code)

        shared = self.env['pos.payment.method']
        if template:
            shared = template.payment_method_ids.filtered(
                lambda method: not method.is_cash_count
                and method.company_id.id in (False, company.id))
            excluded = template.payment_method_ids - shared
            if excluded:
                _logger.info(
                    'Hotel pricing: retail cash method(s) %s deliberately not '
                    'shared; the hotel POS uses %s instead',
                    ', '.join(excluded.mapped('name')), cash.name)

        methods = shared | cash
        _logger.info('Hotel pricing: hotel POS payment methods: %s',
                     ', '.join(methods.mapped('name')))
        return methods

    def _operational_settings_from(self, template):
        """Copy just enough from the retail POS for the hotel POS to work.

        Sale and invoice journals, the operation type and the warehouse are
        shared by POS configs as a matter of course; sharing them avoids
        inventing accounting objects that would fragment reporting.
        """
        settings = {}
        if template:
            for field_name in ('journal_id', 'invoice_journal_id',
                               'picking_type_id', 'warehouse_id'):
                if field_name in self.env['pos.config']._fields and template[field_name]:
                    settings[field_name] = template[field_name].id
        settings['payment_method_ids'] = [
            (6, 0, self._sync_hotel_payment_methods(template).ids)]
        return settings

    def _sync_hotel_pos_config(self, pricelists, pos_categories):
        Config = self.env['pos.config']
        config = Config.with_context(active_test=False).search(
            [('is_hotel_pos', '=', True)], limit=1)

        # Every contract pricelist has to be attached, customer-specific copies
        # included, or the POS will not load one and that customer would be
        # priced from the default instead.
        no_contract = pricelists[NO_CONTRACT_TIER]
        available = self._contract_pricelists() | no_contract
        arabic, english = HOTEL_POS_NAMES

        values = {
            'limit_categories': True,
            # The six groups only. The old catch-all is left out, so the
            # filter bar shows real groups instead of one useless "فنادق".
            'iface_available_categ_ids': [(6, 0, sorted(
                c.id for c in pos_categories.values()))],
            'use_pricelist': True,
            'available_pricelist_ids': [(6, 0, available.ids)],
            # Deliberately *not* a contract tier: an order with no customer
            # must not quietly inherit real agreed prices.
            'pricelist_id': no_contract.id,
            'active': True,
        }

        template = Config.search([('is_hotel_pos', '=', False)], limit=1)

        if not config:
            create_values = dict(values, name=english, is_hotel_pos=True,
                                 company_id=self.env.company.id)
            create_values.update(self._operational_settings_from(template))
            config = Config.create(create_values)
            self._translate(config, 'name', arabic)
            _logger.info('Hotel pricing: created POS %r (id %s) with payment '
                         'methods %s', english, config.id,
                         ', '.join(config.payment_method_ids.mapped('name')))
            return config

        # Make sure the methods and pricelists this module owns are present
        # without dropping anything an operator added by hand -- and because
        # removing an available pricelist is rejected outright while a session
        # is open, whereas adding one is allowed.
        required = self._sync_hotel_payment_methods(template)
        methods = config.payment_method_ids | required
        values['payment_method_ids'] = [(6, 0, methods.ids)]
        values['available_pricelist_ids'] = [
            (6, 0, (config.available_pricelist_ids | available).ids)]

        changed = self._changed_values(config, values)
        if changed:
            try:
                config.with_context(
                    bypass_categories_forbidden_change=True,
                    bypass_payment_method_ids_forbidden_change=True,
                ).write(changed)
                _logger.info('Hotel pricing: updated hotel POS %s (%s)',
                             config.name, ', '.join(changed))
            except UserError as error:
                _logger.warning(
                    'Hotel pricing: hotel POS %s has an open session, so %s '
                    'could not be updated: %s',
                    config.name, ', '.join(changed), error)
        self._translate(config, 'name', arabic)
        return config

    def _restore_retail_pos_configs(self):
        """Keep hotel products and hotel pricelists off the retail POS.

        Hiding the hotel category is the only per-config way to exclude
        products, so the retail POS is restricted to every category except
        ``فنادق``. Removing an available pricelist or switching ``use_pricelist``
        off is rejected outright while a session is open -- there is no bypass
        for either -- so that half is attempted separately and reported if it
        cannot be applied yet.
        """
        retail_categories = self.env['pos.category'].search(
            [('id', 'not in', self._hotel_pos_categories().ids)])
        hotel_tiers = self.env['product.pricelist'].with_context(
            active_test=False).search([('hotel_tier', '!=', False)])
        blocked = []
        touched = []

        for config in self.env['pos.config'].search([('is_hotel_pos', '=', False)]):
            # Products: restrict to the non-hotel categories.
            category_values = self._changed_values(config, {
                'limit_categories': True,
                'iface_available_categ_ids': [(6, 0, retail_categories.ids)],
            })
            if category_values:
                try:
                    # Odoo provides this bypass precisely so category limits can
                    # be corrected without waiting for a session to close; the
                    # running client keeps the catalogue it already loaded.
                    config.with_context(
                        bypass_categories_forbidden_change=True
                    ).write(category_values)
                    touched.append('%s: categories' % config.name)
                except UserError as error:
                    blocked.append('%s: categories (%s)' % (config.name, error))

            # Pricelists: strip anything this module put there.
            keep = config.available_pricelist_ids - hotel_tiers
            pricelist_values = {}
            if keep != config.available_pricelist_ids:
                pricelist_values['available_pricelist_ids'] = [(6, 0, keep.ids)]
            if not keep and config.use_pricelist:
                pricelist_values['use_pricelist'] = False
            if config.pricelist_id and config.pricelist_id in hotel_tiers:
                pricelist_values['pricelist_id'] = keep[:1].id if keep else False

            if pricelist_values:
                try:
                    config.write(pricelist_values)
                    touched.append('%s: pricelists' % config.name)
                except UserError:
                    blocked.append(
                        '%s: hotel pricelists still selectable until the open '
                        'session is closed' % config.name)

        if blocked:
            for note in blocked:
                _logger.warning('Hotel pricing: %s', note)
        _logger.info('Hotel pricing: retail POS adjustments %s (blocked: %s)',
                     touched or 'none', blocked or 'none')
        return {'applied': touched, 'blocked': blocked}
