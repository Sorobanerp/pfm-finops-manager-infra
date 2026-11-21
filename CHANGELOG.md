# Changelog — `pfm-finops-manager-infra`

Todas as alterações notáveis neste repositório são documentadas neste arquivo seguindo o padrão [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e versionamento semântico [SemVer 2.0.0](https://semver.org/lang/pt-BR/).

---

## [Unreleased]

---

## [0.4.0] - 2026-11-21

### Changed
- Refatoração completa de `src/finops_manager/handler.py` eliminando 100% do gerenciamento legado de NodeGroups EKS/AutoScaling e direcionando `stop`, `start`, `status` e `audit` exclusivamente para o cluster ECS Fargate Spot (`pfm-ecs-pilot`), instância RDS PostgreSQL 16 (`pfm-core-ledger-prod`) e função AWS Lambda (`pfm-ai-worker-python-prod`).
- Adicionado controle opcional de concorrência (`freeze_lambda` via `PutFunctionConcurrency` / `DeleteFunctionConcurrency`) sobre `pfm-ai-worker-python-prod` e guardrails de auditoria (`cost_guardrails`) para alertar sobre qualquer cluster EKS ou NAT Gateway ativo na região `us-east-2`.

### Security
- Política IAM Least Privilege (`pfm-finops-manager-least-privilege`) restrita aos ARNs reais da conta `366476833548` (`arn:aws:ecs:us-east-2:366476833548:cluster/pfm-ecs-pilot`, `service/pfm-ecs-pilot/*`, `arn:aws:rds:us-east-2:366476833548:db:pfm-*`, `arn:aws:lambda:us-east-2:366476833548:function:pfm-ai-worker*`).

---

## [0.2.0] - 2026-11-20

### Added
- Suporte completo a ECS Fargate Spot (`stop`/`start`/`audit`/`status`), relatório de run-rate em USD e schedules EventBridge desabilitados por padrão (`enable_nightly_schedule = false`).

### Changed
- Alinhamento com a arquitetura **PFM Core Banking V3.0 (Production-Ready FinOps & Multi-Cloud)**.

### Security
- Aplicação estrita de políticas Zero-Trust (OIDC sem chaves estáticas, Trivy/Semgrep/Gitleaks gates e isolamento por tenant).

### Infrastructure
- Permissões IAM de menor privilégio para `ecs:ListServices`, `ecs:DescribeServices` e `ecs:UpdateService`.

---

## [0.1.0] - 2026-11-15

### Added
- Estrutura inicial do repositório `pfm-finops-manager-infra`, pipelines GitHub Actions e integração ao ecossistema Gitflow `Sorobanerp`.
