#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/opt/coeria/app"
VENV_PYTHON="/opt/coeria/venv/bin/python"
ENV_FILE="/etc/coeria/coeria.env"
TEST_DB="/var/lib/coeria/test-update.db"
SERVICE="coeria"
BACKUP_SERVICE="coeria-backup.service"
NGINX_SITE_SOURCE="$APP_DIR/deploy/nginx-coeria.conf"
NGINX_SITE_TARGET="/etc/nginx/sites-available/coeria"
PUBLIC_URL="https://coeria.ivovargas.pt/login"
LOCAL_URL="http://127.0.0.1:7860/login"

usage() {
  cat <<'USAGE'
Uso:
  ./deploy/update.sh <tag>

Exemplo:
  ./deploy/update.sh v0.2.2

O script executa:
  1. verificações de segurança do checkout;
  2. backup;
  3. fetch e checkout da tag;
  4. atualização de COERIA_APP_VERSION;
  5. instalação das dependências bloqueadas;
  6. testes com base SQLite temporária;
  7. sincronização e validação da configuração Nginx;
  8. restart do serviço;
  9. verificações local, HTTPS, Nginx e serviços.
USAGE
}

log() {
  printf '\n==> %s\n' "$*"
}

fail() {
  printf '\nERRO: %s\n' "$*" >&2
  exit 1
}

cleanup() {
  sudo rm -f "$TEST_DB" >/dev/null 2>&1 || true
  [[ -z "${NGINX_SITE_BACKUP:-}" ]] || rm -f "$NGINX_SITE_BACKUP"
}
trap cleanup EXIT
trap 'fail "Falha na linha $LINENO. O deploy foi interrompido."' ERR

TAG="${1:-}"
if [[ -z "$TAG" || "$TAG" == "-h" || "$TAG" == "--help" ]]; then
  usage
  [[ -n "$TAG" ]] && exit 0
  exit 2
fi

if [[ ! "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$ ]]; then
  fail "Tag inválida: '$TAG'. Esperado algo como v0.2.2."
fi

[[ -d "$APP_DIR/.git" ]] || fail "Não encontrei um repositório Git em $APP_DIR."
[[ -x "$VENV_PYTHON" ]] || fail "Python do ambiente virtual não encontrado em $VENV_PYTHON."
[[ -f "$APP_DIR/requirements-vps.lock" ]] || fail "Falta $APP_DIR/requirements-vps.lock."
[[ -f "$ENV_FILE" ]] || fail "Falta o ficheiro de configuração $ENV_FILE."

log "Versão atual"
CURRENT_VERSION="$(git -C "$APP_DIR" describe --tags --always 2>/dev/null || true)"
printf 'Atual: %s\nAlvo:  %s\n' "${CURRENT_VERSION:-desconhecida}" "$TAG"

LATEX_PDF_SETTING="$(
  sudo sed -n 's/^COERIA_LATEX_PDF_ENABLED=//p' "$ENV_FILE" \
    | tail -n 1 \
    | tr '[:upper:]' '[:lower:]' \
    | tr -d '[:space:]'
)"
if [[ "$LATEX_PDF_SETTING" =~ ^(1|true|yes|on)$ ]]; then
  LATEX_COMPILER_SETTING="$(
    sudo sed -n 's/^COERIA_LATEX_COMPILER=//p' "$ENV_FILE" | tail -n 1
  )"
  LATEX_COMPILER_SETTING="${LATEX_COMPILER_SETTING:-pdflatex}"
  command -v "$LATEX_COMPILER_SETTING" >/dev/null 2>&1 \
    || fail "A compilação LaTeX/PDF está ativa, mas '$LATEX_COMPILER_SETTING' não existe."
  printf 'Compilador LaTeX: %s\n' "$(command -v "$LATEX_COMPILER_SETTING")"
fi

log "Verificar checkout"
OWNER="$(stat -c '%U' "$APP_DIR")"
CURRENT_USER="$(id -un)"
printf 'Proprietário do checkout: %s\nUtilizador atual: %s\n' "$OWNER" "$CURRENT_USER"

if [[ "$OWNER" != "$CURRENT_USER" ]]; then
  fail "O checkout pertence a '$OWNER'. Execute este script como esse utilizador, não com sudo."
fi

if [[ -n "$(git -C "$APP_DIR" status --porcelain)" ]]; then
  git -C "$APP_DIR" status --short
  fail "Existem alterações locais em $APP_DIR. Faça commit/stash ou investigue antes do deploy."
fi

log "Criar backup"
sudo systemctl start "$BACKUP_SERVICE"
sudo systemctl status "$BACKUP_SERVICE" --no-pager || true
if sudo systemctl is-failed --quiet "$BACKUP_SERVICE"; then
  fail "O backup falhou. Não será feito deploy."
fi

log "Obter tags do Git"
git -C "$APP_DIR" fetch origin --tags
if ! git -C "$APP_DIR" rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  fail "A tag '$TAG' não existe no repositório local após o fetch."
fi

log "Checkout de $TAG"
git -C "$APP_DIR" checkout "$TAG"
INSTALLED="$(git -C "$APP_DIR" describe --tags --exact-match 2>/dev/null || true)"
[[ "$INSTALLED" == "$TAG" ]] || fail "Checkout inesperado: '$INSTALLED'."

