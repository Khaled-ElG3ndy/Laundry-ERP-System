# Hotel Contract Pricing — Farha Laundry

Gives hotel and company customers their own point of sale, where selecting a
customer applies that customer's agreed contract prices automatically.

## Two points of sale, kept apart

| | مغاسل رغوة بلس (retail) | مبيعات الفنادق والشركات (hotel) |
|---|---|---|
| Products | 4 retail categories only | `فنادق` category only |
| Pricing | variant `price_extra`, no pricelist | 4 contract pricelists |
| Sessions | its own | its own |
| Owned by this module | no | yes (`pos.config.is_hotel_pos`) |

Both appear as cards on the Point of Sale dashboard. Neither can see the
other's products: each config is restricted with `limit_categories` +
`iface_available_categ_ids`, which is the only per-config product filter Odoo
offers.

## How the pricing works

Odoo 17 already re-prices an entire open order when the customer changes:

```
Order.set_partner()
  -> updatePricelistAndFiscalPosition()      # reads partner.property_product_pricelist
     -> set_pricelist()                      # recomputes every existing order line
```

The POS javascript is deliberately tiny: it removes the manual pricelist button
and refuses to add a product before a contract customer is chosen. It holds no
pricing logic and no customer names. Everything else is ordinary data:

| What | Where |
|---|---|
| 36 hotel linen services, one shared catalogue | `product.template`, `default_code = HTL-01 … HTL-36` |
| 4 contract price tiers | `product.pricelist`, keyed by `hotel_tier` |
| 144 fixed-price rules | `product.pricelist.item`, `applied_on = 1_product` |
| Customer → tier assignment | `res_partner.property_product_pricelist` |
| The dedicated POS | `pos.config`, keyed by `is_hotel_pos` |

Rules are written at **template** level with `compute_price = 'fixed'`. A fixed
rule replaces the price outright instead of adding to it, so every variant of a
hotel product resolves to the same contract price — which is what a sheet with
one price per item means. The POS client fans template rules out to each variant
in `pos_store.js::_loadProductProduct`.

## Payment methods

The hotel POS takes all three payment types:

| Method | Journal | Shared with retail? |
|---|---|---|
| Bank | `BNK1` | yes — a bank method holds no per-session register |
| Customer Account | none (pay later) | yes — settles against the receivable |
| Cash (Hotel & Company) | `CSHH` → its own liquidity account | **no** |

**Cash is deliberately not shared.** A cash method carries a drawer that is
opened and counted per session; two tills sharing one would count each other's
money. Odoo's own `_get_default_payment_methods` only offers cash methods with
`config_ids = False` for exactly this reason. So the module creates a dedicated
cash journal (`CSHH`), and because Odoo gives every new cash journal a freshly
created liquidity account, the hotel drawer has its own balance from the start.
Cash-difference profit/loss accounts come from the company defaults — the retail
journal uses those too, and they are P&L accounts carrying no register balance,
so sharing them is harmless.

Sale and invoice journals, the operation type and the warehouse **are** shared
with the retail POS — POS configs share these as a matter of course, and sharing
avoids fragmenting reporting with duplicate accounting objects.

## The cashier workflow

The cashier picks a **customer**, never a price tier. The manual pricelist
button is removed from the hotel POS (`ProductScreen.controlButtons` filters out
`SetPricelistButton`), so the automatic path is the only path:

```
cashier selects customer
  -> Order.set_partner()
     -> updatePricelistAndFiscalPosition()   reads property_product_pricelist
        -> set_pricelist()                   recomputes every existing line
```

Adding a product is refused until a contract customer is selected, and refused
again at payment on the server, so an offline client replaying queued orders
cannot get round it.

The POS default pricelist is deliberately **not** a contract tier. It is an
empty *No Contract* list, so an unconfigured customer prices at 0.00 —
obviously wrong on screen rather than plausibly wrong — instead of silently
inheriting real agreed base rates.

## How customer filtering works

`pos.session._hotel_partner_domain()` returns `[('is_hotel_customer','=',True)]`
for the hotel POS and `[]` for retail. It is applied in two places, because the
base code loads and searches partners through different paths:

* `_get_pos_ui_res_partner` — the preload. The base method discards the loader
  domain in favour of the 100 most-used partners, so the filter is reapplied
  here; the hotel list is small enough to load whole.
* `get_pos_ui_res_partner_by_params` — live search. The client's own domain
  wins in the base method, so the hotel domain is appended to it.

No names appear anywhere in javascript. Marking a new partner as a hotel
customer makes them appear at the till with no code change.

