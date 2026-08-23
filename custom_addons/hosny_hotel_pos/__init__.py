from . import models
from . import wizard


def post_init_hook(env):
    """First install only: build the structure and load the sheet once.

    Later upgrades deliberately do not come back through here, so imported
    prices that staff have since adjusted are never reset.
    """
    env['hotel.pricing.setup'].bootstrap()
