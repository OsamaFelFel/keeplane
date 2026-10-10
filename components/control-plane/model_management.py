"""Model registration and setup use case, independent of the HTTP transport."""

import json
import sqlite3
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from local_identity import IdentityError
from model_catalog import fingerprint
from provider_keys import (save as save_provider_key, remove as remove_provider_key,
                           from_resource as provider_key_file, is_managed as managed_provider_key)
from runner_adapter import local_runner


class ModelManagement:
    def __init__(self, catalog, data_classes, gateway, actor, gateway_mode, file_config,
                 provider_key_dir, runner_urls, cloud_base_urls, trial_key):
        self.catalog = catalog
        self.data_classes = data_classes
        self.gateway = gateway
        self._actor = actor
        self.gateway_mode = gateway_mode
        self.file_config = file_config
        self.provider_key_dir = provider_key_dir
        self.runner_urls = runner_urls
        self.cloud_base_urls = cloud_base_urls
        self.trial_key = trial_key

    def reply(self, status, body):
        return status, body

    def actor(self):
        return self._actor

    def model_fingerprint(self, model_id, resources):
        return fingerprint(model_id, resources, self.file_config)

    def gateway_model_resources(self):
        return self.gateway.resources()

    def local_runner(self, address, model=None):
        return local_runner(address, self.runner_urls, model)

    def confirm_new_model(self, model_id, expected_params):
        """Wait for management readback, then ask through the registered gateway path."""
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            status, listing = self.gateway.request("/v1/models", timeout=5)
            resource_status, resources = self.gateway.request("/api/config/resources/llm.model", timeout=5)
            if status == 200 and resource_status == 200:
                raw = resources.get("resources", [])
                entry = next((item.get("value", {}) for item in raw if item.get("id") == model_id), {})
                if model_id in {item.get("id") for item in listing.get("data", [])} and \
                        entry.get("params") == expected_params:
                    model_revision = self.model_fingerprint(model_id, raw)
                    if model_revision:
                        for delay in (0, 0.2, 0.4, 0.8, 1.6):
                            if delay:
                                time.sleep(delay)
                            answer_status, answer = self.gateway.request("/v1/chat/completions", {
                                "model": model_id, "messages": [{"role": "user", "content": "Reply OK."}],
                                "max_tokens": 1}, timeout=30, connection_retries=3)
                            if answer_status == 200 and answer.get("choices") and \
                                    answer["choices"][0].get("message", {}).get("content"):
                                return model_revision
                            # A different replica may not have applied the registration yet.
                            # Only this explicit not-found response is safe to retry.
                            if answer_status != 404 or not isinstance(answer.get("error"), dict) or \
                                    answer["error"].get("code") != "model_not_found":
                                break
                        return None
            if time.monotonic() < deadline:
                time.sleep(0.3)
        return None

    def undo_new_model(self, model_id, expected_params):
        """Remove only the model definition this request created when it can be verified."""
        status, resources = self.gateway.request("/api/config/resources/llm.model", timeout=5)
        if status != 200:
            return False
        entry = next((item.get("value", {}) for item in resources.get("resources", [])
                      if item.get("id") == model_id), {})
        if entry.get("params") != expected_params:
            return False
        status, _ = self.gateway.request("/api/config/resources/llm.model/" + model_id, method="DELETE")
        return status == 200

    def undo_cloud_model(self, model_id, expected_resource):
        """Remove a failed cloud registration only if its complete definition is unchanged."""
        status, resources = self.gateway_model_resources()
        if status != 200:
            return False
        entry = next((item.get("value", {}) for item in resources.get("resources", [])
                      if item.get("id") == model_id), {})
        if not entry:
            return True
        if entry != expected_resource:
            return False
        status, _ = self.gateway.request("/api/config/resources/llm.model/" + model_id, method="DELETE")
        return status == 200

    def confirm_cloud_model(self, model_id, expected_resource, retry_refused=False):
        """Verify management readback and one answer through the chosen gateway."""
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            status, listing = self.gateway.request("/v1/models", timeout=5)
            resource_status, resources = self.gateway_model_resources()
            if status == 200 and resource_status == 200:
                raw = resources.get("resources", [])
                entry = next((item.get("value", {}) for item in raw if item.get("id") == model_id), {})
                if model_id in {item.get("id") for item in listing.get("data", [])} and \
                        entry == expected_resource:
                    revision = self.model_fingerprint(model_id, raw)
                    if not revision:
                        return None, "The gateway didn't register it."
                    for delay in (0, 0.2, 0.4, 0.8, 1.6, 3.2):
                        if delay:
                            time.sleep(delay)
                        answer_status, answer = self.gateway.request("/v1/chat/completions", {
                            "model": model_id,
                            "messages": [{"role": "user", "content": "Reply OK."}],
                            "max_tokens": 1}, timeout=30, connection_retries=3)
                        if answer_status == 200 and answer.get("choices") and \
                                answer["choices"][0].get("message", {}).get("content"):
                            return revision, None
                        if answer_status in (401, 403):
                            if retry_refused and delay != 3.2:
                                continue
                            return None, "The provider refused the key."
                        if answer_status == 404 and isinstance(answer.get("error"), dict) and \
                                answer["error"].get("code") == "model_not_found":
                            continue
                        return None, "The provider didn't answer."
                    return None, "The gateway didn't register it."
            time.sleep(0.3)
        return None, "The gateway didn't register it."

    def replace_shared_key(self, model_id, resource, previous, classes, replacement):
        if self.gateway_mode == "existing":
            return self.reply(422, {"error": "Shared provider keys need a supported delivery path to the customer-run gateway"})
        if not previous["owned_by_keeplane"] or resource.get("provider") not in ("openAI", "anthropic"):
            return self.reply(400, {"error": "This trial can replace keys only for cloud models Keeplane added"})
        old_path = provider_key_file(resource)
        if not managed_provider_key(self.provider_key_dir, old_path):
            return self.reply(400, {"error": "This model's shared key is not managed by Keeplane"})
        try:
            new_path = save_provider_key(self.provider_key_dir, replacement)
        except OSError:
            return self.reply(503, {"error": "Shared provider key storage is unavailable"})
        updated = json.loads(json.dumps(resource))
        updated["auth"]["key"]["value"] = {"file": new_path}
        resource_path = "/api/config/resources/llm.model/" + model_id
        check_name = "keeplane-keycheck-" + uuid.uuid4().hex
        check_resource = json.loads(json.dumps(updated))
        check_resource["name"] = check_name

        # A model already in service may still answer with its old route just
        # after a management update. A unique model proves the new key first.
        check_status, _ = self.gateway.request("/api/config/resources/llm.model",
                                  {"resources": [{"value": check_resource}]}, "PUT")
        checked, _ = self.confirm_cloud_model(check_name, check_resource) if check_status == 200 else (None, None)
        check_removed = self.undo_cloud_model(check_name, check_resource)
        if checked is None or not check_removed:
            if check_removed:
                remove_provider_key(self.provider_key_dir, new_path)
            return self.reply(503, {"error": "The replacement key didn't answer through the gateway. " +
                              ("The previous key is still active." if check_removed else
                               "A verification model may need cleanup; check Models.")})

        def restore_previous():
            status, resources = self.gateway_model_resources()
            if status != 200:
                return False
            current = next((item.get("value", {}) for item in resources.get("resources", [])
                            if item.get("id") == model_id), {})
            if current == updated:
                status, _ = self.gateway.request(resource_path, {"value": resource}, "PUT")
                if status != 200:
                    return False
            elif current != resource:
                return False
            revision, _ = self.confirm_cloud_model(model_id, resource, retry_refused=True)
            if revision is None:
                return False
            try:
                self.catalog.approve(model_id, previous["approved_classes"], revision, self.actor(),
                                owned_by_keeplane=True, key_choice="shared")
            except (ValueError, IdentityError, sqlite3.Error):
                return False
            return remove_provider_key(self.provider_key_dir, new_path)

        status, _ = self.gateway.request(resource_path, {"value": updated}, "PUT")
        revision, _ = self.confirm_cloud_model(model_id, updated, retry_refused=True) if status == 200 else (None, None)
        if revision is None:
            restored = restore_previous()
            return self.reply(503, {"error": "The replacement key didn't work. " +
                              ("The previous key is still active." if restored else
                               "The model may need admin attention; check Models.")})
        try:
            approval = self.catalog.approve(model_id, classes, revision, self.actor(),
                                       owned_by_keeplane=True, key_choice="shared")
        except (ValueError, IdentityError, sqlite3.Error):
            restored = restore_previous()
            return self.reply(503, {"error": "Keeplane couldn't save the change. " +
                              ("The previous key is still active." if restored else
                               "The model may need admin attention; check Models.")})
        if not remove_provider_key(self.provider_key_dir, old_path):
            return self.reply(503, {"error": "New key saved, but the previous key file needs cleanup"})
        return self.reply(200, approval)

    def add_cloud_model(self, body, name, model, classes):
        if not self.catalog:
            return self.reply(403, {"error": "Sign in as an admin to add a cloud model"})
        source = body.get("source")
        provider = {"openai": "openAI", "anthropic": "anthropic"}[source]
        key_choice = body.get("key_choice")
        if key_choice not in ("shared", "none"):
            return self.reply(400, {"error": "Choose a supported provider key option"})
        if key_choice == "shared":
            if self.gateway_mode == "existing":
                return self.reply(422, {"error": "Shared provider keys need a supported delivery path to the customer-run gateway"})
            shared_key = body.get("shared_key")
            if not isinstance(shared_key, str) or not 12 <= len(shared_key) <= 512 or \
                    "\n" in shared_key or "\r" in shared_key:
                return self.reply(400, {"error": "Enter a valid shared provider key"})

        status, listing = self.gateway.request("/v1/models", timeout=10)
        if status != 200:
            return self.reply(status, listing)
        resource_status, resources = self.gateway_model_resources()
        if resource_status != 200:
            return self.reply(resource_status, resources)
        if name in {item.get("id") for item in listing.get("data", [])} or any(
            item.get("value", {}).get("provider") == provider and
            item.get("value", {}).get("params", {}).get("model") == model
            for item in resources.get("resources", [])):
            label = "OpenAI" if source == "openai" else "Anthropic"
            return self.reply(409, {"error": f"{model} from {label} is already added."})

        key_path = None
        if key_choice == "shared":
            try:
                key_path = save_provider_key(self.provider_key_dir, shared_key)
            except OSError:
                return self.reply(503, {"error": "Shared provider key storage is unavailable"})
        params = {"model": model}
        if self.cloud_base_urls[source]:
            params["baseUrl"] = self.cloud_base_urls[source]
        resource = {"name": name, "provider": provider, "params": params}
        if key_path:
            resource["auth"] = {"key": {"value": {"file": key_path}}}
        status, _ = self.gateway.request("/api/config/resources/llm.model",
                            {"resources": [{"value": resource}]}, "PUT")
        if status != 200:
            removed = self.undo_cloud_model(name, resource)
            if key_path and removed:
                remove_provider_key(self.provider_key_dir, key_path)
            return self.reply(503, {"error": "The gateway didn't confirm registration. " +
                              ("Nothing was saved." if removed else
                               "Its entry may remain without approval; check Models.")})
        revision, reason = self.confirm_cloud_model(name, resource)
        if revision is None:
            removed = self.undo_cloud_model(name, resource)
            if key_path and removed:
                remove_provider_key(self.provider_key_dir, key_path)
            suffix = " Nothing was saved." if removed else \
                " Its gateway entry may remain without a working key; check Models."
            if reason == "The provider refused the key.":
                reason = f"{'OpenAI' if source == 'openai' else 'Anthropic'} refused the key."
            elif reason == "The provider didn't answer.":
                reason = f"{'OpenAI' if source == 'openai' else 'Anthropic'} didn't answer."
            return self.reply(503, {"error": reason + suffix})
        try:
            approval = self.catalog.approve(name, classes, revision, self.actor(),
                                       owned_by_keeplane=True, key_choice=key_choice)
        except (ValueError, IdentityError, sqlite3.Error):
            removed = self.undo_cloud_model(name, resource)
            if key_path and removed:
                remove_provider_key(self.provider_key_dir, key_path)
            return self.reply(503, {"error": "Keeplane couldn't save model approval. " +
                              ("Registration was removed." if removed else
                               "The model may remain in the gateway without Keeplane approval.")})
        return self.reply(200, {"name": name, "key_choice": approval["key_choice"],
                                "approved_classes": approval["approved_classes"]})

    def setup(self, model_id, body):
        choice = body.get("key_choice")
        previous = self.catalog.get(model_id)
        if choice not in ("none", "shared") or (choice == "shared" and
                                                  (not previous or previous["key_choice"] != "shared")):
            return self.reply(400, {"error": "Choose a supported provider key option"})
        replacement = body.get("replace_shared_key", "")
        if not isinstance(replacement, str) or (replacement and
                (choice != "shared" or not 12 <= len(replacement) <= 512 or
                 "\n" in replacement or "\r" in replacement)):
            return self.reply(400, {"error": "Enter a valid replacement shared key"})
        try:
            classes_on = self.data_classes.enabled()
            # Editing a key while classes are off must not erase approvals
            # that will apply if the admin turns the mode on again.
            classes = body.get("approved_classes", []) if classes_on else \
                (previous["approved_classes"] if previous else [])
            # Validate before making a model call or changing storage.
            known_classes = {item["name"] for item in self.data_classes.list()}
            if not isinstance(classes, list) or \
                    any(not isinstance(item, str) or item not in known_classes for item in classes) or \
                    len(classes) != len(set(classes)):
                raise ValueError("Choose valid data classes")
        except ValueError as error:
            return self.reply(400, {"error": str(error)})
        except sqlite3.Error:
            return self.reply(503, {"error": "Keeplane settings storage is unavailable"})
        status, listing = self.gateway.request("/v1/models", timeout=10)
        if status != 200:
            return self.reply(status, listing)
        if model_id not in {item.get("id") for item in listing.get("data", [])}:
            return self.reply(404, {"error": "Model not found in the gateway"})
        resource_status, resource_result = self.gateway_model_resources()
        if resource_status != 200:
            return self.reply(resource_status, resource_result)
        raw_resources = resource_result.get("resources", [])
        resource = next((item.get("value", {}) for item in raw_resources
                         if item.get("id") == model_id), {})
        if choice == "none" and resource.get("auth"):
            return self.reply(400, {"error": "This model has a provider key in the gateway"})
        if choice == "shared" and not managed_provider_key(
                self.provider_key_dir, provider_key_file(resource)):
            return self.reply(400, {"error": "This model's shared key is not managed by Keeplane"})
        current_fingerprint = self.model_fingerprint(model_id, raw_resources)
        if not current_fingerprint:
            return self.reply(503, {"error": "The gateway model definition could not be verified"})
        if choice == "shared" and previous["gateway_fingerprint"] != current_fingerprint:
            return self.reply(409, {"error": "This model changed in the gateway and must be set up again"})
        if replacement:
            return self.replace_shared_key(model_id, resource, previous, classes, replacement)
        answer_status, answer = self.gateway.request("/v1/chat/completions", {
            "model": model_id, "messages": [{"role": "user", "content": "Reply OK."}],
            "max_tokens": 1}, timeout=30)
        if answer_status != 200 or not answer.get("choices"):
            return self.reply(503, {"error": "The model didn't answer. Nothing was saved."})
        try:
            # A definition replaced outside Keeplane loses its provenance.
            still_owned = bool(previous and previous["owned_by_keeplane"] and
                               previous["gateway_fingerprint"] == current_fingerprint)
            return self.reply(200, self.catalog.approve(model_id, classes, current_fingerprint,
                                                   self.actor(), owned_by_keeplane=still_owned,
                                                   key_choice=choice))
        except ValueError as error:
            return self.reply(400, {"error": str(error)})
        except IdentityError as error:
            return self.reply(error.status, {"error": error.message})
        except sqlite3.Error:
            return self.reply(503, {"error": "Keeplane settings storage is unavailable"})

    def add(self, body):
        name = body.get("name", "")
        model = body.get("model", "")
        source = body.get("source", "fixture")
        if not isinstance(name, str) or not name or len(name) > 80 or not all(c.isalnum() or c in "-_.:" for c in name):
            return self.reply(400, {"error": "Model name must use letters, numbers, dots, dashes, underscores or colons"})
        if not isinstance(model, str) or not model or len(model) > 100:
            return self.reply(400, {"error": "Enter an upstream model ID"})
        try:
            classes = (body.get("approved_classes", []) if self.data_classes.enabled() else []) if self.catalog else None
            if classes is not None:
                known_classes = {item["name"] for item in self.data_classes.list()}
        except sqlite3.Error:
            return self.reply(503, {"error": "Keeplane settings storage is unavailable"})
        if classes is not None:
            if not isinstance(classes, list) or \
                    any(not isinstance(item, str) or item not in known_classes for item in classes) or \
                    len(classes) != len(set(classes)):
                return self.reply(400, {"error": "Choose valid data classes"})
        if source in self.cloud_base_urls:
            return self.add_cloud_model(body, name, model, classes)
        sources = {"fixture": "http://model:18080/v1", "qwen": "http://qwen:8080/v1",
                   "guarded": "http://guarded-provider:18081/v1"}
        if source == "runner":
            address = body.get("address", "")
            checked_status, checked = self.local_runner(address, model)
            if checked_status != 200:
                return self.reply(checked_status, checked)
            sources["runner"] = address.rstrip("/") + "/v1"
        if source not in sources:
            return self.reply(400, {"error": "Choose a supported local source"})
        if source in ("qwen", "guarded"):
            try:
                with urlopen("http://qwen:8080/health", timeout=10) as response:
                    if response.status != 200:
                        raise URLError("Qwen is still loading")
            except (HTTPError, URLError, TimeoutError):
                return self.reply(503, {"error": "The local Qwen runner is not ready"})
        if source == "guarded":
            if not self.trial_key:
                return self.reply(503, {"error": "The disposable test key is not configured"})
            try:
                with urlopen("http://guarded-provider:18081/health", timeout=2) as response:
                    if response.status != 200:
                        raise URLError("Guarded endpoint is still loading")
            except (HTTPError, URLError, TimeoutError):
                return self.reply(503, {"error": "The guarded endpoint is not ready"})
        listed_status, listed = self.gateway.request("/v1/models", timeout=10)
        if listed_status != 200:
            return self.reply(listed_status, listed)
        if name in {item.get("id") for item in listed.get("data", [])}:
            resource_status, resource_result = self.gateway_model_resources()
            if resource_status != 200:
                return self.reply(resource_status, resource_result)
            existing = next((item.get("value", {})
                             for item in resource_result.get("resources", []) if item.get("id") == name), None)
            if name == "local-fixture":
                existing = {"params": {"model": "mock-local", "baseUrl": sources["fixture"]}}
            expected_auth = {"key": {"value": self.trial_key}} if source == "guarded" else None
            if existing and existing.get("params") == {"model": model, "baseUrl": sources[source]} \
                    and (source != "guarded" or existing.get("auth") == expected_auth):
                return self.reply(200, {"name": name, "existing": True})
            return self.reply(409, {"error": "A model with this name is already registered"})
        # External endpoints and credentials need account and policy controls.
        resource = {"name": name, "provider": {"custom": {"formats": [{"type": "completions"}]}},
                    "params": {"model": model, "baseUrl": sources[source]}}
        if source == "guarded":
            resource["auth"] = {"key": {"value": self.trial_key}}
        status, result = self.gateway.request("/api/config/resources/llm.model", {"resources": [{"value": resource}]}, "PUT")
        if status != 200:
            if classes is not None:
                if self.undo_new_model(name, resource["params"]):
                    return self.reply(503, {"error": "The gateway did not confirm registration. A matching definition was removed."})
                if status >= 500:
                    return self.reply(503, {"error": "The gateway did not confirm registration. The model may remain in the gateway without Keeplane approval; check Models."})
            return self.reply(status, result)
        if classes is None:
            return self.reply(200, {"name": name})
        params = resource["params"]
        model_revision = self.confirm_new_model(name, params)
        if model_revision is None:
            removed = self.undo_new_model(name, params)
            return self.reply(503, {"error": "The model did not answer through the gateway. " +
                              ("Registration was removed." if removed else
                               "It may remain in the gateway without Keeplane approval; check Models.")})
        try:
            approval = self.catalog.approve(name, classes, model_revision, self.actor(),
                                       owned_by_keeplane=True)
        except (ValueError, IdentityError, sqlite3.Error):
            removed = self.undo_new_model(name, params)
            return self.reply(503, {"error": "Keeplane could not save the model approval. " +
                              ("Registration was removed." if removed else
                               "It may remain in the gateway without Keeplane approval; check Models.")})
        return self.reply(200, {"name": name, "approved_classes": approval["approved_classes"]})
