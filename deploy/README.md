# Implantação e operação do CoerIA

Este documento é o *runbook* operacional do CoerIA. Reúne a preparação de uma VPS, publicação de uma nova versão no GitHub, atualização da instalação oficial, testes antes do reinício, verificação pós-deploy, rollback e diagnóstico dos problemas mais comuns.

A instalação oficial usa uma versão identificada por **tag Git**. Os docentes acedem apenas ao endereço HTTPS; os procedimentos abaixo destinam-se ao operador técnico.

## Estrutura da instalação oficial

| Elemento | Caminho / valor |
|---|---|
| Código | `/opt/coeria/app` |
| Proprietário atual do checkout | `ubuntu:coeria` |
| Ambiente Python | `/opt/coeria/venv` |
| Configuração e segredos | `/etc/coeria` |
| Base de dados de produção | `/var/lib/coeria/data/prism.db` |
| Sessões NiceGUI | `/var/lib/coeria/nicegui` |
| Base temporária de testes de deploy | `/var/lib/coeria/test-update.db` |
| Backups | `/var/backups/coeria` |
| Serviço | `coeria.service` |
| Proxy HTTPS | Nginx em `coeria.ivovargas.pt` |
| Aplicação local | `127.0.0.1:7860` |

> **Regra operacional:** no servidor atual, os comandos Git em `/opt/coeria/app` são executados pelo utilizador `ubuntu`, que é o proprietário do checkout. Não usar `sudo git` nem `sudo -u coeria git` para atualizar o repositório atual.

---

## 1. Publicar uma nova versão no GitHub

Executar no computador de desenvolvimento, dentro do repositório CoerIA.

### 1.1 Confirmar repositório e branch

```bash
git status --short
git remote -v
git branch --show-current
```

### 1.2 Atualizar dependências e executar validações

No Windows/PowerShell, os mesmos comandos podem ser executados com `python`.

```bash
python -m pip install -r requirements-dev.txt
python -m pip check
python -m pytest -q
python -m compileall app.py prism tests
git diff --check
```

Rever o que vai ser publicado:

```bash
git diff --stat
git diff
```

### 1.3 Preparar e criar o commit

Preferir `git add` explícito para evitar publicar ficheiros locais, bases de dados ou segredos por engano.

```bash
git add <ficheiros-alterados>
git status
git diff --cached --check
git diff --cached --stat
git commit -m "<mensagem do commit>"
git push origin HEAD
```

### 1.4 Criar uma tag de release

Exemplo para a versão `v0.2.0`:

```bash
git tag --list "v0.2.0"
git tag -a v0.2.0 -m "CoerIA v0.2.0"
git push origin v0.2.0
git show v0.2.0 --stat
```

Nunca reutilizar uma tag já publicada para apontar para outro commit. Criar uma nova tag para cada release.

---

## Atualização automatizada com `deploy/update.sh`

Para um deploy normal, o procedimento abaixo está automatizado em `deploy/update.sh`. O script deve ser executado na VPS pelo utilizador proprietário do checkout (`ubuntu` na instalação atual), **sem `sudo` no próprio script**; o script pede `sudo` apenas nas operações administrativas necessárias.

Exemplo:

```bash
cd /opt/coeria/app
./deploy/update.sh v0.2.2
```

O script valida que o checkout está limpo, cria backup, faz `fetch` e checkout da tag, atualiza `COERIA_APP_VERSION`, instala `requirements-vps.lock`, executa a suíte com uma base temporária, reinicia o serviço apenas se os testes passarem e verifica o acesso local/HTTPS, Nginx e serviços.

Se qualquer etapa crítica falhar, o processo termina imediatamente. O script não executa `git reset --hard`, não altera ownership e não imprime segredos.

Para consultar a ajuda:

```bash
./deploy/update.sh --help
```

---

## 2. Atualizar a VPS para uma nova versão

Os exemplos seguintes usam `v0.2.0`. Substituir pela tag que se pretende instalar.

### 2.1 Criar backup antes do deploy

```bash
sudo systemctl start coeria-backup.service
sudo systemctl status coeria-backup.service --no-pager
```

Não prosseguir se o backup tiver falhado.

### 2.2 Confirmar o estado atual do checkout

```bash
stat -c '%U:%G %a %n' /opt/coeria/app /opt/coeria/app/.git
git -C /opt/coeria/app status --short
git -C /opt/coeria/app describe --tags --always
```