## Editing prices in the backend

Prices are ordinary `product.pricelist.item` rules. On a hotel customer's form:

* a **أسعار عقد الفندق / Hotel Contract Prices** smart button opens that
  customer's rules for editing,
* **Open Pricelist** opens the pricelist record itself,
* a warning appears when the pricelist is shared, naming how many other
  customers an edit would affect,
* **إنشاء قائمة أسعار خاصة بالعميل / Create Customer-Specific Pricelist** copies
  the shared list, moves only that customer onto the copy, and leaves everyone
  else where they were.

A copy carries `is_hotel_contract = True` but **no** `hotel_tier`, which is what
keeps a later sheet import from writing over a negotiated price. It is attached
to the hotel POS automatically, otherwise the POS would not load it and that
customer would fall back at the till.

Menus live under **Point of Sale > Hotel Contracts** and are limited to the
*Hotel Contract Manager* group.

## Importing the price sheet

Importing is an explicit action — **Point of Sale > Hotel Contracts > Import
Price Sheet** — never a side effect of an upgrade. Three modes:

| Mode | Behaviour |
|---|---|
| Add missing, update untouched *(default)* | leaves any price edited since it was imported |
| Only add missing | never changes an existing price |
| Overwrite everything | restores the sheet's prices, discarding manual edits |

**Preview only** is on by default: it reports exactly what would change and
writes nothing. Every run reports created / updated / skipped / unchanged /
ambiguous / failed, for both prices and customers, with a per-row detail list.

"Edited by hand" is tracked honestly: each imported rule stores
`hotel_imported_price` plus a separate `hotel_import_tracked` flag, so a genuine
imported price of 0.00 is not mistaken for "never imported".

## Invoices typed in Accounting

Odoo 17 prices an invoice line from the product's own sales price and never
reads the customer's pricelist. Hotel products have a sales price of 0.00 (their
price lives only in the contract pricelist), so an invoice written by hand for
a hotel customer used to come out at 0.00. `models/account_move.py` fixes that:

* On a customer invoice or credit note, a product line asks the customer's
  pricelist first **when it is a hotel contract** (`is_hotel_contract`), the
  same way a sale order line does. The fixed price is converted to the
  invoice currency and the fiscal position is applied, as core does for a
  product's own price. VAT comes from the product (the exclusive 15%).
* Changing the customer on a draft invoice re-prices the lines whose product
  has a hotel contract rule, as the POS re-prices on `set_partner`. A line
  added before the customer was chosen therefore still ends up at the
  contract price. Other lines keep whatever price was typed on them.
* Everything else is core behaviour: customers without a contract (every
  partner resolves to *some* fallback pricelist, which is deliberately not
  applied), vendor bills, and every line created with an explicit price (POS
  invoices, sale order invoices, credit notes from the reversal wizard).

## Security

One narrow group, **Hotel Contract Manager**, gates the contract-price tools and
the importer. It grants no rights on `res.partner`, `pos.config`, `pos.order` or
`product.pricelist` — those keep whatever Odoo's own POS and Sales groups
define, so a cashier stays a cashier. The only `ir.model.access` line this
module ships is for its own wizard model.

The structure sync also deactivates four unowned access rules left in the
database by the abandoned first attempt, which had granted *every internal user*
create, write and unlink on partners, POS configs, POS orders and pricelists.


## Why hotel products are separate from the retail catalogue

They are a different service sold on different terms, not the same service at a
discount:

* **Price scale.** Retail `شرشف كبير` (wash + iron) is 11.04 SAR; the hotel
  `شرشف سرير كبير` is 2.90. The gap runs 3–5× across the overlap.
* **Pricing dimensions.** Retail products are variant-driven on *Service Type*
  (كوي / غسيل + كوي / كوي مستعجل / غسيل + كوي مستعجل), each tier priced
  separately via `price_extra`. The sheet has exactly one price per item.
  Mapping onto retail templates would leave three of four service tiers
  unpriced for hotels, or flatten express service to the standard rate.
* **Different items.** 16 of the 36 have no retail counterpart at all — chair
  covers, tablecloths, napkins, bath mats, bed valances, duvets and duvet
  covers, chef jackets. The retail catalogue is garment-centric.
* **Different classification.** Retail sizes are كبير/وسط/صغير, hotel is
  كبير/صغير. Retail curtains are sized and sold per piece; hotel curtains are
  classified by fabric and billed per metre.

Retail products carry no hotel rules and the retail POS uses no pricelist at
all, so retail pricing is byte-for-byte unchanged.

## The one thing an open session can block

