"""Build twice in isolated directories; never overwrite frozen data/master files."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def fingerprint(path):
    return {"size_bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, default=Path("data/master/train_features_full.csv"))
    parser.add_argument("--cohort", type=Path)
    parser.add_argument("--expected-features", type=int)
    parser.add_argument("--output", type=Path, default=Path("docs/artifact_reproducibility.json"))
    args = parser.parse_args(argv)
    sources = [args.train.resolve()]
    if args.cohort:
        sources.append(args.cohort.resolve())
    for source in sources:
        if not source.is_file():
            parser.error(f"Missing frozen input: {source}")
    if len({p.name for p in sources}) != len(sources):
        parser.error("Training and cohort files must have distinct basenames.")
    repo = Path(__file__).resolve().parents[1]
    source_hashes = {p.name: fingerprint(p) for p in sources}
    outputs = ["models/preprocess.joblib", "models/preprocess_metadata.json",
               "models/feature_names.json", "encoded/X_train_full_oof.npz",
               "encoded/train_full_oof_rows.csv"]
    runs = []
    with tempfile.TemporaryDirectory(prefix="preprocess-rebuild-") as folder:
        for index in range(2):
            root = Path(folder) / f"run-{index + 1}"
            (root / "inputs").mkdir(parents=True)
            copied = []
            for source in sources:
                destination = root / "inputs" / source.name
                shutil.copyfile(source, destination)
                if fingerprint(destination) != source_hashes[source.name]:
                    raise RuntimeError(f"Input changed while copying: {source.name}")
                copied.append(destination.relative_to(root) if index == 0 else destination)
            env = {**os.environ, "PYTHONPATH": str(repo), "PYTHONHASHSEED": str(index)}
            build = [sys.executable, "-m", "src.features.pipeline", "--features", "full",
                     "--train", str(copied[0]), "--output", "models/preprocess.joblib",
                     "--encoded-dir", "encoded", "--describe", "--docs", "features.md"]
            verify = [sys.executable, "-m", "tools.verify_phuong", "--train", str(copied[0]),
                      "--artifact", "models/preprocess.joblib", "--encoded-dir", "encoded",
                      "--output", "verification.json"]
            if args.cohort:
                build += ["--cohort", str(copied[1]), "--require-imputed"]
                verify += ["--cohort", str(copied[1])]
            subprocess.run(build, cwd=root, env=env, check=True)
            subprocess.run(verify, cwd=root, env=env, check=True)
            metadata = json.loads((root / "models/preprocess_metadata.json").read_text())
            if args.expected_features is not None and metadata["output_features"] != args.expected_features:
                raise RuntimeError(f"Unexpected feature count: {metadata['output_features']}")
            if metadata["training_source"] != sources[0].name:
                raise RuntimeError("Training metadata contains a path instead of a basename.")
            if args.cohort and metadata["cohort_source"] != sources[1].name:
                raise RuntimeError("Cohort metadata contains a path instead of a basename.")
            runs.append({path: fingerprint(root / path) for path in outputs})
        if runs[0] != runs[1]:
            raise RuntimeError("Independent rebuild hashes differ; no success report was written.")
    if any(fingerprint(p) != source_hashes[p.name] for p in sources):
        raise RuntimeError("Frozen input changed during verification.")
    report = {
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
        "working_tree_dirty": bool(subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=repo, text=True).strip()),
        "pipeline_sha256": fingerprint(repo / "src/features/pipeline.py")["sha256"],
        "python_version": metadata["python_version"], "versions": metadata["versions"],
        "input_files": source_hashes, "missing_mode": metadata["missing_mode"],
        "output_features": metadata["output_features"], "independent_runs": 2,
        "relative_and_absolute_input_paths": True, "all_output_hashes_match": True,
        "independent_oof_verification_passed_each_run": True,
        "outputs": runs[0],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