Na instalação atual, espera-se que `/opt/coeria/app` e `.git` pertençam a `ubuntu:coeria`.

O `git status --short` deve idealmente não devolver nada. Se existirem alterações locais não esperadas, investigá-las antes do checkout; não usar `git reset --hard` como solução automática.

### 2.3 Obter as tags e selecionar a release

Executar Git como o utilizador `ubuntu` da sessão SSH atual:

```bash
git -C /opt/coeria/app fetch origin --tags
git -C /opt/coeria/app tag --list "v0.2.0"
git -C /opt/coeria/app checkout v0.2.0
git -C /opt/coeria/app describe --tags --always
```

O último comando deve mostrar a tag instalada, por exemplo:

```text
v0.2.0
```

### 2.4 Instalar as dependências bloqueadas da VPS

```bash
sudo /opt/coeria/venv/bin/python -m pip install -r /opt/coeria/app/requirements-vps.lock
sudo /opt/coeria/venv/bin/python -m pip check
```

Para confirmar Pillow, usado pelo processamento de imagens e por `python-pptx`:

```bash
sudo /opt/coeria/venv/bin/python -c "from PIL import Image; print(Image.__version__)"
```

### 2.5 Confirmar configuração da geração de imagens

Não imprimir o conteúdo integral de `/etc/coeria/coeria.env`, porque contém segredos.

Para verificar apenas se as variáveis relevantes existem:

```bash
sudo grep -E '^(OPENAI_API_KEY|COERIA_OPENAI_IMAGE_MODEL|COERIA_OPENAI_IMAGE_SIZE|COERIA_OPENAI_IMAGE_QUALITY|COERIA_OPENAI_IMAGE_MAX_PER_PRESENTATION)=' /etc/coeria/coeria.env | sed 's/=.*/=<configurado>/'
```

Configuração recomendada para o A3:

```text
COERIA_OPENAI_IMAGE_MODEL=gpt-image-2
COERIA_OPENAI_IMAGE_SIZE=1536x864
COERIA_OPENAI_IMAGE_QUALITY=low
COERIA_OPENAI_IMAGE_MAX_PER_PRESENTATION=2
```

A mesma `OPENAI_API_KEY` é usada pelas chamadas OpenAI de texto e de imagem. Nunca guardar a chave real no Git.

### 2.6 Executar a suíte antes de reiniciar produção

É importante iniciar o `pytest` num diretório ao qual o utilizador `coeria` tenha acesso. A forma mais robusta é executar todo o teste dentro de um `sh -c` que primeiro muda para `/opt/coeria/app`:

```bash
sudo -u coeria sh -c '
  cd /opt/coeria/app &&
  COERIA_AUTH_MODE=disabled \
  COERIA_DATABASE_PATH=/var/lib/coeria/test-update.db \
  /opt/coeria/venv/bin/python -m pytest \
    -q \
    -p no:cacheprovider \
    tests
'
```

Não executar este teste a partir de `/home/ubuntu` com `sudo -u coeria`, porque o `pytest` pode tentar regressar ao diretório inicial da sessão e terminar com `PermissionError`.

Só prosseguir com o restart se a suíte terminar com sucesso.

Depois de um teste aprovado:

```bash
sudo rm -f /var/lib/coeria/test-update.db
```

### 2.7 Reiniciar o serviço

```bash
sudo systemctl restart coeria
sudo systemctl status coeria --no-pager
sudo journalctl -u coeria -n 50 --no-pager
```

### 2.8 Verificar a aplicação local e externamente

```bash
curl -I http://127.0.0.1:7860/login
curl -I https://coeria.ivovargas.pt/login
sudo nginx -t
systemctl is-active coeria nginx coeria-backup.timer
git -C /opt/coeria/app describe --tags --always
```

Espera-se que os três serviços estejam `active` e que o último comando apresente a tag implantada.

Um acesso anónimo à raiz pode redirecionar para `/login`. O processo Python deve escutar apenas em `127.0.0.1:7860`.

---

## 3. Resumo operacional de um deploy normal

