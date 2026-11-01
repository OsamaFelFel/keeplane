# Try data classes in the protected local preview

Start the [account preview](accounts-local.md), sign in at
[Data classes](http://127.0.0.1:3000/app/data-classes). A new installation starts
with data classes off. Turn on **Use data classes** to create the starter
Public, Internal and Confidential classes. You can add a
class, rename it, and choose from models already set up in Keeplane. **Edit**
also changes the model list. Removing a class asks for confirmation because
its model approvals will change; if it was a model's only approved class, the
model stays set up with no class approval. A class assigned to a project cannot
be removed. Turning classes off hides the class fields in Models and routing
and retains the definitions and approvals for later use.

The local preview stores classes and model approvals in the same persistent
Docker volume. Restarting the protected app keeps both. The Models and routing
setup dialog reads the current class list, including classes you add or rename.
The class list counts only models whose current gateway definition still
matches their Keeplane approval. When a gateway model changes, it disappears
from the effective class list until an admin sets it up again; the admin cannot
add that stale model to another class.

Run the [plain-English cases](../../tests/e2e/data-classes-cases.md):

```sh
.venv/bin/python -m pytest tests/e2e/test_data_classes.py -m live
.venv/bin/python -m pytest tests/integration/test_data_classes_store.py
```

The latest live suite records [HTTP evidence](https://github.com/OsamaFelFel/keeplane/blob/de0aba5f8052fbbec55a2060309812812f09588e/tests/e2e/runs/2026-10-10-optional-data-classes-full-final.json).
It creates and removes one trial class and one trial approval. It requires the
`local-fixture` model to be present and unapproved before it starts, so it
will refuse to overwrite your own approval. The isolated database suite checks
the project-in-use rule.

Assign a class to a project in [Projects](projects.md); that page also explains
how the class limits which models get the project's tasks. The
Docker model preview at port 3000 uses this same protected account session.

## Detect personal data in requests

Detection is off until you turn it on, and works only while data classes are
on. It first needs to be installed (below); until then the switch can't be
turned on and the page says "Personal-data detection isn't installed. Install
it, then turn this on."

Under **Personal data in requests** on Data classes, turn on **Detect personal
data in requests** and choose a class under **Handle it as** (Confidential
unless you change it). From then on, a request that carries personal data is
handled as that class, whatever its project: it can go only to models approved
for that class. If its project has a class too, the model must be approved for
both, so detection never loosens a project's own limit. Turning detection off
changes no route. Once detection has been set up, its class can't be removed, even
while detection is off: choose another class under **Handle it as** first. With the Audit
**Settings changes** switch on, each change is recorded, for example "Turned
personal-data detection on; detected requests handled as Confidential" or
"Changed the class for detected requests: Confidential to Internal".

What it finds, in English only: names, addresses, emails, phone numbers and
payment card numbers. Names and places inside code, stack traces, package
paths and time zones are ignored, as are common library and algorithm names
such as Kafka or Dijkstra. It is not perfect: on Keeplane's test sets it misses
about 1 in 11 requests with personal data and holds about 1 in 17 clean
requests.

A request is also handled as the chosen class when Keeplane can't check it:
the detector is down, still starting, fails, or can't finish within 200 ms.
**Long requests may be held for this reason alone**, such as a pasted file or
a long log; on a typical two-core server that starts at about 4 000
characters, and every request over 1 MiB is held without a check. Requests
with images or other parts that aren't text can't be checked and are held too.
If the detector is removed after detection was turned on, every request is held
until you turn detection off. When a held request asks for a model that isn't
approved for the class, nothing is sent and the developer sees:

```text
This request is handled as Confidential and coder isn't approved for it, so
nothing was sent. Run it with a model approved for Confidential, or ask your
admin to approve one.
```

Keeplane doesn't switch the model itself.

Request text is checked inside Keeplane only. It is never sent to another
service and never stored or logged.

### Install detection

1. Build the app from the `detection` image target, which adds the detector
   and its language model (about 750 MiB more image and about 750 MiB more app
   memory):

   ```sh
   docker build -f components/control-plane/Dockerfile --target detection \
     -t keeplane-app:detection .
   ```

2. Set `KEEPLANE_PERSONAL_DATA_DETECTION=1` for the app, then install the
   managed runtime again so the gateway's checks send each request's messages
   to Keeplane. A customer-run gateway must add the messages to its own checks;
   see [gateway modes](gateway-configuration.md#keeplanes-checks-on-a-customer-run-gateway).

Without this setting the gateway's checks carry only the project and model, as
they always have, and detection can't be turned on. Licences, notices and the
source offer for the detector are in
[the detection notices](../../components/control-plane/licenses/personal-data-detection.md).
Held requests are not yet recorded in Audit.
