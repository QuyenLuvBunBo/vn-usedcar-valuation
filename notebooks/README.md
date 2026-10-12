# Notebooks

Conventions so that nine people can work on EDA and modelling without conflicts:

- Each member creates **their own folder**: `notebooks/quyen/`, `notebooks/bao/`, …
  Never edit another member's notebook.
- **Always strip outputs before committing** (outputs and `execution_count` create noisy diffs):

  ```bash
  pip install nbstripout
  nbstripout --install        # strips outputs automatically on commit
  ```

- Name notebooks after the task: `price_by_brand_eda.ipynb`, `median_baseline.ipynb`, …
- When a notebook grows, move stable logic into `src/` (for example `src/data_prep/`) and call it
  from the notebook.

Week 2 split from the project plan: EDA in sub-team 3 (Phong, Tuấn Anh, Quang);
missing-data audit in sub-team 2 (Hiếu, Bảo, Duy); merge/dedupe in sub-team 1 (Quyền, Quyết, Phương).
