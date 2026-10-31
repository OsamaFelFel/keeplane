"""Storage failures that use cases can handle without depending on an ORM."""


class StorageUnavailable(Exception):
    pass


class GatewayRemovalFailed(Exception):
    """The gateway refused a removal; Keeplane's records were not changed."""

    def __init__(self, status, result):
        super().__init__(status)
        self.status = status
        self.result = result
