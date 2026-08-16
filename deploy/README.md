# Implantação reproduzível do CoerIA

Este diretório representa, sem segredos, a configuração da instalação oficial
do CoerIA. A referência validada é Ubuntu 26.04 LTS, Python 3.14.4 e a versão da
aplicação indicada pela tag Git. Os docentes usam apenas o endereço HTTPS; os
procedimentos abaixo destinam-se ao operador técnico.

## Estrutura instalada

| Elemento | Caminho |
|---|---|
| Código | `/opt/coeria/app` |
| Ambiente Python | `/opt/coeria/venv` |
| Configuração e acessos | `/etc/coeria` |
| Base de dados | `/var/lib/coeria/data/prism.db` |
| Sessões NiceGUI | `/var/lib/coeria/nicegui` |
| Backups | `/var/backups/coeria` |
| Serviço | `coeria.service` |
| Proxy HTTPS | Nginx em `coeria.ivovargas.pt` |

## Preparar uma VPS nova

Instalar os componentes de sistema:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv nginx certbot sqlite3 gzip ufw
sudo adduser --system --group --home /nonexistent --no-create-home coeria
sudo install -d -o root -g root -m 0755 /opt/coeria
sudo install -d -o root -g coeria -m 0750 /etc/coeria
sudo install -d -o coeria -g coeria -m 0750 /var/lib/coeria/data
sudo install -d -o coeria -g coeria -m 0750 /var/lib/coeria/nicegui
```

Criar uma chave SSH exclusiva, sem palavra-passe, e adicionar a chave pública ao
repositório GitHub como *Deploy key* apenas de leitura:

```bash
sudo install -d -o root -g root -m 0700 /root/.ssh
sudo ssh-keygen -t ed25519 -f /root/.ssh/coeria_github -C "CoerIA VPS read-only"
sudo cat /root/.ssh/coeria_github.pub
```

Registar o alias em `/root/.ssh/config`, depois de confirmar a impressão digital
oficial do GitHub:

```sshconfig
Host github-coeria
  HostName github.com
  User git
  IdentityFile /root/.ssh/coeria_github
  IdentitiesOnly yes
```

Clonar e selecionar a versão identificada para implantação:

```bash
sudo git clone git@github-coeria:IvoVargas/CoerIA.git /opt/coeria/app
sudo git -C /opt/coeria/app fetch --tags
sudo git -C /opt/coeria/app checkout v0.1.0
sudo python3 -m venv /opt/coeria/venv
sudo /opt/coeria/venv/bin/python -m pip install --upgrade pip
sudo /opt/coeria/venv/bin/python -m pip install -r /opt/coeria/app/requirements-vps.lock
sudo /opt/coeria/venv/bin/python -m pip check
```

Instalar a configuração e preencher os segredos diretamente na VPS. O segredo
de sessão deve ter pelo menos 32 caracteres e pode ser criado com
`openssl rand -hex 32`:

```bash
sudo install -o root -g coeria -m 0640 /opt/coeria/app/deploy/coeria.env.example /etc/coeria/coeria.env
sudoedit /etc/coeria/coeria.env
```

Gerar os códigos com `scripts/generate_access_credentials.py` num computador
administrativo. Apenas o JSON com hashes é copiado para a VPS:

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

Obter primeiro o certificado, com a porta 80 livre, e instalar depois o virtual
host definitivo:

```bash
sudo systemctl stop nginx
sudo certbot certonly --standalone -d coeria.ivovargas.pt
sudo systemctl start nginx
sudo install -o root -g root -m 0644 /opt/coeria/app/deploy/nginx-coeria.conf /etc/nginx/sites-available/coeria
sudo ln -s /etc/nginx/sites-available/coeria /etc/nginx/sites-enabled/coeria
sudo nginx -t
sudo systemctl reload nginx
```

Instalar os backups e limitar a exposição de rede:

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

## Atualizar para uma nova versão

Criar primeiro um backup e só depois mudar para uma tag já publicada:

```bash
sudo systemctl start coeria-backup.service
sudo git -C /opt/coeria/app fetch --tags
sudo git -C /opt/coeria/app checkout v0.1.0
sudo /opt/coeria/venv/bin/python -m pip install -r /opt/coeria/app/requirements-vps.lock
sudo -u coeria env COERIA_AUTH_MODE=disabled COERIA_DATABASE_PATH=/var/lib/coeria/test-update.db /opt/coeria/venv/bin/python -m pytest -q -p no:cacheprovider /opt/coeria/app/tests
sudo rm -f /var/lib/coeria/test-update.db
sudo systemctl restart coeria
```

O ficheiro temporário `/var/lib/coeria/test-update.db` deve ser removido depois
de confirmado o sucesso dos testes. Para recuar, repetir o procedimento com a
tag anterior; não usar `git reset --hard`.

## Verificação e diagnóstico

```bash
git -C /opt/coeria/app describe --tags --always
systemctl is-enabled coeria nginx coeria-backup.timer
systemctl is-active coeria nginx coeria-backup.timer
sudo systemctl status coeria --no-pager
sudo journalctl -u coeria -n 50 --no-pager
sudo nginx -t
curl -I https://coeria.ivovargas.pt/login
```

Um acesso anónimo à raiz deve devolver um redirecionamento para `/login`. O
serviço Python escuta apenas em `127.0.0.1:7860`.

## Restaurar um backup

Escolher explicitamente um ficheiro em `/var/backups/coeria` e validar a cópia
antes de substituir a base de dados:

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

Só eliminar `prism.before-restore.db` depois de confirmar a sessão restaurada.

## Segredos e dados

Nunca colocar no Git as chaves de API, o segredo de sessão, códigos em claro,
chaves SSH, bases de dados ou exportações. Não apresentar o conteúdo de
`/etc/coeria/coeria.env` em relatórios. Para confirmar a presença das chaves sem
as revelar, mostrar apenas os nomes das variáveis.
