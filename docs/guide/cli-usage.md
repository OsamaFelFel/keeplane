# See your own usage

`keeplane usage` shows the tokens you used with each model, today and this
month, and an estimated cost (Spec 009 ST31). It shows only your own usage:
there is no option for another developer, and admins have no way to read it
either.

```sh
keeplane usage
```

```text
Your usage for today, 9 November 2026, and this month, November 2026.

Model  Period      Input tokens  Output tokens  Estimated cost
cloud  Today              2,000            500  $0.0035
       This month     1,250,000        210,000  $4.57
local  Today              1,200            300  —
       This month         1,200            300  —

Costs are estimates from each provider's list price (price list of 3 November 2026), in US dollars.
cloud: 3 requests didn't report tokens, so its totals may be low.
```

Each model you used this month has two rows. Input tokens include cached
input; output tokens include reasoning.

## What the cost means

- **A dollar amount** is an estimate: your tokens times the provider's public
  list price, from the price list shipped with your Keeplane server. The line
  under the table names that list's date. Discounts and negotiated prices are
  never applied, and cached input and reasoning tokens are priced as ordinary
  tokens. It is never a bill. Amounts under $1 show to the millionth of a
  dollar; from $1 they are rounded to the cent.
- **—** is a model your admin added from a local runner. It has no cost.
- **no list price** is a cloud model Keeplane has no price for. Its tokens
  still show.

A cloud model is priced from the moment your admin adds it. When some of a
model's tokens couldn't be priced (for example a name reused for a new model,
whose tokens earlier that hour may belong to the old one), a line says so:

```text
cloud: some of its tokens couldn't be priced, so its cost may be low.
```

## Today and this month

"Today" and "this month" follow your computer's time zone (from `TZ`, or the
system setting). If the CLI can't read it, or your Keeplane server doesn't know
the zone, it uses UTC and says so at the end of the heading:

```text
Your usage for today, 9 November 2026, and this month, November 2026 (UTC).
```

In a zone with a half- or quarter-hour offset, a day starts at the hour
nearest your local midnight.

Totals are kept for this month and last month, then deleted. There is no "last
month" view. If you haven't used a model this month, `keeplane usage` shows
the heading, no table and no estimate label, then:

```text
You haven't used any models this month.
```

## Where the numbers come from

After each `keeplane code` turn, the CLI sends your Keeplane server one report
per model the turn used: the project, the model, input and output tokens, the
number of model calls and how many came back without token counts. A report
holds no prompt, answer, file or path, and the server takes the account from
your sign-in, never from the report.

The counts come from the gateway's own answers. For one turn, `keeplane code`
starts a small relay on `127.0.0.1` and points the coding runtime at it. The
relay sends each of the runtime's requests on to your gateway unchanged, adds
no credential of its own, passes each answer straight back and reads only the
token counts in it. So every model call is counted, including the turn's last
answer and calls made by subagents. See
[Developers' computers](outbound-connections.md#developers-computers).

The relay only sends on requests that carry this turn's own Keeplane grant.
Other users and programs on the same computer can reach its port while a turn
runs, but they can't use it: any other request is refused (403), never sent to
the gateway and never counted. The relay stops when the turn ends.

Because the CLI, not the coding tool, now connects to the gateway, it checks
the gateway's HTTPS certificate with the same trust as its calls to your
Keeplane server: `SSL_CERT_FILE` and `SSL_CERT_DIR`, or the system store. See
[developers with a private CA](certificate-operations.md#renew-the-public-https-certificate).

A model call whose answer had no token counts still counts as a call, and its
tokens are never guessed. The table then says the model's totals may be low:

```text
cloud: 3 requests didn't report tokens, so its totals may be low.
```

Recording usage doesn't need the gateway: while it is down, Keeplane checks the
model against its own setup (set up in Keeplane and allowed for the project's
class), so the calls the gateway answered before it went down still count.

If a report can't be sent (the server can't be reached, or your sign-in
expired during the turn), the turn still finishes as usual and `code` adds:

```text
Keeplane couldn't record this task's usage of cloud, so `keeplane usage` may show less than you used.
```

That turn's usage is then missing: usage can undercount. A turn you cancel
(Ctrl-C), that times out, or that stops because your sign-in expired is not
reported.

## When you're signed out or your sign-in has expired

Like `models`, `keeplane usage` sends nothing when you're signed out:

```text
You're signed out of Keeplane, so nothing was sent. Run `keeplane login` to sign in.
```

When your sign-in has expired it exits 1 with:

```text
Your Keeplane sign-in has expired. Run `keeplane login` to sign in again.
```

An older Keeplane server that doesn't keep usage exits 1 with:

```text
This Keeplane server doesn't show usage yet. Ask your admin to update it.
```

How the server keeps and prices usage is in
[developer usage](../architecture/developer-usage.md); the routes are in the
[runtime catalog](runtime-catalog.md#report-and-read-your-own-usage).
