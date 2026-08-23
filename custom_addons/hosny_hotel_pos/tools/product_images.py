# -*- coding: utf-8 -*-
"""Give the hotel catalogue the same product imagery the retail catalogue uses.

Run against a database::

    su -s /bin/bash odoo17 -c "cd /tmp && /opt/odoo17/venv/bin/python \
        /opt/odoo17/odoo/odoo-bin shell -c /etc/odoo17-farha.conf \
        -d farha_laundry --workers=0 --max-cron-threads=0 --no-http" \
        < tools/product_images.py

Images only. Nothing here touches prices, customers, pricelists, the POS
configuration or any other behaviour, and an existing image is never replaced.

Why copy rather than draw
-------------------------
Every retail image is an RGBA cut-out on a transparent background, cropped to
the object, in a mix of photographic and flat-illustration styles. Copying the
exact bytes of an existing image gives byte-identical dimensions, aspect ratio,
padding and quality -- the only way to guarantee the hotel products look like
they came from the same set. Odoo regenerates the 1024/512/256/128 variants
from ``image_1920`` on write, exactly as it did for the retail products.

Note on the retail catalogue's own imagery: its bed sheets, mattress pads,
blanket, towels and pillowcase all use the same folded grey textile photo
(separate crops of it, not one shared file). Hotel linens therefore inherit that
same photo -- that *is* the house style, not a shortcut.
"""

# HTL code -> (source product.template id, why)
# Only mappings whose source image was visually checked to depict the right
# thing are listed. Anything uncertain is in NEEDS_ARTWORK instead.
IMAGE_SOURCES = {
    'HTL-01': (126, 'شرشف كبير - the retail bed-sheet image'),
    'HTL-02': (125, 'شرشف صغير - the retail bed-sheet image'),
    'HTL-03': (126, 'duvet cover: folded bed linen, same photo as bed sheets'),
    'HTL-04': (125, 'duvet cover: folded bed linen, same photo as bed sheets'),
    'HTL-05': (140, 'لباد مرتبة كبير - the retail mattress-pad image'),
    'HTL-06': (139, 'لباد مرتبة صغير - the retail mattress-pad image'),
    'HTL-07': (102, 'duvet: folded quilted bedding, as the retail blanket'),
    'HTL-08': (101, 'duvet: folded quilted bedding, as the retail blanket'),
    'HTL-09': (102, 'بطانية كبيرة - the retail blanket image'),
    'HTL-10': (141, 'مخدة - the retail pillow illustration'),
    'HTL-11': (133, 'غطاء مخدة - the retail pillowcase image'),
    'HTL-12': (146, 'منشفة كبيرة - the retail large-towel image'),
    'HTL-13': (147, 'منشفة وسط - the retail medium-towel image'),
    'HTL-14': (145, 'منشفة صغير - the retail small-towel image'),
    'HTL-16': (118, 'روب حمام - the retail bathrobe image'),
    'HTL-26': (106, 'بنطلون - the retail trousers image'),
    'HTL-28': (110, 'تي شيرت - the retail t-shirt image'),
    'HTL-29': (115, 'جاكيت خفيف - the retail light-jacket image'),
    'HTL-31': (136, 'فستان 1 - the retail dress illustration'),
    'HTL-32': (120, 'ستاره كبيرة - the retail curtain illustration'),
    'HTL-33': (120, 'ستاره كبيرة - the retail curtain illustration'),
    'HTL-34': (120, 'ستاره كبيرة - the retail curtain illustration'),
    'HTL-35': (121, 'سجادة صلاة - the retail prayer-rug illustration'),
    'HTL-36': (99, 'بدلة كاملة - the retail full-suit image'),
}

# No retail image depicts these, so none is assigned. Listed with what each
# actually needs, so artwork can be commissioned or generated later.
NEEDS_ARTWORK = {
    'HTL-15': ('دواسة', 'Bath Mat',
               'small rectangular bath mat, folded or flat'),
    'HTL-17': ('حلية للسرير كبير', 'Large Bed Valance',
               'pleated bed valance / bed skirt, large'),
    'HTL-18': ('حلية للسرير صغير', 'Small Bed Valance',
               'pleated bed valance / bed skirt, small'),
    'HTL-19': ('غطاء كرسي', 'Chair Cover',
               'white banquet chair cover fitted over a chair'),
    'HTL-20': ('مفرش طاولة كبير', 'Large Tablecloth',
               'white tablecloth draped over a round banquet table'),
    'HTL-21': ('مفرش طاولة صغير', 'Small Tablecloth',
               'white tablecloth on a small table'),
    'HTL-22': ('منديل طعام', 'Napkin',
               'folded white linen dinner napkin'),
    'HTL-23': ('ديكور طاولة', 'Table Runner',
               'decorative table runner across a table'),
    'HTL-24': ('حلية طاولة', 'Table Skirt',
               'pleated table skirt around a banquet table'),
    # These two have a retail product of the same name, but its image shows
    # something else entirely -- striped pyjamas and a navy suit respectively --
    # so copying it would put a visibly wrong picture on the till.
    'HTL-25': ('قميص', 'Shirt',
               'plain dress shirt; retail "قميص رجالي" image is pyjamas'),
    'HTL-27': ('صديري', 'Vest',
               'waistcoat / vest; retail "سديري" image is a full suit'),
    'HTL-30': ('جاكيت مطبخ', 'Chef Jacket',
               'white double-breasted chef jacket'),
}


def run(env):
    Template = env['product.template'].with_context(lang='en_US')
    assigned, already, missing_source, skipped = [], [], [], []

    for code, (source_id, reason) in sorted(IMAGE_SOURCES.items()):
        target = Template.search([('default_code', '=', code)], limit=1)
        if not target:
            missing_source.append('%s: no such product' % code)
            continue
        if target.image_1920:
            already.append(code)
            continue
        source = Template.browse(source_id).exists()
        if not source or not source.image_1920:
            missing_source.append('%s: source template %s has no image'
                                  % (code, source_id))
            continue
        # Copy the stored original; Odoo recomputes 1024/512/256/128 itself.
        target.image_1920 = source.image_1920
        assigned.append((code, target.name, source_id, source.name, reason))

    for code in sorted(NEEDS_ARTWORK):
        target = Template.search([('default_code', '=', code)], limit=1)
        if target and not target.image_1920:
            skipped.append(code)

    print('=' * 78)
    print('ASSIGNED %d image(s)' % len(assigned))
    print('=' * 78)
    for code, name, sid, sname, reason in assigned:
        print('  %-7s %-34s <- [%s] %-22s %s'
              % (code, name[:34], sid, sname[:22], reason.split(' - ')[0][:28]))
    if already:
        print('\nLEFT ALONE (already had an image): %s' % ', '.join(already))
    if missing_source:
        print('\nSOURCE PROBLEM: %s' % '; '.join(missing_source))
    print()
    print('=' * 78)
    print('STILL NEEDS ARTWORK: %d product(s)' % len(skipped))
    print('=' * 78)
    for code in skipped:
        ar, en, need = NEEDS_ARTWORK[code]
        print('  %-7s %-26s %-22s %s' % (code, ar, en, need))
    return assigned, skipped


if 'env' in globals():        # running inside `odoo-bin shell`
    run(env)                  # noqa: F821
    env.cr.commit()           # noqa: F821
