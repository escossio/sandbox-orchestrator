# Dev service (systemd)

Este repo inclui templates em `deploy/` para instalar o serviço no host
sem commitar arquivos de `/etc`.

## Instalação rápida (no host)

```bash
sudo cp deploy/env/sandbox-orchestrator.env.example /etc/sandbox-orchestrator.env
sudo cp deploy/systemd/sandbox-orchestrator-dev.service /etc/systemd/system/sandbox-orchestrator-dev.service
sudo systemctl daemon-reload
sudo systemctl enable --now sandbox-orchestrator-dev.service
