"""
Train and evaluate the customer intent classification model.
"""

import pandas as pd

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report


# 1. Load dataset
data = pd.read_csv("data/intents.csv")

texts = data["text"]
labels = data["intent"]


# 2. Split data into training and testing sets
X_train, X_test, y_train, y_test = train_test_split(
    texts,
    labels,
    test_size=0.2,
    random_state=42,
    stratify=labels,
)


# 3. Convert text into TF-IDF features
vectorizer = TfidfVectorizer()

X_train_tfidf = vectorizer.fit_transform(X_train)
X_test_tfidf = vectorizer.transform(X_test)


# 4. Create and train the classifier
model = LogisticRegression(max_iter=1000)

model.fit(X_train_tfidf, y_train)


# 5. Predict the test data
predictions = model.predict(X_test_tfidf)


# 6. Evaluate the model
accuracy = accuracy_score(y_test, predictions)

print("Training completed successfully.")
print("Training examples:", len(X_train))
print("Testing examples:", len(X_test))
print("Accuracy:", round(accuracy * 100, 2), "%")

print("\nClassification Report:")
print(classification_report(y_test, predictions, zero_division=0))