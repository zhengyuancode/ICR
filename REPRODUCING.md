# Reproduction guide

Commands assume the repository root as the working directory. The recorded
experiments used Python 3.11; Python 3.10 or newer is recommended.

## 1. Environment and public data

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python scripts/fetch_public_data.py
```

The fetcher verifies the exact TaskBench file hashes and checks out
PlanBench-XL commit `a24bfd5f1a6ad7ad3c5d5204525272c6488225ac`.

## 2. Structural studies (no API)

### Fixed-assignment closure

```bash
python -m research.taskbench_multinode_study --domain multimedia --seed 20260924
python -m research.taskbench_multinode_study --domain huggingface --seed 20260924
python -m research.analyze_taskbench_multinode
python -m research.benchmark_repair_region
```

Repeat the two domain commands with seeds `20260925` and `20260926` for the
reported assignment sensitivity.

### Joint choice on forests

```bash
python -m research.joint_taskbench_study --seed 20260924
python -m research.joint_taskbench_study --seed 20260925
python -m research.joint_taskbench_study --seed 20260926
python -m research.analyze_joint_taskbench
python -m research.joint_beam_sensitivity
python -m research.joint_scaling
python -m research.benchmark_joint_beam_20260930
```

### Multi-input DAGs

```bash
python -m research.port_dag_taskbench_study --seed 20260924 --variants 2
python -m research.port_dag_taskbench_study --seed 20260925 --variants 2
python -m research.port_dag_taskbench_study --seed 20260926 --variants 2
python -m research.port_dag_taskbench_study --seed 20260924 --variants 4
python -m research.port_dag_taskbench_study --seed 20260925 --variants 4
python -m research.port_dag_taskbench_study --seed 20260926 --variants 4
```

## 3. PlanBench-XL certificate study (no API)

```bash
python -m research.planbench_probe
python -m research.certify_planbench_paths --seed 20260925
python -m research.certify_planbench_paths --seed 20260926
python -m research.certify_planbench_paths --seed 20260927
python -m research.relational_certificate_study
python -m research.compile_planbench_instance_contracts
python -m research.analyze_planbench_route_decisions
python -m research.benchmark_certificate_index
python -m research.integrated_planbench_replay
python -m research.integrated_planbench_suffix_replay
```

These commands use only the released tool schemas, executor, and 100-row retail
relation. Candidate execution is used after compilation only to audit all
31,565 path-input classifications.

The additional integration replay is post-review exploratory analysis. Its
selection rule is saved in `integrated_replay_protocol_20260930.json`; the
output records all 32 composed two-call configurations and their 3,200 inputs.
The suffix replay appends every compatible unchanged one-call consumer and
records 117 executable extensions, including 10,062 certificate-admitted,
defined configuration-input executions.
The same-instance beam timing uses five alternating-order repetitions per
instance and is an implementation measurement, not a new accuracy endpoint.

## 4. Online studies (API required)

Create the untracked file `experiments/config.local.json`:

```json
{
  "api_key": "YOUR_KEY",
  "base_url": "YOUR_OPENAI_COMPATIBLE_BASE_URL",
  "model": "YOUR_MODEL_ID"
}
```

Use the same endpoint, temperature-zero configuration, and step limits for all
paired arms.

### 21-task matched admission control

```bash
python -m research.run_planbench_final_holdout --variant baseline
python -m research.run_planbench_final_holdout --variant global_advice
python -m research.run_planbench_final_holdout --variant instance_advice
python -m research.run_planbench_final_holdout --variant type_only_advice
python -m research.analyze_planbench_final_holdout
```

### 72-task system confirmation

```bash
python -m research.run_planbench_seed43_transfer --variant baseline
python -m research.run_planbench_seed43_transfer --variant instance_advice
python -m research.analyze_planbench_seed43_confirmation
```

The parent cohort contains 102 frozen tasks. The first 30 are diagnostic; the
remaining 72 form the untouched confirmation subset specified in
`planbench_seed43_confirmation72_protocol.json`.

### 20-prefix matched-state confirmation

The frozen cohort uses blocker seeds `48, 49, 50, 52, 54, 55, 56, 57, 58, 60,
61`. For each seed, run the capture and both predeclared arms:

```bash
python -m research.run_planbench_prefix_capture --seed SEED
python -m research.run_planbench_prefix_pair --cohort confirmation --variant global --seed SEED
python -m research.run_planbench_prefix_pair --cohort confirmation --variant instance --seed SEED
python -m research.run_planbench_prefix_type_control --seed SEED
```

Then analyze the frozen rows:

```bash
python -m research.analyze_planbench_prefix_trial --cohort confirmation
python -m research.analyze_planbench_prefix_type_control
python -m research.audit_review_mechanism_20260930
```

Hosted model services can change over time, so a fresh API rerun need not
reproduce identical trajectories. The committed protocols and outcome rows
preserve the exact evaluated sample and recorded statistics.
