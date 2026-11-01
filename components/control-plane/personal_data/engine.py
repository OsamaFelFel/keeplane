"""The bundled detector: Presidio Analyzer with a local spaCy language model.

Settings are the ones measured for the release-1 bar: Presidio's default
recognisers and spaCy label mapping for names (PERSON) and places (LOCATION,
reported as ADDRESS), emails, phones and payment cards, no score threshold,
then Keeplane's code-aware filter and card and phone rules.

Nothing here downloads anything. The model must already be installed as a
Python package (``en_core_web_lg``) or be a directory on disk; otherwise the
detector is unavailable and every request is held. Presidio's email check
uses a public-suffix list, which is read from the copy bundled with
tldextract, never fetched.
"""

from pathlib import Path

PRESIDIO_MAP = {
    "PERSON": "PERSON",
    "LOCATION": "ADDRESS",
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "PHONE",
    "CREDIT_CARD": "CARD",
}

# Presidio's documented default mapping from spaCy labels (conf/default.yaml).
NER_MAPPING = {
    "PER": "PERSON", "PERSON": "PERSON", "NORP": "NRP", "FAC": "LOCATION",
    "LOC": "LOCATION", "GPE": "LOCATION", "LOCATION": "LOCATION",
    "ORG": "ORGANIZATION", "ORGANIZATION": "ORGANIZATION", "DATE": "DATE_TIME",
    "TIME": "DATE_TIME",
}
NER_IGNORE = ["ORGANIZATION", "CARDINAL", "EVENT", "LANGUAGE", "LAW", "MONEY",
              "ORDINAL", "PERCENT", "PRODUCT", "QUANTITY", "WORK_OF_ART"]


class DetectorUnavailable(Exception):
    """The detector or its model cannot be loaded here."""


def _offline_suffixes():
    """Make Presidio's email check use tldextract's bundled list only."""
    import tldextract
    from presidio_analyzer.predefined_recognizers.generic import email_recognizer

    extractor = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)

    class Offline:
        extract = staticmethod(extractor)

    email_recognizer.tldextract = Offline


class PresidioDetector:
    """Find personal data in one piece of text; returns types and offsets only."""

    def __init__(self, model):
        if not isinstance(model, str) or not model:
            raise DetectorUnavailable("Configure the detection model")
        try:
            import spacy
            from presidio_analyzer import AnalyzerEngine
            from presidio_analyzer.nlp_engine import NlpEngineProvider
        except ImportError:
            raise DetectorUnavailable("The detector is not installed") from None
        # Presidio downloads a missing model; never let it reach the network.
        if not (spacy.util.is_package(model) or Path(model).is_dir()):
            raise DetectorUnavailable("The detection model is not installed")
        _offline_suffixes()
        conf = {
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": model}],
            "ner_model_configuration": {
                "model_to_presidio_entity_mapping": dict(NER_MAPPING),
                "low_confidence_score_multiplier": 0.4,
                "low_score_entity_names": [],
                "labels_to_ignore": list(NER_IGNORE),
            },
        }
        nlp = NlpEngineProvider(nlp_configuration=conf).create_engine()
        self.engine = AnalyzerEngine(nlp_engine=nlp, supported_languages=["en"])
        self.entities = list(PRESIDIO_MAP)
        self.find("warm up the pipeline")

    def find(self, text):
        return [
            {"type": PRESIDIO_MAP[r.entity_type], "start": r.start, "end": r.end}
            for r in self.engine.analyze(
                text=text, language="en", entities=self.entities, score_threshold=0.0
            )
            if r.entity_type in PRESIDIO_MAP
        ]
