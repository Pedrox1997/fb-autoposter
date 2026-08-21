/* ===========================================================================
   Bloqueio de seguidores-robo direto na lista do Painel profissional.
   Cola no console do navegador (F12 -> Console) COM A LISTA DE SEGUIDORES ABERTA.

   A Graph API nao expoe a lista de seguidores; so o DOM tem. Por isso aqui.

   MODO "listar"   -> nao clica em nada, so baixa um CSV com quem esta na lista.
   MODO "bloquear" -> abre o menu "..." de cada linha e bloqueia, com pausa.

   Fluxo recomendado:
     1. rode em "listar", abra o CSV, confira os nomes
     2. cole os nomes ruins em ALVOS
     3. rode em "bloquear" com LOTE baixo (10) para validar
     4. suba o LOTE

   Para abortar no meio: digite  PARAR = true  no console.
   =========================================================================== */

const MODO  = "listar";   // "listar" | "bloquear"
const LOTE  = 300;        // orcamento de bloqueios por execucao (dia)
const ALVOS = [];         // vazio = todos os visiveis. Ex: ["Hoang Minh Anh", "Tri To Nhu"]

const PAUSA_MIN = 1200;   // ritmo humano entre acoes (ms)
const PAUSA_MAX = 2600;
const ROLAGENS  = 40;     // rolagens no modo "listar" (o modo bloquear nao pre-carrega)

// ---------------------------------------------------------------- utilidades

var PARAR = false;

const dorme = ms => new Promise(r => setTimeout(r, ms));
const pausa = () => dorme(PAUSA_MIN + Math.random() * (PAUSA_MAX - PAUSA_MIN));

// rotulos do menu em varios idiomas - a conta pode estar em pt, en ou es
const RE_MENU     = /mais op|more options|más opciones|ações|actions/i;
const RE_BLOQUEAR = /^(bloquear|block|bloquear do|block from|banir|ban)/i;
const RE_CONFIRMA = /^(bloquear|block|confirmar|confirm|ok)$/i;

// se qualquer um destes textos aparecer na tela, o Facebook travou a acao:
// para NA HORA. Insistir depois de um aviso desses e o que vira restricao.
const RE_TRAVA = new RegExp([
  "temporariamente bloquead", "temporarily blocked", "bloqueado temporalmente",
  "você está indo rápido demais", "going too fast", "slow down",
  "recurso indisponível", "feature (temporarily )?unavailable",
  "tente novamente mais tarde", "try again later",
].join("|"), "i");

function travou() {
  const txt = document.body.innerText || "";
  // olha so o fim do texto visivel para nao casar com conteudo de post antigo
  return RE_TRAVA.test(txt.slice(0, 4000));
}

function visivel(el) {
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0;
}

/** Procura, por ate `tentativas` ciclos, um elemento clicavel cujo texto casa. */
async function esperarClicavel(regex, tentativas = 20) {
  for (let i = 0; i < tentativas; i++) {
    const alvos = [...document.querySelectorAll(
      '[role="menuitem"], [role="button"], [role="menuitemcheckbox"], button')];
    const achado = alvos.find(el => visivel(el) && regex.test((el.innerText || "").trim()));
    if (achado) return achado;
    await dorme(250);
  }
  return null;
}

/** Rola a lista ate parar de crescer, para carregar todos os seguidores. */
async function carregarTudo() {
  let anterior = -1;
  for (let i = 0; i < ROLAGENS; i++) {
    const atual = linhas().length;
    console.log(`  rolando... ${atual} na lista`);
    if (atual === anterior) break;
    anterior = atual;
    window.scrollTo(0, document.body.scrollHeight);
    await dorme(1400);
  }
}

/** Cada linha da lista, ancorada no botao "..." (o unico marcador estavel). */
function linhas() {
  return [...document.querySelectorAll('[aria-label]')]
    .filter(el => RE_MENU.test(el.getAttribute("aria-label") || "") && visivel(el))
    .map(botao => {
      // sobe ate um bloco que contenha o nome e o botao
      let caixa = botao;
      for (let i = 0; i < 8 && caixa.parentElement; i++) {
        caixa = caixa.parentElement;
        if (caixa.innerText && caixa.innerText.trim().length > 2) break;
      }
      const link = caixa.querySelector('a[href*="/profile.php?id="], a[href^="https://www.facebook.com/"], a[href^="/"]');
      const href = link ? link.getAttribute("href") : "";
      const nome = (caixa.innerText || "").trim().split("\n")[0].trim();

      // "ref" e o que a Graph API consegue resolver: o id numerico quando existe,
      // senao o apelido da URL (paginas costumam ter /nome-da-pagina).
      const num = href.match(/profile\.php\?id=(\d+)/) || href.match(/\/(\d{8,})(?:\/|\?|$)/);
      let ref = num ? num[1] : "";
      if (!ref) {
        const caminho = href.replace(/^https?:\/\/(www\.|m\.)?facebook\.com/, "")
                            .split("?")[0].replace(/^\/|\/$/g, "");
        // ignora rotas internas do proprio Facebook
        if (caminho && !/^(profile\.php|people|pages|groups|photo|watch)/.test(caminho)) {
          ref = caminho.split("/")[0];
        }
      }
      return { botao, nome, href: href.split("?")[0], id: ref };
    })
    .filter(l => l.nome && !/^\W*$/.test(l.nome));
}