```bash
# 1. Backup
sudo systemctl start coeria-backup.service
sudo systemctl status coeria-backup.service --no-pager

# 2. Código — substituir v0.2.0 pela release pretendida
git -C /opt/coeria/app status --short
git -C /opt/coeria/app fetch origin --tags
git -C /opt/coeria/app checkout v0.2.0
git -C /opt/coeria/app describe --tags --always

# 3. Dependências
sudo /opt/coeria/venv/bin/python -m pip install -r /opt/coeria/app/requirements-vps.lock
sudo /opt/coeria/venv/bin/python -m pip check

# 4. Testes
sudo -u coeria sh -c '
  cd /opt/coeria/app &&
  COERIA_AUTH_MODE=disabled \
  COERIA_DATABASE_PATH=/var/lib/coeria/test-update.db \
  /opt/coeria/venv/bin/python -m pytest -q -p no:cacheprovider tests
'

# 5. Limpeza e restart
sudo rm -f /var/lib/coeria/test-update.db
sudo systemctl restart coeria

# 6. Verificação
sudo systemctl status coeria --no-pager
sudo journalctl -u coeria -n 50 --no-pager
curl -I http://127.0.0.1:7860/login
curl -I https://coeria.ivovargas.pt/login
sudo nginx -t
systemctl is-active coeria nginx coeria-backup.timer
git -C /opt/coeria/app describe --tags --always
```

---

## 4. Diagnóstico de problemas Git/SSH

### `Could not resolve hostname github-coeria`

Exemplo:

```text
ssh: Could not resolve hostname github-coeria: Temporary failure in name resolution
```

`github-coeria` é um alias SSH. O erro pode ocorrer quando Git é executado por um utilizador diferente daquele que tem o alias no seu `~/.ssh/config`.

Na instalação atual, usar Git como `ubuntu`:

```bash
git -C /opt/coeria/app remote -v
git -C /opt/coeria/app fetch origin --tags
```

Não mudar imediatamente o remote nem copiar chaves SSH entre utilizadores apenas para contornar o erro.

### `detected dubious ownership`

Este erro aparece quando Git considera que o repositório pertence a outro utilizador. Antes de adicionar exceções, confirmar o proprietário real:

```bash
stat -c '%U:%G %a %n' /opt/coeria/app /opt/coeria/app/.git
```

Na instalação atual, Git deve ser executado como `ubuntu`, proprietário do checkout; por isso não é necessário marcar o repositório como `safe.directory` para `coeria` durante o deploy normal.

### `.git/FETCH_HEAD: Permission denied`

Se ocorrer com:

```bash
sudo -u coeria git -C /opt/coeria/app fetch origin --tags
```

é porque `coeria` pertence ao grupo mas não é o proprietário do checkout e não tem escrita em `.git` com permissões `755`.

Não usar `chmod -R 777` e não alterar o ownership sem necessidade. No servidor atual, executar simplesmente:

```bash
git -C /opt/coeria/app fetch origin --tags
```

como `ubuntu`.

### `pytest` termina com `PermissionError` em `session.startpath`

Se o comando foi iniciado em `/home/ubuntu` mas o processo corre como `coeria`, este utilizador pode não conseguir regressar ao diretório inicial.

Executar os testes com:

```bash
sudo -u coeria sh -c '
  cd /opt/coeria/app &&
  COERIA_AUTH_MODE=disabled \
  COERIA_DATABASE_PATH=/var/lib/coeria/test-update.db \
  /opt/coeria/venv/bin/python -m pytest -q -p no:cacheprovider tests
'
```

---

## 5. Rollback para a tag anterior

Se a nova versão apresentar um problema em produção, fazer novo backup antes da alteração sempre que a situação o permita e selecionar explicitamente uma tag conhecida como estável.

Exemplo:

```bash
sudo systemctl start coeria-backup.service
git -C /opt/coeria/app fetch origin --tags
git -C /opt/coeria/app checkout <tag-anterior>
sudo /opt/coeria/venv/bin/python -m pip install -r /opt/coeria/app/requirements-vps.lock
sudo -u coeria sh -c '
  cd /opt/coeria/app &&
  COERIA_AUTH_MODE=disabled \
  COERIA_DATABASE_PATH=/var/lib/coeria/test-update.db \
  /opt/coeria/venv/bin/python -m pytest -q -p no:cacheprovider tests
'
sudo rm -f /var/lib/coeria/test-update.db
sudo systemctl restart coeria
```

Não usar `git reset --hard` como procedimento normal de rollback.

---

## 6. Restaurar um backup da base de dados

Escolher explicitamente um ficheiro em `/var/backups/coeria` e validar a cópia antes de substituir a base de produção:

