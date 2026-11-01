# Recording held-back requests

**Edition:** Open Source. These cases cover spec 006 ST21 "Held-back requests"
under ADR 025 and governance issue #29. When the **Held-back requests** switch
is on, Keeplane writes one record for each request personal-data detection
holds back. The record gives a reference, the time, the developer, the
project, the class the request was handled as, why it was held, and the model
it was allowed to or refused for. It never holds the prompt, other request
text or anything detection found.

[`test_held_request_records.py`](test_held_request_records.py) calls the
gateway checks over HTTP in the test process, on SQLite, with a deterministic
fake detector. HR-01 to HR-09 and HR-11 use the managed installed checks;
HR-10 and HR-12 a customer-run (`existing`) gateway's shared checks.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| HR-01 After install | With detection on and the switch untouched, send a request with personal data through the entry and final checks | The switch is off and no record is written. |
| HR-02 One record per request | Switch on. Send two held requests, each through the entry check once and the final check three times (a first try and two retries) | Both are allowed to the approved model. Exactly two records, one per request, each naming `callback-developer`, a UTC time and "Request HR-… held back as Confidential (personal data detected); project Callback; allowed to model private, approved for it", each with its own reference. Search finds them by text and by reference. No model-answer record is written while that switch is off. |
| HR-03 Refused for its model | Switch on; detection's class is Public, which the installed model isn't approved for. Send a held request | The developer is refused with "nothing was sent". One record says the request was held back as Public and refused for model private, not approved for it; nothing was sent. |
| HR-04 Clean or undecided | Send a clean request through both checks, a request for a model that isn't installed, and a request after signing out | No held-back record: a clean request isn't held, and a request refused before any decision was never held. |
| HR-05 Detection off | Switch on; turn detection off, then data classes off, and send a request with personal data | No record: nothing is held. |
| HR-06 Why it was held | Switch on; the detector finds personal data, gets no readable text, is unavailable, is too slow, fails, or gives a reason Keeplane doesn't know; and a request with an image part | Each record names the reason category only: personal data detected, request could not be read, detector unavailable, check took too long, detector failed, or not checked. |
| HR-07 Its own switch | Settings changes and model answers on, held-back requests off; then only held-back requests on; then off again | No held-back record while it is off. Turning it on changes no other switch; turning it off stops new records and keeps the earlier one. |
| HR-08 No request text or secrets | With held-back requests and model answers on, send a held request that is allowed and one that is refused, with all logging captured | No record or log line contains the prompt, the detected email address or any part of it, the developer's session, the gateway credential, the definition fingerprint or the password. |
| HR-09 A failed write keeps the hold | The record insert, or the switch read, fails while a held request is allowed to its approved model and another is refused for an unapproved one | The approved model is still allowed and the unapproved one still refused with "nothing was sent". No record is written; each failure logs one warning, "not written; the hold still applies", with only the error kind. The next held request is recorded again. |
| HR-10 Customer-run gateway | Switch on; on an `existing` gateway, send a held request to the route check and three times to the final check; then a held request for model `public`, and one naming an unknown model that looks like an email address | One record for the allowed request, from the route check only. The refused requests are recorded at the route check; the unknown model ID is shown as "a model Keeplane doesn't know" and never copied into the record. |
| HR-11 One recorder per mode | Switch on; on a managed install, send a held request to the shared route check | No record: a managed install records on its installed entry check only, so one request is never recorded twice. |
| HR-12 Only its developer, only admins | Two developers each send a held request for the same project; then the second developer and an anonymous visitor read Audit | Each record names the developer whose session sent it, by account ID and username. Neither the developer nor the anonymous visitor can read the records. |

## Known limit

Detection runs at both checks, but only the entry check records. A request
the entry check found clean but the final check held (only possible when the
detector becomes unavailable or too slow in between) is still held back, and
is not recorded.