log "Atualizar COERIA_APP_VERSION"
APP_VERSION="${TAG#v}"
if sudo grep -q '^COERIA_APP_VERSION=' "$ENV_FILE"; then
  sudo sed -i "s/^COERIA_APP_VERSION=.*/COERIA_APP_VERSION=$APP_VERSION/" "$ENV_FILE"
else
  printf '\nCOERIA_APP_VERSION=%s\n' "$APP_VERSION" | sudo tee -a "$ENV_FILE" >/dev/null
fi
printf 'COERIA_APP_VERSION=%s\n' "$APP_VERSION"

log "Instalar dependências bloqueadas"
sudo "$VENV_PYTHON" -m pip install -r "$APP_DIR/requirements-vps.lock"
sudo "$VENV_PYTHON" -m pip check

log "Executar testes antes do restart"
sudo rm -f "$TEST_DB"
sudo -u coeria sh -c "
  cd '$APP_DIR' &&
  COERIA_AUTH_MODE=disabled \\
  COERIA_DATABASE_PATH='$TEST_DB' \\
  '$VENV_PYTHON' -m pytest -q -p no:cacheprovider tests
"
sudo rm -f "$TEST_DB"

log "Sincronizar configuração Nginx"
[[ -f "$NGINX_SITE_SOURCE" ]] || fail "Falta $NGINX_SITE_SOURCE."
NGINX_RELOAD_REQUIRED=0
NGINX_SITE_BACKUP=""
NGINX_SITE_EXISTED=0
if ! cmp -s "$NGINX_SITE_SOURCE" "$NGINX_SITE_TARGET"; then
  NGINX_SITE_BACKUP="$(mktemp)"
  if sudo test -f "$NGINX_SITE_TARGET"; then
    sudo cp "$NGINX_SITE_TARGET" "$NGINX_SITE_BACKUP"
    NGINX_SITE_EXISTED=1
  fi
  sudo install -o root -g root -m 0644 "$NGINX_SITE_SOURCE" "$NGINX_SITE_TARGET"
  if ! sudo nginx -t; then
    if [[ "$NGINX_SITE_EXISTED" == "1" ]]; then
      sudo install -o root -g root -m 0644 "$NGINX_SITE_BACKUP" "$NGINX_SITE_TARGET"
    else
      sudo rm -f "$NGINX_SITE_TARGET"
    fi
    sudo nginx -t || true
    fail "A nova configuração Nginx era inválida e foi revertida."
  fi
  NGINX_RELOAD_REQUIRED=1
fi

log "Reiniciar $SERVICE"
sudo systemctl restart "$SERVICE"
sudo systemctl is-active --quiet "$SERVICE" || {
  sudo systemctl status "$SERVICE" --no-pager || true
  sudo journalctl -u "$SERVICE" -n 80 --no-pager || true
  fail "O serviço $SERVICE não ficou ativo."
}

log "Validar Nginx"
sudo nginx -t
if [[ "$NGINX_RELOAD_REQUIRED" == "1" ]]; then
  sudo systemctl reload nginx
fi

check_http() {
  local url="$1"
  local label="$2"
  local attempts="${3:-1}"
  local delay="${4:-2}"
  local code="000"
  local attempt

  for ((attempt = 1; attempt <= attempts; attempt++)); do
    code="$(
      curl \
        --silent \
        --request GET \
        --output /dev/null \
        --write-out '%{http_code}' \
        --max-time 10 \
        "$url" \
      || true
    )"
    code="${code:-000}"

    if [[ "$code" =~ ^[23][0-9][0-9]$ ]]; then
      printf '%s: HTTP %s\n' "$label" "$code"
      return 0
    fi

    if (( attempt < attempts )); then
      printf '%s ainda indisponível (HTTP %s). Nova tentativa em %ss (%s/%s).\n' \
        "$label" "$code" "$delay" "$attempt" "$attempts"
      sleep "$delay"
    fi
  done

  if [[ "$label" == "Local" ]]; then
    sudo systemctl status "$SERVICE" --no-pager -l || true
    sudo journalctl -u "$SERVICE" -n 100 --no-pager || true
    sudo ss -ltnp | grep ':7860' || true
  fi

  fail "$label não ficou disponível após $attempts tentativas (último HTTP $code): $url"
}

log "Verificar aplicação"
# O NiceGUI pode precisar de alguns segundos para começar a aceitar ligações
# depois de o systemd considerar o processo ativo.
check_http "$LOCAL_URL" "Local" 15 2
check_http "$PUBLIC_URL" "HTTPS" 5 2

log "Verificar serviços"
for unit in coeria nginx coeria-backup.timer; do
  state="$(systemctl is-active "$unit" || true)"
  printf '%-22s %s\n' "$unit" "$state"
  [[ "$state" == "active" ]] || fail "$unit não está ativo."
done

log "Versão instalada"
FINAL_VERSION="$(git -C "$APP_DIR" describe --tags --always)"
printf '%s\n' "$FINAL_VERSION"
[[ "$FINAL_VERSION" == "$TAG" ]] || fail "A versão final não corresponde a $TAG."

log "Deploy concluído com sucesso"
printf 'CoerIA %s está instalado e ativo.\n' "$TAG"
