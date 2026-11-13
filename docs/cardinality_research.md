# Brand/model cardinality study

20,000 train rows, 14,964 val rows, LightGBM with identical remaining features. Only the brand/model encoding changes.

Cardinality on train: `brand` 103 · `model` 1,912 · `model_group` 711 · `brand|model` 1,968.

| Encoding | R²(log) | RMSE(log) | MAE (VND) | MAPE | median APE |
| --- | ---: | ---: | ---: | ---: | ---: |
| brand_and_model_categorical | 0.9319 | 0.2159 | 102,465,148 | 0.137 | 0.075 |
| model_group_categorical | 0.9313 | 0.2169 | 103,505,326 | 0.137 | 0.075 |
| model_categorical | 0.9304 | 0.2182 | 103,642,113 | 0.138 | 0.075 |
| target_encoded_brand_model | 0.9178 | 0.2372 | 126,248,925 | 0.159 | 0.097 |

**Conclusion: `brand_and_model_categorical` wins on val.** The plain categorical wins at this cardinality, so the report must not claim the target encoding is improving accuracy — it is a variance-control choice.

The encoding is fitted inside each of 5 grouped folds on train only, so the val number is not inflated by a row's own target.
