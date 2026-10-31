"""What the admin reads when not every gateway copy confirms a model change.

Each answer has a short title and the error text the admin dialog shows.
"""

BAD_LIST = (
    "Keeplane can't check every gateway copy because the gateway copy list in "
    "its settings isn't valid."
)
ASK_INSTALLER = "Ask whoever installed Keeplane to fix it."


def _did(readback):
    return f"{readback.confirmed} of {readback.total} did."


def not_added(model_id, readback, undone):
    title = f"{model_id} wasn't added"
    if readback.misconfigured:
        tail = (
            "Nothing was saved."
            if undone
            else "It may still be listed in the gateway, but it gets no work."
        )
        return {"title": title, "error": f"{BAD_LIST} {tail} {ASK_INSTALLER}"}
    if undone:
        body = (
            f"Not every gateway copy confirmed it: {_did(readback)} "
            "Nothing was saved. Check the gateway and try again."
        )
    else:
        body = (
            f"Not every gateway copy confirmed it: {_did(readback)} It may still "
            "be listed in the gateway, but it gets no work. Check Models."
        )
    return {"title": title, "error": body}


def not_changed(model_id, readback):
    title = f"{model_id} wasn't changed"
    if readback.misconfigured:
        return {
            "title": title,
            "error": f"{BAD_LIST} Nothing was saved. {ASK_INSTALLER}",
        }
    return {
        "title": title,
        "error": f"Not every gateway copy confirmed the change: {_did(readback)} "
        "Nothing was saved, and its earlier setup stays. Check the gateway and "
        "try again.",
    }


def key_not_changed(model_id, readback, restored):
    title = f"{model_id} wasn't changed"
    if readback.misconfigured:
        tail = "Nothing was saved." if restored else "The model may need attention."
        return {"title": title, "error": f"{BAD_LIST} {tail} {ASK_INSTALLER}"}
    if restored:
        body = (
            f"Not every gateway copy confirmed the new key: {_did(readback)} "
            "Nothing was saved, and the earlier key stays. Check the gateway and "
            "try again."
        )
    else:
        body = (
            f"Not every gateway copy confirmed the new key: {_did(readback)} "
            "The model may need attention. Check Models."
        )
    return {"title": title, "error": body}


def removed_but_listed(model_id, readback):
    title = f"{model_id} was removed"
    if readback.misconfigured:
        return {
            "title": title,
            "error": f"Developers can't use it, but {BAD_LIST} {ASK_INSTALLER}",
        }
    listed = readback.total - readback.confirmed
    return {
        "title": title,
        "error": f"Developers can't use it, but {listed} of {readback.total} "
        "gateway copies still list it. Check the gateway.",
    }
