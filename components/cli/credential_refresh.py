"""Explicit one-shot pair rotation; never retry an ambiguous token exchange."""

if __package__:
    from .browser_login import exchange
    from .credential_profile import Credential, ProfileError, opened
    from .server_connection import ConnectionError, account, logout
else:
    from browser_login import exchange
    from credential_profile import Credential, ProfileError, opened
    from server_connection import ConnectionError, account, logout


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
        except ConnectionError:
            raise ConnectionError(
                "Refresh did not complete; the old local profile was retained. "
                "The server may have rotated it. Sign in again after recovery."
            ) from None
        try:
            if access == old.access_token or renewal == old.refresh_token:
                raise ProfileError("The server did not rotate the credential pair.")
            actor = account(old.issuer, access)
            if actor["id"] != old.actor_id:
                raise ProfileError("The server account changed; sign in again.")
            profile.save(
                Credential(old.issuer, old.actor_id, access, renewal, old.client_id)
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