`pos.config` rejects three changes outright while a session is open, and only
two of them have a bypass:

| Change | While a session is open |
|---|---|
| `limit_categories`, `iface_available_categ_ids` | allowed via `bypass_categories_forbidden_change` |
| adding an available pricelist | allowed |
| **removing** an available pricelist, or `use_pricelist = False` | **rejected, no bypass** |

An earlier revision of this module put hotel pricing on the retail POS. Undoing
that needs the removal path, so if the retail POS has a session open the sync
applies the category restriction, logs a warning naming what it could not do,
and leaves the rest for the next run. Nothing is forced through and nothing is
half-applied — the pricelist changes are written as one `write`, so they either
all land or none do.

Exposure while it is pending is nil: the hotel pricelists hold rules only for
hotel products, hotel products are already hidden from the retail POS, and none
of the tiers carry a global or category-wide rule. A retail product prices
identically under every hotel tier. Closing the session and re-running
`-u hosny_hotel_pos` completes the cleanup.

## Re-importing an amended price sheet

```bash
python3 custom_addons/hosny_hotel_pos/tools/import_price_book.py \
    "/opt/odoo17/كشف اسعار مفصل بالعماء 1.xlsx"

sudo systemctl stop odoo17-farha
su -s /bin/bash odoo17 -c "cd /tmp && /opt/odoo17/venv/bin/python \
    /opt/odoo17/odoo/odoo-bin -c /etc/odoo17-farha.conf -d farha_laundry \
    -u hosny_hotel_pos --workers=0 --max-cron-threads=0 --stop-after-init"
sudo systemctl start odoo17-farha
```

Then run the importer from the UI. The generator warns about sheet items
missing from `CATALOG` (add them with a fresh `HTL-xx` code) and `CATALOG` items
missing from the sheet. The sync is
keyed on `default_code`, `hotel_tier` and reviewed partner ids — never on names
— so repeat runs update in place and never duplicate. Verified: install plus
three upgrades leaves 36 products / 144 rules / 15 partners / exactly one hotel
`pos.config`. The POS config is matched on `is_hotel_pos`, so renaming it in the
UI never causes a second one to be created.

## Customer mapping

`CUSTOMER_MAP` in `models/hotel_setup.py` records the reviewed decision for each
of the 14 sheet customers, with the reasoning inline. Each linked entry stores
the partner name as it read at review time; if a partner is later renamed or
deleted the sync **skips it with a warning** rather than pricing what might be a
different customer. `res_partner.hotel_excel_name` keeps the original sheet
spelling for traceability.

## Notes

* Contract prices are quoted **before VAT**, so hotel products carry the
  price-exclusive 15% sale tax (the company default) and VAT is added on top:
  a 2.90 sheet price bills 2.90 + 0.44 = 3.34. Retail keeps its VAT-inclusive
  tax. The hotel POS shows prices before tax (`iface_tax_included =
  'subtotal'`), so the till and the receipt lines show the contract price and
  the receipt lists subtotal, VAT and total separately. Until 17.0.4.1.0 hotel
  products used the retail VAT-inclusive tax; the migration for that version
  moved them over. Orders taken before it keep the tax stored on their lines.
* Four items are priced at or near zero in the sheet and were imported verbatim:
  `ديكور طاولة`, `حلية طاولة`, `فستان` (0.15 base / 0.00 fann / 0.10 naseem /
  0.00 lulua) and `سجادة صلاة` (0.00 everywhere). Confirm these are intended
  before selling them.
* A POS session loads its catalogue and pricelists once, at session start. Any
  change made here reaches the till on the next session, not the current one.
* Adding a new retail POS category later will not appear on the retail POS until
  the next `-u hosny_hotel_pos`, because the retail config is pinned to an
  explicit category list in order to exclude `فنادق`.

## The payment guard

The hotel POS defaults to the **base** contract tier, so without a check a
walk-in — or an order with no customer at all — would be charged agreed hotel
rates instead of retail ones. That is what this guard prevents.

`pos.order._process_order` refuses to settle an order on the hotel POS unless
the selected customer has a contract pricelist. Enforced server-side because
that is the single point every payment passes through, including orders replayed
after an offline spell — javascript could be bypassed by a stale client.

* No customer, or a customer with no contract tier → `UserError`, in Arabic and
  English, naming the customer.
* Draft (parked, unpaid) orders are exempt — the check is about taking money.
* The retail POS is untouched: a no-customer cash sale there still works.

It sits above `pos_laundry_receipt`'s own `_process_order`, which calls `super()`
first, so a blocked order never creates a partial laundry intake.
