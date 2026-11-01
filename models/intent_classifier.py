"""
Customer intent classification.
"""

import pandas as pd
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression


class IntentClassifier:
    """Classify customer messages into predefined intents."""

    def __init__(self, dataset_path: str | None = None):
        if dataset_path is None:
            dataset_path = str(
                Path(__file__).resolve().parents[1] / "data" / "intents.csv"
            )
        self.data = pd.read_csv(dataset_path)

        self.vectorizer = TfidfVectorizer()
        self.model = LogisticRegression(max_iter=1000)

        self._train()

    def _train(self):
        """Train the classifier using the intent dataset."""

        texts = self.data["text"]
        labels = self.data["intent"]

        features = self.vectorizer.fit_transform(texts)

        self.model.fit(features, labels)

    def predict(self, text: str) -> str:
        """Predict the intent of a new customer message."""

        normalized = text.casefold().strip()
        if any(word in normalized for word in ("hello", "hi", "hey", "good morning", "good afternoon", "good evening")):
            return "GREETING"
        if any(
            phrase in normalized
            for phrase in (
                "stop calling",
                "do not call",
                "don't call",
                "remove my number",
                "not interested",
            )
        ):
            return "DO_NOT_CALL"
        if any(
            phrase in normalized
            for phrase in (
                "route",
                "directions",
                "how do i reach",
                "where is the property",
                "location",
                "पत्ता",
                "रस्ता",
                "रास्ता",
            )
        ):
            return "LOCATION_INQUIRY"
        if any(word in normalized for word in ("amenity", "amenities", "play area", "fitness", "garden", "parking")):
            return "AMENITIES_INQUIRY"
        if any(word in normalized for word in ("area", "square feet", "sq ft", "size")):
            return "AREA_INQUIRY"
        if "budget" in normalized:
            return "BUDGET_INQUIRY"
        if any(
            phrase in normalized
            for phrase in ("site visit", "visit the property", "visit the flat")
        ):
            return "BOOK_APPOINTMENT"
        if any(
            phrase in normalized
            for phrase in ("flat", "apartment", "bhk", "घर", "फ्लॅट", "फ्लैट")
        ) and any(
            phrase in normalized
            for phrase in ("price", "cost", "rate", "how much", "starting", "किंमत", "कीमत")
        ):
            return "PRICE_INQUIRY"
        if any(phrase in normalized for phrase in ("flat", "flats", "apartment", "bhk", "property", "project", "घर", "फ्लॅट", "फ्लैट")):
            return "PRODUCT_INQUIRY"

        features = self.vectorizer.transform([text])

        prediction = self.model.predict(features)

        return prediction[0]