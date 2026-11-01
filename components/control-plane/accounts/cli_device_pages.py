"""Page context for the CLI device-code sign-in pages."""

# Django names a field's error element "<field id>_error" when the form is bound;
# the page uses the same id for a code Keeplane itself rejected.
CODE_ERROR_ID = "id_user_code_error"


def rejected_code_context(form_class, code):
    """Show the code field again, marked invalid and linked to its error."""
    form = form_class(initial={"user_code": code})
    form.fields["user_code"].widget.attrs.update(
        {"aria-invalid": "true", "aria-describedby": CODE_ERROR_ID}
    )
    return {"entry": True, "invalid": True, "form": form}
