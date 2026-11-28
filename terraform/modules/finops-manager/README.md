# Module `finops-manager` (`pfm-finops-manager-infra`)

Módulo canônico OpenTofu (Padrão Terraform Docs) para provisionamento da função AWS Lambda `pfm-finops-manager` (Python 3.12 Arm64) e agendamentos EventBridge (`stop` 20h30 BRT / `start` 06h00 BRT, `DISABLED` por padrão via `enable_nightly_schedule = false`) isolados por ambiente (`dev` ou `prod`).

## Inputs & Outputs
Consulte `variables.tf` e `outputs.tf`.
