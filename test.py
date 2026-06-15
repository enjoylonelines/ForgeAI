import pandas as pd

X = pd.read_csv("data/raw/secom/secom.data", sep=r"\s+", header=None, na_values="NaN")
labels = pd.read_csv("data/raw/secom/secom_labels.data", sep=r"\s+",
                     header=None, names=["label", "timestamp"])

print(X.shape)                          # ≈ (1567, 590)
print(labels["label"].value_counts())   # -1(정상) vs 1(불량) 개수
print(f"불량률: {(labels['label'] == 1).mean():.1%}")   # ≈ 6.6%
print(f"결측 비율: {X.isna().mean().mean():.1%}")      # 곳곳에 NaN
