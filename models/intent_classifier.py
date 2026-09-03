"""
Customer intent classification.
"""

import pandas as pd

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression


class IntentClassifier:
    """Classify customer messages into predefined intents."""

    def __init__(self, dataset_path: str = "data/intents.csv"):
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

        features = self.vectorizer.transform([text])

        prediction = self.model.predict(features)

        return prediction[0]