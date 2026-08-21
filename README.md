# Postador automático de Facebook

Puxa vídeos de uma pasta do **Google Drive** ou **OneDrive** e publica nas suas
Páginas do Facebook nos horários que você definir. Roda de graça no GitHub Actions.

## Como funciona

Uma vez por dia (03:00 de Brasília) o robô:

1. lê a pasta e monta a fila com os vídeos que ainda não foram postados;
2. baixa um vídeo para cada horário livre das próximas 30 horas;
3. valida o arquivo (duração, formato, áudio) e envia para o Facebook;
4. **agenda no próprio Facebook** com `scheduled_publish_time`;
5. commita em `state/posted.json` o que foi usado.

Quem publica no horário exato é o Facebook, não o GitHub. Se o Actions atrasar
ou cair, os posts já estão agendados lá dentro. O run das 12:00 UTC é rede de
segurança: pega o que o da madrugada não conseguiu.

**Nada é postado duas vezes.** Cada vídeo e cada horário ficam marcados no
`state/posted.json`; rodar o workflow dez vezes no mesmo dia não duplica post.

---

## Instalação

### 1. Subir para o GitHub

Crie um repositório **privado** e suba esta pasta.

```powershell
cd "c:\Users\pedro\Projetos pedro\fb-autoposter"
git init
git add .
git commit -m "postador automatico"
gh repo create fb-autoposter --private --source=. --push
```

### 2. Acesso ao Google Drive

1. Acesse <https://console.cloud.google.com> e crie um projeto.
2. **APIs e serviços → Biblioteca →** ative a **Google Drive API**.
3. **APIs e serviços → Credenciais → Criar credenciais → Conta de serviço.**
4. Na conta criada, aba **Chaves → Adicionar chave → Criar nova → JSON.** Baixe o arquivo.
5. Copie o e-mail da conta de serviço (algo como `robo@projeto.iam.gserviceaccount.com`).
6. No Google Drive, **compartilhe a pasta dos vídeos** com esse e-mail como **Leitor**.

### 3. Acesso ao OneDrive (via rclone)

A Microsoft cortou o acesso anônimo a links de compartilhamento em contas
migradas para o SharePoint Online, e conta pessoal não consegue registrar app no
Azure ("criar aplicativos fora de um diretório foi preterida"). O rclone resolve
os dois problemas: ele tem registro próprio na Microsoft.

**a) Instalar:**
```powershell
winget install Rclone.Rclone
```

**b) Conectar a conta** (uma vez só):
```powershell
rclone config
```
- `n` (new remote) → nome: **onedrive**
- tipo: procure o número de **Microsoft OneDrive**
- `client_id` e `client_secret`: deixe **vazios** (Enter) — é o que usa o registro do rclone
- region: `1` (global)
- "Edit advanced config?": `n`
- "Use web browser to automatically authenticate?": `y` → autorize na janela que abrir
- tipo de conta: **OneDrive Personal**
- confirme o drive encontrado e finalize com `q`

**c) Testar e descobrir o caminho da pasta:**
```powershell
rclone lsd onedrive:
rclone lsjson --files-only "onedrive:Videos/Daily Blessings"
```

**d) Levar a configuração para o GitHub:** abra o arquivo abaixo e copie o
conteúdo inteiro para o secret `RCLONE_CONF`.
```powershell
rclone config file    # mostra onde está o rclone.conf
notepad "$env:APPDATA\rclone\rclone.conf"
```

**e) `PAGE1_SOURCE`** recebe o caminho da pasta no formato
`onedrive:Videos/Daily Blessings`.

> O mesmo mecanismo serve para Dropbox, Mega, Google Drive, S3 e outros: basta
> configurar outro remote e apontar `PAGE1_SOURCE` para ele.

### 4. Token da Página do Facebook

