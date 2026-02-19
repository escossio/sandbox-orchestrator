# Git Audit Log – Sandbox Orchestrator

## Objetivo

Este documento define como o projeto registra automaticamente todas as ações relevantes realizadas no repositório Git, criando um histórico auditável e persistente.

A finalidade é:

- Rastreabilidade total de alterações
- Histórico cronológico das ações
- Transparência no fluxo de desenvolvimento
- Base para auditoria técnica futura


## Conceito

Toda ação relevante no repositório deve gerar um registro automático em arquivo .log.

Isso inclui:

- git add
- git commit
- git merge
- git pull
- git push
- git reset
- git revert
- criação de branch
- troca de branch


## Local de Armazenamento

Os arquivos de auditoria ficam em:

./logs/git-audit/

Estrutura:

logs/
└── git-audit/
    ├── 2026-02.log
    ├── 2026-03.log
    └── ...

- Um arquivo por mês
- Nome no formato YYYY-MM.log


## Formato do Registro

Cada ação registrada deve seguir o padrão:

[YYYY-MM-DDTHH:MM:SS.sssZ] USER=<user> ACTION=<git command> BRANCH=<branch> COMMIT=<hash>

Exemplo real:

[2026-02-18T03:41:22.315Z] USER=leo ACTION=git commit BRANCH=main COMMIT=ca5f608

Se não houver commit hash (ex: git status), registrar como:

COMMIT=none


## Regras

1. O log nunca deve ser sobrescrito.
2. Sempre usar append.
3. Sempre usar timestamp UTC com milissegundos.
4. O formato deve ser consistente.
5. O diretório logs/git-audit deve existir antes da escrita.


## Versionamento do Log

Decisão do projeto:

- Os logs NÃO devem ser versionados no Git.
- O diretório logs/ deve estar no .gitignore.

Motivo:
- Evitar crescimento desnecessário do repositório.
- Evitar commits circulares causados pelo próprio log.


## Integração com Workflow

Toda vez que o desenvolvedor executar um comando Git:

1. O comando executa normalmente.
2. A ação é registrada automaticamente no log.
3. O desenvolvedor não precisa fazer nada manualmente.


## Benefícios

- Auditoria técnica completa
- Histórico detalhado de operações
- Base para investigação de regressões
- Evidência de governança de mudanças
- Profissionalismo de nível enterprise


## Observação

Este documento define o comportamento.
A implementação técnica é tratada separadamente.
