"""Authorize a current account before resolving its definition-bound provider key."""

from dataclasses import dataclass, field

from common.errors import StorageUnavailable

from .authorization import DjangoModelAuthorization
from .developer_keys import DjangoDeveloperKeyStore
from .key_validation import DjangoProviderKeyValidator
from .resolved_keys import ResolvedProviderKey


@dataclass(frozen=True)
class AuthorizedProviderKey:
    actor_id: str
    project_id: str
    model_id: str
    definition_fingerprint: str
    _credential: ResolvedProviderKey = field(repr=False)

    def for_provider(self):
        """Trusted transport only; never return this value to a developer or log it."""
        return self._credential.for_provider()


class DjangoPersonalDispatch:
    """Internal composition only; no HTTP route or gateway enrollment is enabled.

    A trusted final-destination adapter supplies its fixed model and definition
    fingerprint. It must also verify its installed routing before using the key.
    This result is one current decision, not a lease across future requests.
    """

    def __init__(self, identity, policy, gateway, directory, *, project_access):
        self.authorization = DjangoModelAuthorization(
            identity, policy, project_access=project_access
        )
        self.gateway, self.directory = gateway, directory

    def resolve(self, session_token, project_id, model_id, *, definition_fingerprint):
        if (
            not isinstance(definition_fingerprint, str)
            or len(definition_fingerprint) != 64
            or any(char not in "0123456789abcdef" for char in definition_fingerprint)
        ):
            raise StorageUnavailable("Provider key is unavailable")
        decision = self.authorization.authorize(session_token, project_id, model_id)

        def current_owner(owner):
            # The store holds the same owner lock as key writes and account
            # withdrawal. Recheck project/class/model policy before secret reads.
            current = self.authorization.authorize(session_token, project_id, model_id)
            if (
                owner is None
                or current != decision
                or current["actor_id"] != str(owner.pk)
            ):
                raise StorageUnavailable("Provider key is unavailable")

        key = DjangoDeveloperKeyStore(
            decision["actor_id"],
            self.directory,
            validate_key=DjangoProviderKeyValidator(self.gateway),
            reauthenticate=current_owner,
        ).resolve(model_id, expected_definition_fingerprint=definition_fingerprint)
        return AuthorizedProviderKey(
            **decision, definition_fingerprint=definition_fingerprint, _credential=key
        )