```bash
sudo systemctl stop coeria
sudo gzip -dc /var/backups/coeria/prism-AAAAMMDDTHHMMSSZ.db.gz | sudo tee /var/lib/coeria/data/prism.restore.db >/dev/null
sudo sqlite3 /var/lib/coeria/data/prism.restore.db 'PRAGMA integrity_check;'
sudo chown coeria:coeria /var/lib/coeria/data/prism.restore.db
sudo chmod 0640 /var/lib/coeria/data/prism.restore.db
sudo mv /var/lib/coeria/data/prism.db /var/lib/coeria/data/prism.before-restore.db
sudo mv /var/lib/coeria/data/prism.restore.db /var/lib/coeria/data/prism.db
sudo systemctl start coeria
```

Só eliminar `prism.before-restore.db` depois de confirmar que a sessão restaurada está correta.

---

## 7. Preparar uma VPS nova

A referência atual usa Ubuntu, Python, Nginx, Certbot, SQLite e UFW. Instalar os componentes base:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv nginx certbot sqlite3 gzip ufw
sudo adduser --system --group --home /nonexistent --no-create-home coeria
sudo install -d -o root -g root -m 0755 /opt/coeria
sudo install -d -o root -g coeria -m 0750 /etc/coeria
sudo install -d -o coeria -g coeria -m 0750 /var/lib/coeria/data
sudo install -d -o coeria -g coeria -m 0750 /var/lib/coeria/nicegui
```

Ao preparar uma nova VPS, definir deliberadamente qual utilizador administrativo será proprietário do checkout e da chave/deploy key SSH. Depois manter esse mesmo utilizador para as operações Git, evitando misturar `root`, `ubuntu` e `coeria`.

Criar o ambiente e instalar a versão bloqueada:

```bash
python3 -m venv /opt/coeria/venv
sudo /opt/coeria/venv/bin/python -m pip install --upgrade pip
sudo /opt/coeria/venv/bin/python -m pip install -r /opt/coeria/app/requirements-vps.lock
sudo /opt/coeria/venv/bin/python -m pip check
```

Instalar a configuração e preencher os segredos apenas na VPS:

```bash
sudo install -o root -g coeria -m 0640 /opt/coeria/app/deploy/coeria.env.example /etc/coeria/coeria.env
sudoedit /etc/coeria/coeria.env
```

O segredo de sessão deve ter pelo menos 32 caracteres e pode ser criado com:

```bash
openssl rand -hex 32
```

Gerar os códigos com `scripts/generate_access_credentials.py` num computador administrativo. Apenas o JSON com hashes deve ser copiado para a VPS:

```bash
sudo install -o root -g coeria -m 0640 /tmp/coeria-access.json /etc/coeria/access.json
```

Instalar e ativar a aplicação:

```bash
sudo install -o root -g root -m 0644 /opt/coeria/app/deploy/coeria.service /etc/systemd/system/coeria.service
sudo systemctl daemon-reload
sudo systemctl enable --now coeria
curl -I http://127.0.0.1:7860/login
```

Instalar o virtual host Nginx depois de obter o certificado TLS adequado:

```bash
sudo install -o root -g root -m 0644 /opt/coeria/app/deploy/nginx-coeria.conf /etc/nginx/sites-available/coeria
sudo ln -s /etc/nginx/sites-available/coeria /etc/nginx/sites-enabled/coeria
sudo nginx -t
sudo systemctl reload nginx
```

Instalar backups e limitar a exposição de rede:

```bash
sudo install -o root -g root -m 0755 /opt/coeria/app/deploy/coeria-backup /usr/local/sbin/coeria-backup
sudo install -o root -g root -m 0644 /opt/coeria/app/deploy/coeria-backup.service /etc/systemd/system/coeria-backup.service
sudo install -o root -g root -m 0644 /opt/coeria/app/deploy/coeria-backup.timer /etc/systemd/system/coeria-backup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now coeria-backup.timer
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

---

## 8. Segredos e dados

Nunca colocar no Git:

- chaves de API;
- segredo de sessão;
- códigos de acesso em claro;
- chaves SSH privadas;
- bases de dados;
- exportações de utilizadores.

Não apresentar o conteúdo integral de `/etc/coeria/coeria.env` em relatórios ou pedidos de suporte. Para confirmar configuração, mostrar apenas nomes de variáveis ou valores não secretos.
