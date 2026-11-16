---
name: awg-checkout-recipe
description: Level 3 of AWG site testing. Write a site recipe (the clicks from product page to card form) and run a recorded checkout through the Agent Web Gateway with the session's card, stopping before the order unless a human approved a purchase with a maximum total. Use for demos and end-to-end proof on a specific site.
---

# Recorded checkout through the gateway

## Steps

1. **Check the prerequisites.** The site should be `reachable` in a probe. If its PSP uses client-side encryption, it also needs an applied adapter (skill `awg-adapter-authoring`), with its id set as `adapter:` on the site.
2. **Write the recipe.** Copy `recipes/_template.py` to `recipes/<site-id>.py` and set `recipe:` on the site. Implement `to_payment(run)`, which runs from the first URL until the card fields are visible. Use `recipes/hm_us.py` as the worked example.
   - Use `run.goto`, `run.caption("...")` (captions appear in the video), `run.browse()` (bot-sensor warm-up), and `run.retry_post("<url part>", click)` for cart, email and checkout POSTs that a bot wall may reject.
   - Use roles and labels (`page.get_by_role`, `get_by_label`). Read shopper details from `run.site.contact` (`sites.yaml`), never from the recipe.
   - For the PSP's frames, use `run.wait_frames(host_part, selector, count)`. For Adyen, `fill_card` defaults to `run.fill_adyen_card(expiry)`.
   - Set `CAPTURE_KEYS` (Adyen: `["adyen_public_key", "adyen_generationtime"]`) and `CHECKOUT_POST` (the encrypt binding's path).
   - Implement `order_total(run)` (a Decimal), `place_order(run)` (return the button, don't click it) and `confirmed(run)`.
3. **Iterate safely** with `uv run awg-sitecheck probe <site> --deep` until the verdict says `payment-form-ok`. Then run `uv run awg-sitecheck purchase <site>`. This records the whole run with stand-ins typed, and stops at the place-order button.
4. **Purchase only with explicit approval.** A human must approve the item and a maximum total in writing. Then run:
   ```sh
   uv run awg-sitecheck purchase <site> --purchase --max-total 30.00
   ```
   The runner refuses if the shown total is above the maximum, and never retries after the order request was sent. If 3-D Secure or a CAPTCHA appears, a human completes it in the browser window. You do not.
5. **Report.** Give:
   - the order or confirmation id, from `final_url` or the page;
   - the total;
   - the video path;
   - `session_counters` (`reveal_count` > 0 proves the gateway revealed the card);
   - the card's last 4 digits on the confirmation page, which should be the real card's, not the stand-in's.

## Rules

- **Card data:** never type real card data and never print revealed values. The card file holds aliases only.
- **No retry loops:** don't retry a purchase run after `submitted: true`. Check the site's order history first.
- **Fresh emails when blocked:** use a fresh contact email if the site starts rejecting its email lookup (403 on `userExistence`-style calls).
- **Respect the sites:** keep runs few and spaced. Repeated runs train bot walls against the egress IPs.
