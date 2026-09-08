# TillFlow — devops-g3

Multi-tenant POS + M-Pesa payments on AWS ECS (us-west-1). Daraja sandbox only.

## Ownership (locked)
See `docs/ownership.md`.
- **Platform** — Lwam
- **Payments + integrity** — Hunter
- **Product + POS** — Joyce
- **Delivery / CI-CD** — Wairimu
- **Reliability + operations** — Minage

## TODO before G0 (Wed 9 Sep)
- [x] Group number set: **devops-g3**
- [x] Map @handles in CODEOWNERS to real GitHub usernames
- [x] Fill every ADR Decision/Alternatives/Consequences
- [x] Draft SLOs (`docs/slo-error-budgets.md`)
- [ ] Complete `docs/threat-model.md` (DRI: Lwam)
- [ ] Grant mentor repo access (need mentor's GitHub handle)

## Repo conventions
- **Branching**: short-lived `feat/<area>-<thing>` branches off `main`, squash-merged in.
- **Branch protection on `main`**: PR required, CODEOWNERS review required, `ci.yml`'s `validate`
  job required to pass before merge.
- **Folder layout**: `services/{web,pos,payments,commission,_shared}`, `infra/{envs,modules}`,
  `.github/workflows/`, `docs/`, `evidence/<area>/` — see [ADR index](docs/adr/).

## One-command lifecycle (fill in during G1)
- bootstrap: `TODO`
- deploy: `TODO`
- destroy: `TODO`
