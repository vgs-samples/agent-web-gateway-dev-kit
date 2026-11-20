"""Site recipes: the site-specific clicks, in a small Python file per site (see recipes/_template.py).

A recipe module defines:

  to_payment(run)      required. From the first URL to the moment the card form is on screen (cart, checkout,
                       contact, addresses, delivery, payment method).
  fill_card(run)       optional. Type the session's stand-ins. Default: Adyen Secured Fields (run.fill_adyen_card).
  order_total(run)     optional. The total shown before placing the order, as a Decimal.
  place_order(run)     optional. Return the locator of the button that places the order.
  confirmed(run)       optional. True once the confirmation page shows (default: URL contains "confirm").
  CHECKOUT_POST        optional. A substring of the checkout request the encrypt binding acts on.
  CAPTURE_KEYS         optional. Session values the capture function must have stored before the card is typed,
                       e.g. ["adyen_public_key", "adyen_generationtime"].
"""
import importlib.util
from pathlib import Path


def load(path):
    path = Path(path)
    spec = importlib.util.spec_from_file_location(f"awg_recipe_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "to_payment"):
        raise SystemExit(f"recipe {path} has no to_payment(run)")
    return mod