function baixarCSV(dados) {
  const linhasCsv = [["nome", "ref", "perfil"]].concat(
    dados.map(d => [d.nome, d.id, d.href]));
  const texto = "﻿" + linhasCsv
    .map(l => l.map(c => `"${String(c).replace(/"/g, '""')}"`).join(";")).join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([texto], { type: "text/csv" }));
  a.download = "seguidores.csv";
  a.click();
}

// -------------------------------------------------------------------- acoes

async function bloquear(linha) {
  linha.botao.click();                       // abre o menu "..."
  await dorme(600);

  const item = await esperarClicavel(RE_BLOQUEAR, 12);
  if (!item) {
    document.body.click();                   // fecha o menu e segue
    return "sem opcao de bloquear";
  }
  item.click();
  await dorme(700);

  // a confirmacao nem sempre aparece; se aparecer, confirma
  const confirmar = await esperarClicavel(RE_CONFIRMA, 8);
  if (confirmar) {
    confirmar.click();
    await dorme(600);
  }
  return "ok";
}

// --------------------------------------------------------------------- main

const PLACAR = "antibot_placar";   // total acumulado entre execucoes

(async () => {
  console.log(`=== modo: ${MODO}`);

  if (MODO === "listar") {
    await carregarTudo();
    let lista = linhas();
    if (ALVOS.length) {
      const alvos = new Set(ALVOS.map(n => n.trim().toLowerCase()));
      lista = lista.filter(l => alvos.has(l.nome.toLowerCase()));
    }
    console.log(`${lista.length} seguidores no alvo`);
    console.table(lista.map(l => ({ nome: l.nome, id: l.id, perfil: l.href })));
    baixarCSV(lista);
    console.log("CSV baixado. Nada foi alterado.");
    return;
  }

  // ------------------------------------------------------------------------
  // Janela rolante: com 10 mil seguidores a lista e virtualizada - carregar
  // tudo trava o navegador. Entao nunca pre-carregamos: pegamos so o que esta
  // visivel no topo, bloqueamos, a lista sobe sozinha, repetimos.
  // ------------------------------------------------------------------------
  const alvos = ALVOS.length ? new Set(ALVOS.map(n => n.trim().toLowerCase())) : null;
  const vistos = new Set();          // nomes ja tentados nesta execucao
  let ok = 0, falhas = [], vazios = 0;
  const inicio = Date.now();

  while (ok < LOTE) {
    if (PARAR) { console.log("abortado pelo usuario"); break; }

    if (travou()) {
      console.warn("\n!!! O Facebook travou a acao. PARANDO AGORA.");
      console.warn("Espere 24h antes de rodar de novo e baixe o LOTE pela metade.");
      break;
    }

    let fila = linhas().filter(l => !vistos.has(l.nome));
    if (alvos) fila = fila.filter(l => alvos.has(l.nome.toLowerCase()));

    if (!fila.length) {
      // nada novo na janela: rola um pouco para o virtualizador montar mais
      if (++vazios > 6) { console.log("fim da lista visivel"); break; }
      window.scrollBy(0, 600);
      await dorme(1500);
      continue;
    }
    vazios = 0;

    for (const linha of fila) {
      if (PARAR || ok >= LOTE || travou()) break;
      vistos.add(linha.nome);
      let r;
      try {
        r = await bloquear(linha);
      } catch (e) {
        r = "erro: " + e.message;
      }
      if (r === "ok") ok++; else falhas.push(`${linha.nome}: ${r}`);
      const min = ((Date.now() - inicio) / 60000).toFixed(1);
      console.log(`  [${ok}/${LOTE}] ${linha.nome} -> ${r}  (${min} min)`);
      await pausa();
    }
  }

  const total = (Number(localStorage.getItem(PLACAR)) || 0) + ok;
  localStorage.setItem(PLACAR, total);

  console.log(`\nbloqueados agora: ${ok} | falhas: ${falhas.length}`);
  console.log(`acumulado nesta pagina: ${total}`);
  falhas.slice(0, 20).forEach(f => console.log("  ! " + f));
  console.log("Recarregue a pagina amanha e rode de novo para continuar.");
})();
