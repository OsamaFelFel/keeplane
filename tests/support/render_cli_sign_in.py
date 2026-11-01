"""Render every state of the CLI sign-in pages with Django's own template engine.

Prints a JSON object mapping each state name to its HTML. Used by the browser
cases in tests/browser/cli-sign-in-type.spec.ts; it needs Django only, not the
optional OAuth trial packages, and uses synthetic names.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import django
from django.conf import settings

TEMPLATES = Path(__file__).resolve().parents[2] / "components/control-plane/accounts/templates"


def render_states():
    if not settings.configured:
        settings.configure(DEBUG=False, USE_I18N=False, USE_TZ=True)
        django.setup()
    from django import forms
    from django.template import Context, Engine

    class DeviceCodeForm(forms.Form):
        # The toolkit's DeviceGrantForm has this one required text field.
        user_code = forms.CharField(required=True)

    class ConsentForm(forms.Form):
        client_id = forms.CharField(widget=forms.HiddenInput, initial="keeplane-cli")

    engine = Engine(dirs=[str(TEMPLATES)])
    request = SimpleNamespace(user=SimpleNamespace(username="browser-developer"))
    invalid = DeviceCodeForm(data={"user_code": ""})
    invalid.is_valid()
    states = {
        "consent": ("cli_consent.html", {"form": ConsentForm()}),
        "consent-error": ("cli_consent.html", {"error": True}),
        "device-entry": ("cli_device.html", {"entry": True, "form": DeviceCodeForm()}),
        "device-entry-invalid": ("cli_device.html", {"entry": True, "invalid": True, "form": invalid}),
        "device-confirm": ("cli_device.html", {"user_code": "ABCD-EFGH", "form": DeviceCodeForm()}),
        "device-allowed": ("cli_device.html", {"complete": True, "allowed": True}),
        "device-cancelled": ("cli_device.html", {"complete": True, "allowed": False}),
    }
    return {
        name: engine.get_template(f"accounts/{template}").render(Context({"request": request, **context}))
        for name, (template, context) in states.items()
    }


if __name__ == "__main__":
    json.dump(render_states(), sys.stdout)
