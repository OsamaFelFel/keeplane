"""Explicit one-shot pair rotation; never retry an ambiguous token exchange."""

if __package__:
    from .browser_login import AnswerCutOff, ServerUnavailable, exchange
    from .credential_profile import Credential, ProfileError, opened
    from .server_connection import ConnectionError, SignInExpired, logout, session
else:
    from browser_login import AnswerCutOff, ServerUnavailable, exchange
    from credential_profile import Credential, ProfileError, opened
    from server_connection import ConnectionError, SignInExpired, logout, session

# 009-15, wording decided by the associate product owner: the refresh never
# reached Keeplane (or Keeplane answered that it is unavailable), so nothing
# was rotated and the saved sign-in still works.
UNAVAILABLE = (
    "Keeplane isn't available right now, so your sign-in wasn't refreshed. "
    "It's kept as it was. Run `keeplane refresh` again in a few minutes."
)
# The refresh reached Keeplane but its answer was cut off: Keeplane may have
# rotated the pair, and a retry with the old one then ends the sign-in.
CUT_OFF = (
    "Keeplane's answer was cut off, so it isn't clear whether your sign-in was "
    "refreshed. Run `keeplane refresh` again in a few minutes. If it says your "
    "sign-in has expired, run `keeplane login` to sign in again."
)


def refresh(path):
    with opened(path) as profile:
        old = profile.load()
        try:
            access, renewal = exchange(
                old.issuer,
                {
                    "grant_type": "refresh_token",
                    "client_id": old.client_id,
                    "refresh_token": old.refresh_token,
                },
            )
        except AnswerCutOff:
            raise ConnectionError(CUT_OFF) from None
        except ServerUnavailable:
            raise ConnectionError(UNAVAILABLE) from None
        except ConnectionError as error:
            if error.status in (400, 401):
                # The server no longer accepts this pair: it expired, was
                # withdrawn, or was used once already (the whole sign-in is
                # then withdrawn). Only a new sign-in helps.
                raise SignInExpired() from None
            raise ConnectionError(
                "Refresh did not complete; the old local profile was retained. "
                "The server may have rotated it. Sign in again after recovery."
            ) from None
        try:
            if access == old.access_token or renewal == old.refresh_token:
                raise ProfileError("The server did not rotate the credential pair.")
            actor, gateway = session(old.issuer, access)
            if actor["id"] != old.actor_id:
                raise ProfileError("The server account changed; sign in again.")
            # The server's current gateway address replaces the saved one.
            profile.save(
                Credential(
                    old.issuer, old.actor_id, access, renewal, old.client_id, gateway
                )
            )
        except BaseException:
            try:
                logout(old.issuer, access)
            except ConnectionError as error:
                if error.status != 401:
                    raise ConnectionError(
                        "Refresh was not saved reliably; new-pair revocation "
                        "could not be confirmed."
                    ) from None
            raise
    return "Keeplane credential refreshed."