1. Em <https://developers.facebook.com/apps> crie um app do tipo **Business**.
2. Abra o **Graph API Explorer**, selecione seu app e peça estas permissões:
   `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `publish_video`.
3. Gere o token de usuário e clique em **Generate Access Token**.
4. Abra o **Access Token Debug Tool** e clique em **Extend Access Token** (vira 60 dias).
5. Com esse token estendido, chame `GET /me/accounts` no Explorer. O campo
   `access_token` de cada Página é o **Page Access Token** — esse **não expira**.
6. Anote também o `id` da Página.

> Com o app em modo de desenvolvimento já funciona, desde que você seja admin do
> app e da Página. Não precisa passar por App Review para postar nas suas próprias Páginas.

### 5. Cadastrar os segredos

No repositório: **Settings → Secrets and variables → Actions → New repository secret.**

| Secret | Conteúdo |
|---|---|
| `FB_USER_TOKEN` | seu token de usuário de longa duração — dá conta de **todas** as páginas |
| `RCLONE_CONF` | conteúdo inteiro do `rclone.conf` |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | só se usar Google Drive |

São **dois secrets no total**, independente de quantas páginas você tiver. O
`page_id` e o caminho da pasta ficam no `config.yaml`, porque não são sigilosos.

> Se preferir um token por página, use `token_env: PAGE1_TOKEN` no bloco da
> página e cadastre o secret correspondente. O robô prefere o token específico
> quando ele existe.

### 6. Ajustar o `config.yaml`

Horários, tipo de post (`reel` ou `video`), legenda padrão e hashtags. Depois
commite e faça um teste seco:

**Actions → Postador Facebook → Run workflow → marque "Simular sem publicar".**

Ele mostra exatamente o que faria, sem postar nada.

---

## Adicionar mais páginas

Duplique o bloco no `config.yaml` com o nome, o `page_id`, o fuso e a pasta.
**Não precisa cadastrar secret nenhum**: o `FB_USER_TOKEN` já entrega o token de
todas as páginas que você administra. Só é preciso que a página tenha sido
autorizada quando você gerou o token no Graph API Explorer.

O bloco `defaults` no topo evita repetição — horários, `post_type`, `order` e
hashtags valem para todas as páginas, e cada uma sobrescreve o que quiser:

```yaml
defaults:
  post_type: reel
  times: ["09:00", "13:00", "19:30"]

pages:
  - name: "Bendiciones"
    page_id: "0987654321"
    timezone: America/Mexico_City
    source: "onedrive:Videos/Bendiciones"
    times: ["08:00", "20:00"]     # só esta página muda
