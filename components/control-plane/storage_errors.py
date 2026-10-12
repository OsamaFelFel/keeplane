"""Storage failures that use cases can handle without depending on an ORM."""


class StorageUnavailable(Exception):
    pass
