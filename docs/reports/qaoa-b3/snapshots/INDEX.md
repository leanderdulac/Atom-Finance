# Painéis QAOA B3

Esta pasta recebe os painéis da amostra inteira. Eles não entram no git: o cache de preços é grande e é reconstruído.

```text
python scripts/export_qaoa_b3_snapshots.py --cache data/net-net --events data/equal-weight/yahoo --out docs/reports/qaoa-b3/snapshots
```

Um arquivo por rebalanceamento trimestral:

- `YYYY-MM-DD.parquet` e `YYYY-MM-DD.json` — informação até `t_r`, inclusive
- `holdout/YYYY-MM-DD_fwd.parquet` — retornos realizados depois de `t_r`; não entra na seleção

O exemplo de esquema, pequeno e versionado, está em `docs/reports/qaoa-b3/fixtures/`. O contrato está em `docs/QAOA-B3-PHASE1.md`.

O mesmo esquema é o que o Quantum Lighting lê em `/workspace/qaoa-b3/inputs/` e devolve em `/workspace/qaoa-b3/outputs/selections.parquet`.