```

### Minutos do GitHub Actions

Repositório **privado** tem 2.000 minutos/mês grátis. Com ~30 posts por dia, o
consumo fica em torno de 900 min/mês — cabe, mas sem folga. Repositório
**público** tem Actions ilimitado, e os secrets continuam criptografados e
inacessíveis (inclusive em forks). Se a conta de minutos apertar, tornar o
repositório público é a solução mais simples.

## Horário por país

Cada página tem o seu próprio `timezone`. Os horários em `times` são sempre
lidos **no fuso daquela página**: `"19:00"` numa página com
`timezone: America/Mexico_City` significa 19:00 no México, não no Brasil. O robô
converte tudo sozinho e ainda acerta o horário de verão de cada país.

| País | timezone |
|---|---|
| Brasil | `America/Sao_Paulo` |
| EUA (leste) | `America/New_York` |
| EUA (oeste) | `America/Los_Angeles` |
| México | `America/Mexico_City` |
| França | `Europe/Paris` |
| Portugal | `Europe/Lisbon` |

Página sem `timezone` usa o `timezone` global do topo do arquivo.

## Legendas

- Coloque um `.txt` com o **mesmo nome do vídeo** na pasta (`historia01.mp4` →
  `historia01.txt`) e o conteúdo vira a legenda.
- Sem `.txt`, usa o `default_caption` do config.
- Sem nenhum dos dois, usa o nome do arquivo.
- As `hashtags` do config são anexadas no fim (sem duplicar).

## Ordem de postagem

`order` no config: `name` (alfabética — use `01_`, `02_` nos nomes), `created`
(data de upload) ou `random_stable` (embaralhada, mas sempre igual).

## Comandos locais

```powershell
cd "c:\Users\pedro\Projetos pedro\fb-autoposter"
.\.venv\Scripts\python.exe -m tools.selftest    # testa a lógica interna
.\.venv\Scripts\python.exe -m tools.simulate    # simula o fluxo completo
.\.venv\Scripts\python.exe -m tools.check       # valida token e pasta de verdade
$env:DRY_RUN="1"; .\.venv\Scripts\python.exe -m src.main   # ensaio sem publicar
```

Para rodar `tools.check` localmente, exporte os mesmos nomes de secret:

```powershell
$env:PAGE1_ID="123..."; $env:PAGE1_TOKEN="EAAG..."; $env:PAGE1_SOURCE="1AbC..."
$env:GOOGLE_SERVICE_ACCOUNT_FILE="C:\caminho\service-account.json"
```

---

## Diagnóstico de público

Antes de limpar qualquer coisa, veja se vale a pena:

```powershell
.\.venv\Scripts\python.exe -m tools.publico
```

Mostra **seguidores por país** e **alcance por país (28 dias)**. A Graph API não
lista seguidores um a um, mas entrega o agregado — e é ele que decide:

- alcance concentrado no mesmo país da base suja → os bots recebem entrega e
  envenenam o sinal; aí limpar tem efeito
- alcance no país certo, base suja inerte → limpar não muda nada, é 33 dias de
  clique comprando zero

Também vale a **restrição de país** (Configurações da Página → Restrições de
país): não apaga os seguidores existentes, mas torna a Página invisível no país
do farm — os bots atuais param de contar como audiência e novos não conseguem
mais seguir. Instantâneo, oficial, sem risco.

---

## Bloquear seguidores-robô (lista do Painel profissional)

A Graph API não expõe a lista de seguidores — só o navegador tem. `tools/bloquear_seguidores.js`
é um script de console que roda **na aba já aberta** da lista de seguidores.

1. Abra a Página → Painel profissional → Seguidores
2. `F12` → aba Console → cole o conteúdo de `tools/bloquear_seguidores.js` → Enter
3. Modo `"listar"` (padrão) rola a lista toda e baixa `seguidores.csv`. Não clica em nada.
4. Confira o CSV, cole os nomes ruins em `ALVOS`, troque `MODO` para `"bloquear"`, rode de novo.
5. Para abortar no meio: digite `PARAR = true` no console.

`LOTE` é o orçamento de bloqueios por execução (padrão 300 ≈ 19 min) e há pausa
aleatória de 1,2–2,6 s entre ações. O modo `"bloquear"` trabalha em **janela
rolante**: nunca pré-carrega a lista (com 10 mil seguidores isso trava o
navegador), pega só o que está visível no topo, bloqueia e deixa a lista subir.

O script vigia a tela e **para sozinho** se o Facebook exibir "você está indo
rápido demais" / "temporariamente bloqueado". Se isso acontecer, espere 24 h e
volte com metade do `LOTE`. Insistir depois do aviso é o que vira restrição de conta.

O acumulado fica em `localStorage` (`antibot_placar`), então dá para retomar
todo dia e acompanhar o progresso.

**Antes de encarar milhares:** remover 10 mil seguidores em ritmo seguro leva
~33 dias e deixa a página com zero seguidores — o mesmo ponto de partida de uma
página nova, que custa 5 minutos. Só compensa se a página tiver algo não-portável.

---

## Se os seguidores forem Páginas: bloqueio pela API

ID de Página é **público**, e o edge `/blocked` aceita *"User or Page IDs"*. Então,
quando os seguidores-robô são Páginas, o navegador só precisa **ler** os ids e o
bloqueio acontece pela API oficial — 50 por chamada, sem clique nenhum.

```powershell
# 1. no console, MODO = "listar" -> baixa seguidores.csv (só leitura)
# 2. classifica: quem é Página resolve pela Graph, perfil pessoal não
.\.venv\Scripts\python.exe -m tools.bloquear_ids seguidores.csv
# 3. bloqueia as Páginas
.\.venv\Scripts\python.exe -m tools.bloquear_ids seguidores.csv --aplicar
# desfazer
.\.venv\Scripts\python.exe -m tools.bloquear_ids --desfazer --pagina "Nome"
```

Os que **não** resolvem são perfis pessoais (id escopado, a Graph não devolve) e
saem em `state/perfis_pessoais.csv` — esses só pelo caminho do clique.

---

## Limpeza de bots nos comentários

`tools.antibot` varre os comentários dos posts recentes, pontua cada autor por
sinais de robô e bloqueia em massa via `POST /{page-id}/blocked`.

```powershell
.\.venv\Scripts\python.exe -m tools.antibot                    # relatório, não altera nada
.\.venv\Scripts\python.exe -m tools.antibot --posts 60          # varredura mais funda
.\.venv\Scripts\python.exe -m tools.antibot --limiar 4          # mais rigoroso
.\.venv\Scripts\python.exe -m tools.antibot --aplicar           # bloqueia de verdade
.\.venv\Scripts\python.exe -m tools.antibot --aplicar --apagar  # bloqueia e apaga os comentários
.\.venv\Scripts\python.exe -m tools.antibot --listar            # quem já está bloqueado
.\.venv\Scripts\python.exe -m tools.antibot --desfazer          # desfaz o que a ferramenta bloqueou
```

Sinais e pontos: link externo (4), telefone (3), termo de golpe — recuperação de
conta, cripto, WhatsApp/Telegram, adulto — (3 por categoria), mesmo texto em
3+ posts (4 / 6+ posts (6) / 10+ posts (8)), 5 comentários em 60 s (3),
12+ comentários na varredura (2), nome com 4+ dígitos (1). Limiar padrão: 5.

- Sem `--aplicar` nada muda: sai relatório na tela e `state/antibot_relatorio.csv`.
- Quem já foi bloqueado fica em `state/bloqueados.json` e não é reprocessado.
- `state/nunca_bloquear.json` é uma lista de PSIDs que a ferramenta nunca toca.
- Exige o token com `pages_manage_metadata` (erro 283 = reconectar o perfil no painel).
- A Graph API **não** expõe a lista de seguidores — só dá para agir sobre quem comenta.

---

## Proteções contra falha

| Situação | O que acontece |
|---|---|
| GitHub Actions atrasa ou cai | Irrelevante: os posts já estão agendados no Facebook |
| Upload cai no meio | Retoma do ponto onde parou, não reenvia do zero |
| Graph API instável | 4 tentativas com espera crescente (5s, 10s, 20s) |
| 3 falhas seguidas | Aborta a página e falha o workflow — você recebe e-mail do GitHub |
| Vídeo fora do padrão de Reels | Pulado com aviso; o horário recebe o próximo da fila |
| Vídeo dá erro ao publicar | Volta para o fim da fila; após 2 tentativas fica para o dia seguinte |
| Dois runs simultâneos | `concurrency` do workflow impede |
| Token perto de expirar | Aviso no log a partir de 10 dias antes |
| Pasta esgotada | Avisa e para (ou recomeça, se `recycle_when_empty: true`) |

## Requisitos do Reels

3 a 90 segundos, vertical 9:16, mínimo 1080x1920, com áudio. Fora disso o robô
avisa antes de enviar. Para vídeos maiores ou horizontais use `post_type: video`.

## Problemas comuns

**"Secret ausente"** — nome do secret no GitHub diferente do que está no
`config.yaml` (`page_id_env`, `token_env`, `source.env`).

**Erro 190 (token inválido)** — o token expirou ou foi revogado. Refaça o passo 4.
Sinal comum: você trocou a senha do Facebook.

**Erro 200 (sem permissão)** — faltou `pages_manage_posts`, ou o token é de
usuário e não de Página.

**404 no OneDrive** — o link não está como "qualquer pessoa com o link".

**Drive retorna 0 vídeos** — a pasta não foi compartilhada com o e-mail da conta
de serviço, ou o link/ID no secret é de outra pasta.

**Nada postou e o log diz "nada a fazer agora"** — todos os horários da janela
já estão preenchidos. Confira em `state/posted.json`.
