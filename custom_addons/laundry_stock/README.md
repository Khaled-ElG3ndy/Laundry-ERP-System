# Laundry Inventory & Purchasing — مخازن ومشتريات المغسلة

`laundry_stock` gives every laundry branch a real warehouse, tracks the supplies
it consumes, and covers buying them end to end. Every label follows the user's
own language: Arabic for `ar_001` users, English for `en_US` users.

يعطي كل فرع مخزناً حقيقياً بتقسيمة واضحة، ويتابع المواد التي يستهلكها، ويغطي
دورة الشراء كاملة. كل المسميات تظهر بلغة المستخدم نفسه.

## The warehouse layout — تقسيمة المخزن

Each branch gets one warehouse. Its store is split into six zones, and a
put-away rule sends every received product to its own zone automatically:

| Zone | Location | What goes in it |
|------|----------|-----------------|
| `CHEM` | Chemicals & Detergents / كيماويات ومنظفات | detergent, softener, bleach, solvent, spotting |
| `PACK` | Packaging & Covers / تغليف وأغطية | covers, bags, boards, tissue |
| `HANG` | Hangers & Tags / شماعات وبطاقات | hangers, clips, pins, tags |
| `SPARE` | Spare Parts & Maintenance / قطع غيار وصيانة | belts, valves, hoses, lubricant |
| `LINEN` | Linen & Uniforms / بياضات ويونيفورم | uniforms, towels, board covers |
| `HKPG` | Housekeeping & Office / نظافة ومستلزمات مكتبية | cleaners, gloves, paper, receipt rolls |

A seventh, virtual location per branch — `Laundry Consumption / استهلاك المغسلة`
— receives everything the branch uses up. What lands there is the branch's
consumption, and it is what the analysis report reads.

Provisioning is idempotent: **Set Up Warehouse** on the branch form creates
what is missing and leaves the rest alone. Installing the module runs it once
for every branch that already exists.

## Day to day — التشغيل اليومي

1. **Buy** — a branch files a *Purchase Request*, a manager approves it, and
   **Create RFQ** turns it into one request for quotation per vendor, delivered
   to the branch's own warehouse.
2. **Receive** — the standard receipt. Put-away rules shelve each line in its
   zone; average costing keeps the product cost in step with what was paid.
3. **Consume** — a *Material Issue* takes supplies out of the store against
   production, a machine, housekeeping or damage. Confirming posts a real stock
   transfer, so on-hand quantities never drift from the shelf. A *Return to
   Store* puts back what was drawn and not used.
4. **Watch** — *Stock on Hand* per zone, *Reordering Rules* for what to buy
   before a branch runs out, *Consumption Analysis* for what each branch used,
   on which order or machine, and what it cost.

## The dashboard — لوحة المخزون

`Inventory > Dashboard` is the front door: stock value, what to reorder, what is
out, what this month cost, requests waiting for approval and receipts still open
— then consumption over six months, stock per storage zone, what to buy before
it runs out, the most used materials, and the latest movements. Every tile and
row opens the screen behind it, and a branch selector narrows the whole board.

It lives in this module (`models/laundry_stock_dashboard.py` for the data, one
OWL client action under `static/src/`), borrows the `--lf-*` design tokens the
laundry theme defines, and falls back to the same values when that theme is
absent. Its CSS is logical-properties-only and the component stamps its own
`dir` from the user's language, because Odoo's backend leaves `dir` off the
document and this server builds the RTL bundle unmirrored.

## Two ways materials get issued — طريقتان للصرف

The counter sells a garment with a service variant (ironing, wash & iron, deep
clean); the back office writes laundry orders with a service type. Norms speak
both languages, and so do the two ways to issue:

* **Issue from Sales** (`Inventory > Issue from Sales`) reads what the counter
  sold over a period, applies the norms, and prepares one issue to check before
  confirming. A period already issued is refused unless you insist.
* **Issue Materials** on a laundry order does the same for one order.

## Consumption norms — معدلات الاستهلاك

A norm says how much of a supply a piece, a kilogram or a whole order consumes.
Norms can be scoped to a service, an item category and a branch; the most
specific norm wins per supply. They do two things:

* cost an order before it is washed (`Expected Material Cost`);
* fill a material issue in one click (**Issue Materials** on the order, or
  **Fill from Norms** on the issue).

A norm is scoped by what the counter sold (**POS Service**, **Sales
Category**, **Sold Item**) or by what the back office wrote (**Service**,
**Item Category**), and optionally by branch. The most specific norm wins per
supply, and **Not Used** cancels a more general one — a blanket takes no hanger.

Per-kilogram doses are converted with `Average Weight (kg)` on the item
category, or with the product weight for counter sales — 20 shirts at 0.25 kg
and a dose of 0.012 come to 0.06 kg.

**Load Starter Norms** in the norms list writes a first set from the services
your counter sells. Every figure in it is a starting point to correct against
your own usage.

Switch `Auto-issue Materials` on for a branch and the issue is posted by itself
when an order reaches the stage you choose. A failure there is logged on the
order and never blocks the shop floor.

## First counts — أرصدة أول المدة

`Inventory > Opening Stock` lays out a count line for every supply, in the zone
it belongs to. Type what is on the shelf in **Counted Quantity** and press
**Apply**; Odoo posts the difference as an inventory adjustment.

## Groups — الصلاحيات

| Group | Can |
|-------|-----|
| `Laundry / Store Keeper` | receive, issue, count, file purchase requests |
| `Laundry / Purchasing Officer` | approve requests, deal with vendors |
| `Laundry / Branch Manager` | store keeper + approve |
| `Laundry / System Admin` | everything, including warehouses and locations |

Production staff can write and confirm their own issues, and see the ones from
their branch.

## Accounting — المحاسبة

Supply categories are costed at **average** with **periodic (manual)**
valuation: product costs follow the purchase prices, and no stock move posts a
journal entry by itself. The expense hits the ledger when the vendor bill is
posted, on the expense account of the product category (the company default is
`600000 Expenses` unless the accountant sets another one).

## Files — الملفات

```
models/laundry_branch.py            warehouse, zones, put-away, consumption location
models/laundry_stock_issue.py       material issue + lines, posts the transfer
models/laundry_purchase_request.py  internal request, approval, RFQ creation
models/laundry_consumption_norm.py  norms and how they are matched
models/laundry_machine.py           machines, for maintenance issues
report/laundry_consumption_report.py  SQL view behind Consumption Analysis
i18n/ar_001.po, i18n/ar.po          every string in Arabic
```

## Deploy — النشر

```bash
sudo MODULES="laundry_stock" scripts/deploy_laundry_addons.sh
```

The script backs the database up, prints the rollback commands, syncs the
addon, upgrades it and restarts the service. `purchase`, `purchase_stock` and
`stock_account` are installed as dependencies on first install.
