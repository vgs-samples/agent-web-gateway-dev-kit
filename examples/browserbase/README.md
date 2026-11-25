# Browserbase example

[`payment_flow.py`](payment_flow.py) pays a vendor from a [Browserbase](https://www.browserbase.com) browser with a reveal session's stand-ins. It starts the browser on the session, opens the vendor's payment page, types the stand-ins into the card fields, and submits only when you pass `--submit`. [docs/browserbase.md](../../docs/browserbase.md) explains the pieces.

## Run it

Create a session for the vendor's host. Add the payment provider's host when the form posts the card there:

```sh
./awg session <the vendor's host>[,<payment provider host>]
```

Fill the payment form and stop:

```sh
export BROWSERBASE_API_KEY=…
uv run --with playwright==1.49.0 examples/browserbase/payment_flow.py https://<the vendor's payment page>/
```

Submit the payment as well, once you have approved that payment and its amount:

```sh
uv run --with playwright==1.49.0 examples/browserbase/payment_flow.py https://<the vendor's payment page>/ --submit
```

The script prints Browserbase's session ID and a live view link. Watch the run there, or afterwards in Browserbase's session replay. A person completes any 3-D Secure challenge or CAPTCHA in the live view.

## Where the card is

| | Holds |
|---|---|
| The script and Browserbase's browser | The session's stand-ins: a card-shaped number and a security code that work only in this session |
| VGS | The card. It replaces the stand-ins after the request leaves the browser, and only on the way to an allowed host or a trusted destination |
| The vendor or its payment provider | The card |

To see that for a run, compare the number typed in Browserbase's session replay with the card: the replay shows the stand-in. The session's reveal count, in the Control Panel or from `GET /reveal-sessions/{id}`, goes up when VGS releases the card.

A provider that encrypts the card fields in the browser needs an [adapter](../adapters/README.md); the stand-ins are then inside the ciphertext, where the Default adapter cannot find them.

## Fields

The script finds the card number, expiry and security code fields by their `autocomplete` attributes and common names, in the page and its frames. When a page differs, name them with CSS selectors:

```sh
uv run --with playwright==1.49.0 examples/browserbase/payment_flow.py https://<the vendor's payment page>/ \
    --number-field '#card' --expiry-field '#exp' --cvc-field '#code' --submit-button '#pay'
```

## Status

Not yet run against Browserbase or a vendor's page. The request it builds is covered by `tests/test_browserbase_example.py`.

Use Sandbox and the public test card only. The session's proxy details and stand-ins go to Browserbase.
