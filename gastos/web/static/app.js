// Front do Controle de Gastos: conversa com a própria API usando fetch().
// Todo texto vindo da API entra na página com textContent, que não interpreta HTML,
// então uma descrição como "<script>..." aparece como texto e não é executada.

const estado = {
  mes: mesDeHoje(), // "" = todos os meses
  editando: null, // o gasto sendo editado, ou null quando o formulário é de "novo gasto"
};

const $ = (seletor) => document.querySelector(seletor);

// Cria um elemento: el("span", { class: "x", text: "oi" }, filho1, filho2)
function el(tag, { class: classe, text, ...atributos } = {}, ...filhos) {
  const elemento = document.createElement(tag);
  if (classe) elemento.className = classe;
  if (text !== undefined) elemento.textContent = text;
  for (const [nome, valor] of Object.entries(atributos)) elemento.setAttribute(nome, valor);
  elemento.append(...filhos);
  return elemento;
}

// Ícones da Lucide (lucide.dev, licença ISC): cada um é uma lista de caminhos SVG.
const ICONES = {
  editar: [
    "M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z",
    "m15 5 4 4",
  ],
  remover: [
    "M3 6h18",
    "M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6",
    "M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2",
    "M10 11v6",
    "M14 11v6",
  ],
};

// Botão só com ícone; o rótulo vai no aria-label (leitor de tela) e no title (dica do mouse).
function botaoIcone(icone, rotulo, aoClicar) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  for (const [nome, valor] of Object.entries({
    viewBox: "0 0 24 24", width: "18", height: "18", fill: "none", stroke: "currentColor",
    "stroke-width": "2", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true",
  })) svg.setAttribute(nome, valor);
  for (const d of ICONES[icone]) {
    const caminho = document.createElementNS("http://www.w3.org/2000/svg", "path");
    caminho.setAttribute("d", d);
    svg.append(caminho);
  }
  const botao = el("button", {
    class: `botao-icone botao-icone--${icone}`, type: "button", "aria-label": rotulo, title: rotulo,
  }, svg);
  botao.addEventListener("click", aoClicar);
  return botao;
}

// ---------- Datas e dinheiro ----------

function hojeISO() {
  // toISOString() usaria o fuso UTC: às 22h no Brasil já seria "amanhã".
  const agora = new Date();
  const mes = String(agora.getMonth() + 1).padStart(2, "0");
  const dia = String(agora.getDate()).padStart(2, "0");
  return `${agora.getFullYear()}-${mes}-${dia}`;
}

function mesDeHoje() {
  return hojeISO().slice(0, 7);
}

const MESES = [
  "janeiro", "fevereiro", "março", "abril", "maio", "junho",
  "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
];

function nomeDoMes(mes) {
  const [ano, numero] = mes.split("-");
  return `${MESES[Number(numero) - 1]} de ${ano}`;
}

function formatarData(iso) {
  const [ano, mes, dia] = iso.split("-");
  return `${dia}/${mes}/${ano}`;
}

const formatoReais = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });

// A API manda o valor como texto ("45.90"). Aqui ele só vira número para ser exibido.
function formatarReais(texto) {
  return formatoReais.format(Number(texto));
}

// Aceita "45,90", "45.90", "1.234,56" e "1234". Devolve "45.90" ou null se for inválido.
function lerValor(texto) {
  let limpo = texto.trim().replace(/\s|R\$/g, "");
  if (limpo.includes(",")) limpo = limpo.replace(/\./g, "").replace(",", ".");
  if (!/^\d+(\.\d{1,2})?$/.test(limpo) || Number(limpo) <= 0) return null;
  return limpo;
}

// ---------- Conversa com a API ----------

async function api(caminho, opcoes = {}) {
  const resposta = await fetch(caminho, {
    headers: { "Content-Type": "application/json" },
    ...opcoes,
  });
  if (resposta.status === 204) return null;
  const dados = await resposta.json().catch(() => null);
  if (!resposta.ok) throw new Error(mensagemDeErro(dados, resposta.status));
  return dados;
}

// Os erros de validação do Pydantic vêm em inglês; os mais comuns ganham tradução.
const TRADUCOES = {
  decimal_parsing: "Valor inválido",
  greater_than: "O valor precisa ser maior que zero",
  decimal_max_places: "Use no máximo 2 casas decimais (centavos)",
  decimal_max_digits: "Valor grande demais",
  string_too_short: "Preencha a categoria",
  string_too_long: "Texto grande demais",
  date_from_datetime_parsing: "Data inválida",
  greater_than_equal: "O dia vai de 1 a 31",
  less_than_equal: "O dia vai de 1 a 31",
};

function mensagemDeErro(dados, codigo) {
  const detalhe = dados?.detail;
  if (typeof detalhe === "string") return detalhe;
  // Erros de validação (422) vêm como lista; mostramos o primeiro.
  if (Array.isArray(detalhe) && detalhe[0]) {
    return TRADUCOES[detalhe[0].type] ?? detalhe[0].msg.replace("Value error, ", "");
  }
  return `Algo deu errado (erro ${codigo}).`;
}

// ---------- Mensagens rápidas ----------

let temporizadorMensagem;

function mostrarMensagem(texto, erro = false) {
  const caixa = $("#mensagem");
  caixa.textContent = texto;
  caixa.classList.toggle("mensagem--erro", erro);
  caixa.hidden = false;
  clearTimeout(temporizadorMensagem);
  temporizadorMensagem = setTimeout(() => (caixa.hidden = true), erro ? 5000 : 3500);
}

// ---------- Período ----------

async function carregarMeses() {
  const meses = new Set(await api("/meses"));
  meses.add(mesDeHoje());
  if (estado.mes) meses.add(estado.mes);
  const ordenados = [...meses].sort().reverse();
  $("#mes").replaceChildren(
    ...ordenados.map((mes) => el("option", { value: mes, text: nomeDoMes(mes) })),
    el("option", { value: "", text: "Todos os meses" }),
  );
  $("#mes").value = estado.mes;
}

function filtroMes(mes = estado.mes) {
  return mes ? `?mes=${mes}` : "";
}

// ---------- Números e gráfico por categoria ----------

function desenharNumeros(resumo, gastos) {
  const maiorCategoria = resumo.por_categoria[0];
  const maiorGasto = gastos.reduce(
    (maior, g) => (!maior || Number(g.valor) > Number(maior.valor) ? g : maior),
    null,
  );
  const numeros = [
    [formatarReais(resumo.total), estado.mes ? "total do mês" : "total geral"],
    [resumo.quantidade, resumo.quantidade === 1 ? "gasto registrado" : "gastos registrados"],
    [maiorCategoria ? maiorCategoria.categoria : "—", "maior categoria"],
    [maiorGasto ? formatarReais(maiorGasto.valor) : "—", "maior gasto"],
  ];
  $("#numeros").replaceChildren(
    ...numeros.map(([valor, rotulo]) =>
      el("div", { class: "numero spot" },
        el("span", { class: "numero__valor", text: valor }),
        el("span", { class: "numero__rotulo", text: rotulo }),
      ),
    ),
  );
}

function desenharBarras(resumo) {
  if (!resumo.por_categoria.length) {
    $("#barras").replaceChildren(el("p", { class: "aviso", text: "Nenhum gasto no período." }));
    return;
  }
  const maior = Number(resumo.por_categoria[0].total);
  $("#barras").replaceChildren(
    ...resumo.por_categoria.map((item) => {
      const cheio = el("div", { class: "trilho__cheio" });
      // A maior categoria ocupa a barra inteira; as outras, proporcionalmente.
      cheio.style.width = `${Math.max((Number(item.total) / maior) * 100, 1)}%`;
      return el("div", { class: "barra" },
        el("div", { class: "barra__topo" },
          el("span", { text: item.categoria }),
          el("span", { class: "barra__valor", text: formatarReais(item.total) },
            el("small", { text: `${item.porcentagem}%` })),
        ),
        el("div", { class: "trilho", "aria-hidden": "true" }, cheio),
      );
    }),
  );
}

// ---------- Lista de gastos ----------

function desenharGastos(gastos) {
  const aviso = $("#aviso-lista");
  const vazio = gastos.length === 0;
  aviso.hidden = !vazio;
  $("#tabela").hidden = vazio;
  if (vazio) {
    aviso.textContent = estado.mes
      ? `Nenhum gasto em ${nomeDoMes(estado.mes)}. Adicione o primeiro pelo formulário Novo gasto.`
      : "Nenhum gasto registrado ainda. Adicione o primeiro pelo formulário Novo gasto.";
    return;
  }
  // A API devolve em ordem cronológica; na tela, o mais recente vem primeiro.
  const recentes = [...gastos].reverse();
  $("#linhas").replaceChildren(
    ...recentes.map((gasto) => {
      const nome = gasto.descricao || gasto.categoria;
      const editar = botaoIcone("editar", `Editar ${nome} (${formatarData(gasto.data)})`,
        () => comecarEdicao(gasto));
      const remover = botaoIcone("remover", `Remover ${nome} (${formatarData(gasto.data)})`,
        () => removerGasto(gasto));

      const linha = el("tr", {},
        el("td", { class: "tabela__data", text: formatarData(gasto.data) }),
        el("td", { class: "tabela__descricao", text: gasto.descricao || "—" }),
        el("td", { class: "tabela__categoria" }, el("span", { class: "etiqueta", text: gasto.categoria })),
        el("td", { class: "tabela__valor", text: formatarReais(gasto.valor) }),
        el("td", { class: "tabela__acoes" }, editar, remover),
      );
      linha.classList.toggle("linha--editando", estado.editando?.id === gasto.id);
      return linha;
    }),
  );
}

// Na aba Resumo: os 5 mais recentes do período, só para olhar.
function desenharUltimos(gastos) {
  if (!gastos.length) {
    $("#ultimos").replaceChildren(el("li", { class: "aviso", text: "Nenhum gasto no período." }));
    return;
  }
  $("#ultimos").replaceChildren(
    ...[...gastos].reverse().slice(0, 5).map((gasto) =>
      el("li", { class: "ultimo" },
        el("span", { class: "ultimo__info", text: gasto.descricao || gasto.categoria },
          el("small", { text: `${formatarData(gasto.data)} · ${gasto.categoria}` })),
        el("span", { class: "ultimo__valor", text: formatarReais(gasto.valor) }),
      ),
    ),
  );
}

async function removerGasto(gasto) {
  const descricao = gasto.descricao ? ` (${gasto.descricao})` : "";
  if (!confirm(`Remover o gasto de ${formatarReais(gasto.valor)} em ${gasto.categoria}${descricao}?`)) {
    return;
  }
  try {
    await api(`/gastos/${gasto.id}`, { method: "DELETE" });
    if (estado.editando?.id === gasto.id) cancelarEdicao();
    mostrarMensagem("Gasto removido.");
    await recarregar();
  } catch (erro) {
    mostrarMensagem(erro.message, true);
  }
}

// ---------- Formulário (novo gasto e edição) ----------

function comecarEdicao(gasto) {
  estado.editando = gasto;
  $("#valor").value = gasto.valor.replace(".", ",");
  $("#categoria").value = gasto.categoria;
  $("#descricao").value = gasto.descricao;
  $("#data").value = gasto.data;
  $("#titulo-form").textContent = `Editar gasto nº ${gasto.id}`;
  $("#botao-salvar").textContent = "Salvar alterações";
  $("#botao-cancelar").hidden = false;
  $("#form-gasto").classList.add("formulario--editando");
  document.querySelectorAll("#linhas tr").forEach((tr) => tr.classList.remove("linha--editando"));
  $("#form-gasto").scrollIntoView({ behavior: "smooth", block: "center" });
  $("#valor").focus({ preventScroll: true });
}

function cancelarEdicao() {
  estado.editando = null;
  $("#form-gasto").reset();
  $("#data").value = hojeISO();
  $("#titulo-form").textContent = "Novo gasto";
  $("#botao-salvar").textContent = "Adicionar";
  $("#botao-cancelar").hidden = true;
  $("#form-gasto").classList.remove("formulario--editando");
  document.querySelectorAll("#linhas tr").forEach((tr) => tr.classList.remove("linha--editando"));
}

function marcarInvalido(campo, invalido) {
  campo.setAttribute("aria-invalid", invalido ? "true" : "false");
}

async function salvarGasto(evento) {
  evento.preventDefault();
  const valor = lerValor($("#valor").value);
  const categoria = $("#categoria").value.trim();
  marcarInvalido($("#valor"), !valor);
  marcarInvalido($("#categoria"), !categoria);
  if (!valor) return mostrarMensagem("Digite um valor maior que zero, como 45,90.", true);
  if (!categoria) return mostrarMensagem("Preencha a categoria.", true);

  const dados = {
    valor,
    categoria,
    descricao: $("#descricao").value.trim(),
    data: $("#data").value || hojeISO(),
  };
  const editando = estado.editando;
  try {
    const salvo = editando
      ? await api(`/gastos/${editando.id}`, { method: "PATCH", body: JSON.stringify(dados) })
      : await api("/gastos", { method: "POST", body: JSON.stringify(dados) });
    cancelarEdicao();
    // Se o gasto é de outro mês, a tela passa a mostrar esse mês (senão ele "sumiria").
    const mesDoGasto = salvo.data.slice(0, 7);
    if (estado.mes && estado.mes !== mesDoGasto) estado.mes = mesDoGasto;
    await recarregar();
    const acao = editando ? "atualizado" : "adicionado";
    mostrarMensagem(
      `Gasto ${acao}: ${formatarReais(salvo.valor)} em ${salvo.categoria}.` +
        (await avisoDeOrcamento(salvo)),
    );
    if (!editando) $("#valor").focus();
  } catch (erro) {
    mostrarMensagem(erro.message, true);
  }
}

// A API manda o aviso como o terminal mostra ("ATENÇÃO: sobram R$ 27,70"): lá a caixa alta
// destaca a linha. Na página a cor já destaca, então o texto vai em frase normal, montado
// aqui a partir do nível e do restante (a API continua igual para quem a usa).
function textoDoAviso(situacao) {
  const restante = Number(situacao.restante);
  if (situacao.nivel === "estourou") return `Estourou em ${formatarReais(-restante)}`;
  if (situacao.nivel === "atencao") return `Atenção, sobram ${formatarReais(restante)}`;
  if (situacao.nivel === "ok") return `Sobram ${formatarReais(restante)}`;
  return situacao.aviso; // nível que a página não conhece: usa o texto da API como veio
}

function minusculaNoComeco(texto) {
  return texto[0].toLowerCase() + texto.slice(1);
}

// Igual ao terminal: depois de salvar, avisa se o orçamento da categoria está perto ou estourou.
async function avisoDeOrcamento(gasto) {
  const situacoes = await api(`/orcamentos?mes=${gasto.data.slice(0, 7)}`);
  const situacao = situacoes.find((s) => s.categoria === gasto.categoria);
  return situacao && situacao.nivel !== "ok" ? ` Orçamento: ${minusculaNoComeco(textoDoAviso(situacao))}.` : "";
}

// ---------- Orçamento ----------

function desenharOrcamentos(situacoes, mes) {
  $("#nota-orcamento").textContent = estado.mes
    ? ""
    : `Mostrando ${nomeDoMes(mes)} (o orçamento é sempre de um mês).`;
  if (!situacoes.length) {
    $("#orcamentos").replaceChildren(
      el("p", { class: "aviso", text: "Nenhum limite ainda. Defina o primeiro pelo formulário Definir limite." }),
    );
    return;
  }
  $("#orcamentos").replaceChildren(
    ...situacoes.map((s) => {
      const cheio = el("div", { class: "trilho__cheio" });
      cheio.style.width = `${Math.min(Number(s.gasto) / Number(s.limite), 1) * 100}%`;
      const remover = botaoIcone("remover", `Remover o orçamento de ${s.categoria}`,
        () => removerOrcamento(s.categoria));
      return el("div", { class: `orcamento orcamento--${s.nivel} spot` },
        el("div", { class: "orcamento__topo" },
          el("span", { class: "orcamento__categoria", text: s.categoria }),
          el("span", {
            class: "orcamento__numeros",
            text: `${formatarReais(s.gasto)} de ${formatarReais(s.limite)} (${s.porcentagem}%)`,
          }),
        ),
        el("div", { class: "trilho", "aria-hidden": "true" }, cheio),
        el("div", { class: "orcamento__rodape" },
          el("span", { class: "orcamento__aviso", text: textoDoAviso(s) }),
          remover,
        ),
      );
    }),
  );
}

async function definirOrcamento(evento) {
  evento.preventDefault();
  const categoria = $("#orcamento-categoria").value.trim();
  const limite = lerValor($("#orcamento-limite").value);
  marcarInvalido($("#orcamento-categoria"), !categoria);
  marcarInvalido($("#orcamento-limite"), !limite);
  if (!categoria || !limite) return mostrarMensagem("Preencha a categoria e um limite maior que zero.", true);
  try {
    const salvo = await api(`/orcamentos/${encodeURIComponent(categoria)}`, {
      method: "PUT",
      body: JSON.stringify({ limite }),
    });
    evento.target.reset();
    mostrarMensagem(`Orçamento de ${salvo.categoria}: ${formatarReais(salvo.limite)} por mês.`);
    await recarregar();
  } catch (erro) {
    mostrarMensagem(erro.message, true);
  }
}

async function removerOrcamento(categoria) {
  if (!confirm(`Remover o orçamento de ${categoria}?`)) return;
  try {
    await api(`/orcamentos/${encodeURIComponent(categoria)}`, { method: "DELETE" });
    mostrarMensagem(`Orçamento de ${categoria} removido.`);
    await recarregar();
  } catch (erro) {
    mostrarMensagem(erro.message, true);
  }
}

// ---------- Recorrentes ----------

function desenharRecorrentes(recorrentes) {
  $("#aviso-recorrentes").hidden = recorrentes.length > 0;
  $("#lista-recorrentes").replaceChildren(
    ...recorrentes.map((r) => {
      const remover = botaoIcone("remover", `Remover o gasto recorrente de ${r.categoria}`,
        () => removerRecorrente(r));
      return el("li", { class: "recorrente spot" },
        el("span", { class: "recorrente__info", text: `${formatarReais(r.valor)} em ${r.categoria}` },
          el("small", { text: `todo dia ${r.dia} · próximo: ${formatarData(r.proxima_data)}` })),
        remover,
      );
    }),
  );
}

async function criarRecorrente(evento) {
  evento.preventDefault();
  const valor = lerValor($("#recorrente-valor").value);
  const categoria = $("#recorrente-categoria").value.trim();
  const dia = Number($("#recorrente-dia").value);
  const diaValido = Number.isInteger(dia) && dia >= 1 && dia <= 31;
  marcarInvalido($("#recorrente-valor"), !valor);
  marcarInvalido($("#recorrente-categoria"), !categoria);
  marcarInvalido($("#recorrente-dia"), !diaValido);
  if (!valor || !categoria || !diaValido) {
    return mostrarMensagem("Preencha valor, categoria e um dia de 1 a 31.", true);
  }
  try {
    const salvo = await api("/recorrentes", {
      method: "POST",
      body: JSON.stringify({ valor, categoria, dia }),
    });
    evento.target.reset();
    mostrarMensagem(`Recorrente criado. Primeiro lançamento: ${formatarData(salvo.proxima_data)}.`);
    await recarregar();
  } catch (erro) {
    mostrarMensagem(erro.message, true);
  }
}

async function removerRecorrente(r) {
  if (!confirm(`Parar de lançar ${formatarReais(r.valor)} em ${r.categoria} todo mês? Os gastos já lançados continuam.`)) {
    return;
  }
  try {
    await api(`/recorrentes/${r.id}`, { method: "DELETE" });
    mostrarMensagem("Gasto recorrente removido.");
    await recarregar();
  } catch (erro) {
    mostrarMensagem(erro.message, true);
  }
}

// ---------- Importação (CSV do Nubank ou OFX) ----------

// arquivo: o último escolhido, para refazer a prévia quando os nomes mudam.
const importacao = { arquivo: null, novos: [], camposCategoria: [], marcados: [] };

async function lerArquivo(evento) {
  const arquivo = evento.target.files[0];
  evento.target.value = ""; // permite escolher o mesmo arquivo de novo depois
  if (!arquivo) return;
  if (arquivo.size > 2_000_000) {
    return mostrarMensagem("Arquivo grande demais (o máximo é 2 MB).", true);
  }
  importacao.arquivo = arquivo;
  await pedirPrevia();
}

async function pedirPrevia() {
  const arquivo = importacao.arquivo;
  try {
    // O arquivo vai como veio (bytes): quem descobre o formato e a codificação é a API.
    const previa = await api("/importar/previa", {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: arquivo,
    });
    mostrarPrevia(previa, arquivo.name);
  } catch (erro) {
    esconderPrevia();
    mostrarMensagem(erro.message, true);
  }
}

function plural(n, singular, varios) {
  return `${n} ${n === 1 ? singular : varios}`;
}

function mostrarPrevia(previa, nomeDoArquivo) {
  importacao.novos = previa.novos;
  importacao.camposCategoria = previa.novos.map((item) => {
    const campo = el("input", {
      class: "campo campo--pequeno", list: "lista-categorias", maxlength: "40",
      "aria-label": `Categoria de ${item.descricao || "gasto"}` +
        (item.lembrada ? " (a mesma que você já usou para esta loja)" : ""),
    });
    campo.value = item.categoria;
    if (item.lembrada) campo.title = "Categoria que você já usou para esta loja";
    return campo;
  });

  const lembradas = previa.novos.filter((item) => item.lembrada).length;
  const partes = [
    plural(previa.novos.length, "gasto novo", "gastos novos"),
    plural(previa.repetidos, "já importado antes", "já importados antes"),
    plural(previa.ignorados.length, "ignorado", "ignorados"),
  ];
  $("#previa-resumo").replaceChildren(
    el("strong", { text: previa.formato[0].toUpperCase() + previa.formato.slice(1) }),
    `, arquivo ${nomeDoArquivo}: ${partes.join(" · ")}.`,
    previa.novos.length ? " Confira as categorias antes de importar." : " Nada novo para importar.",
    lembradas
      ? ` ${lembradas === 1 ? "Uma categoria veio" : `${lembradas} categorias vieram`} de gastos` +
        " seus da mesma loja (marcadas com •)."
      : "",
  );

  $("#previa-tabela").hidden = previa.novos.length === 0;
  // Cada linha começa marcada; desmarcar deixa o gasto de fora da importação.
  importacao.marcados = previa.novos.map((item) => {
    const caixa = el("input", {
      type: "checkbox", "aria-label": `Importar ${item.descricao || "gasto"}`,
    });
    caixa.checked = true;
    caixa.addEventListener("change", () => {
      caixa.closest("tr").classList.toggle("pulada", !caixa.checked);
      atualizarBotaoImportar();
    });
    return caixa;
  });
  $("#previa-linhas").replaceChildren(
    ...previa.novos.map((item, i) =>
      el("tr", {},
        el("td", { class: "tabela__marcar" }, importacao.marcados[i]),
        el("td", { class: "tabela__data", text: formatarData(item.data) }),
        el("td", { class: "tabela__descricao", text: item.descricao || "—" }),
        el("td", { class: "tabela__categoria" },
          importacao.camposCategoria[i],
          item.lembrada ? el("span", { class: "lembrada", text: " •", "aria-hidden": "true" }) : "",
        ),
        el("td", { class: "tabela__valor", text: formatarReais(item.valor) }),
      ),
    ),
  );

  $("#previa-ignorados").hidden = previa.ignorados.length === 0;
  $("#previa-ignorados-titulo").textContent =
    `${plural(previa.ignorados.length, "linha ignorada", "linhas ignoradas")} (não são gastos)`;
  $("#previa-ignorados-lista").replaceChildren(
    ...previa.ignorados.map((i) =>
      el("li", {
        text: `${formatarData(i.data)} · ${i.descricao} · ` +
          `${formatarReais(Math.abs(Number(i.valor)))}: ${i.motivo}`,
      }),
    ),
  );

  atualizarBotaoImportar();
  $("#previa").hidden = false;
  $("#previa").scrollIntoView({ behavior: "smooth", block: "start" });
}

function atualizarBotaoImportar() {
  const quantos = importacao.marcados.filter((caixa) => caixa.checked).length;
  const botao = $("#botao-importar");
  botao.disabled = quantos === 0;
  botao.textContent = quantos ? `Importar ${plural(quantos, "gasto", "gastos")}` : "Importar";
}

function esconderPrevia() {
  importacao.arquivo = null;
  importacao.novos = [];
  importacao.camposCategoria = [];
  importacao.marcados = [];
  $("#previa").hidden = true;
}

async function importarRevisados() {
  const escolhidos = importacao.novos
    .map((item, i) => ({ item, campo: importacao.camposCategoria[i], caixa: importacao.marcados[i] }))
    .filter(({ caixa }) => caixa.checked);
  const itens = escolhidos.map(({ item, campo }) => ({ ...item, categoria: campo.value.trim() }));
  escolhidos.forEach(({ campo }) => marcarInvalido(campo, !campo.value.trim()));
  if (itens.some((item) => !item.categoria)) {
    return mostrarMensagem("Preencha a categoria de todos os gastos.", true);
  }
  const botao = $("#botao-importar");
  botao.disabled = true;
  try {
    const resultado = await api("/importar", { method: "POST", body: JSON.stringify({ itens }) });
    esconderPrevia();
    // Mostra o mês mais recente do extrato (senão os gastos importados poderiam "sumir").
    if (estado.mes) estado.mes = itens.map((item) => item.data.slice(0, 7)).sort().at(-1);
    await recarregar();
    const pulados = resultado.repetidos
      ? ` (${plural(resultado.repetidos, "já estava", "já estavam")} na lista)` : "";
    mostrarMensagem(`${plural(resultado.importados, "gasto importado", "gastos importados")}${pulados}.`);
  } catch (erro) {
    botao.disabled = false;
    mostrarMensagem(erro.message, true);
  }
}

// ---------- Meus nomes (Pix para outra conta sua não é gasto) ----------

function desenharMeusNomes(nomes) {
  $("#meus-nomes-titulo").textContent = nomes.length
    ? `Pix para outra conta sua (${plural(nomes.length, "nome cadastrado", "nomes cadastrados")})`
    : "Pix para outra conta sua";
  $("#meus-nomes-lista").replaceChildren(
    ...nomes.map((nome) => {
      const remover = botaoIcone("remover", `Remover o nome ${nome}`, () => mudarMeusNomes(
        () => api(`/importar/meus-nomes/${encodeURIComponent(nome)}`, { method: "DELETE" }),
      ));
      return el("li", {}, el("span", { text: nome }), remover);
    }),
  );
}

async function adicionarMeuNome(evento) {
  evento.preventDefault();
  const campo = $("#campo-meu-nome");
  const ok = await mudarMeusNomes(() => api("/importar/meus-nomes", {
    method: "POST", body: JSON.stringify({ nome: campo.value }),
  }));
  if (ok) campo.value = "";
}

// Faz a mudança, redesenha a lista e, se houver prévia aberta, refaz com os nomes novos.
async function mudarMeusNomes(mudanca) {
  try {
    await mudanca();
    desenharMeusNomes(await api("/importar/meus-nomes"));
    if (importacao.arquivo) await pedirPrevia();
    return true;
  } catch (erro) {
    mostrarMensagem(erro.message, true);
    return false;
  }
}

// ---------- Conta (login, só na versão online) ----------

const conta = { modo: "entrar", cadastroAberto: false };

async function atualizarSessao() {
  const info = await api("/info");
  conta.cadastroAberto = info.cadastro;
  $("#aviso-demo").hidden = !info.demo;
  // "Entrar" só aparece na versão online (visitante da demo); no computador não há login.
  $("#botao-entrar").hidden = !info.demo;
  $("#botao-conta").hidden = !info.email;
  if (info.email) {
    $("#botao-conta").textContent = info.email;
    $("#conta-email").textContent = info.email;
  }
}

function trocarModo(modo) {
  conta.modo = modo;
  const cadastro = modo === "cadastro";
  document.querySelectorAll(".aba-janela").forEach((aba) => {
    const ativa = aba.dataset.modo === modo;
    aba.classList.toggle("aba-janela--ativa", ativa);
    aba.setAttribute("aria-selected", ativa);
  });
  $("#titulo-entrar").textContent = cadastro ? "Criar conta" : "Entrar";
  $("#botao-enviar-entrar").textContent = cadastro ? "Criar conta" : "Entrar";
  $("#rotulo-convite").hidden = !cadastro;
  $("#nota-cadastro").hidden = !cadastro;
  // Diz ao gerenciador de senhas do navegador se é para sugerir uma senha nova.
  $("#entrar-senha").autocomplete = cadastro ? "new-password" : "current-password";
  $("#erro-entrar").hidden = true;
}

function abrirJanelaEntrar() {
  $("#abas-janela").hidden = !conta.cadastroAberto;
  trocarModo("entrar");
  $("#form-entrar").reset();
  $("#janela-entrar").showModal();
  $("#entrar-email").focus();
}

function mostrarErro(seletor, texto) {
  $(seletor).textContent = texto;
  $(seletor).hidden = false;
}

async function enviarEntrar(evento) {
  evento.preventDefault();
  const cadastro = conta.modo === "cadastro";
  const dados = { email: $("#entrar-email").value, senha: $("#entrar-senha").value };
  if (!dados.email.trim() || !dados.senha) return mostrarErro("#erro-entrar", "Preencha o e-mail e a senha.");
  if (cadastro) {
    if (dados.senha.length < 8) return mostrarErro("#erro-entrar", "A senha precisa ter pelo menos 8 caracteres.");
    dados.convite = $("#entrar-convite").value.trim();
    if (!dados.convite) return mostrarErro("#erro-entrar", "Digite o código de convite.");
  }
  const botao = $("#botao-enviar-entrar");
  botao.disabled = true;
  try {
    await api(cadastro ? "/conta/cadastro" : "/conta/entrar", { method: "POST", body: JSON.stringify(dados) });
    // A sessão muda de conta: recarregar a página é o jeito mais simples de mostrar tudo certo.
    location.reload();
  } catch (erro) {
    botao.disabled = false;
    mostrarErro("#erro-entrar", erro.message);
  }
}

async function sairDaConta() {
  try {
    await api("/conta/sair", { method: "POST" });
    location.reload();
  } catch (erro) {
    mostrarMensagem(erro.message, true);
  }
}

async function excluirConta(evento) {
  evento.preventDefault();
  const senha = $("#excluir-senha").value;
  if (!senha) return mostrarErro("#erro-excluir", "Digite sua senha.");
  if (!confirm("Excluir a conta e todos os seus dados? Isso não pode ser desfeito.")) return;
  try {
    await api("/conta/excluir", { method: "POST", body: JSON.stringify({ senha }) });
    location.reload();
  } catch (erro) {
    mostrarErro("#erro-excluir", erro.message);
  }
}

function iniciarConta() {
  $("#botao-entrar").addEventListener("click", abrirJanelaEntrar);
  $("#botao-conta").addEventListener("click", () => {
    $("#form-excluir").reset();
    $("#erro-excluir").hidden = true;
    $("#janela-conta").showModal();
  });
  document.querySelectorAll(".aba-janela").forEach((aba) =>
    aba.addEventListener("click", () => trocarModo(aba.dataset.modo)));
  document.querySelectorAll("[data-fechar]").forEach((botao) =>
    botao.addEventListener("click", () => botao.closest("dialog").close()));
  $("#form-entrar").addEventListener("submit", enviarEntrar);
  $("#botao-sair").addEventListener("click", sairDaConta);
  $("#form-excluir").addEventListener("submit", excluirConta);
  atualizarSessao().catch(() => {}); // sem isso, a página continua funcionando
}

// ---------- Abas (igual ao portfólio: cada função numa aba, escolhida pelo endereço) ----------

const abas = [...document.querySelectorAll("main > .aba")];
const linksAbas = document.querySelectorAll(".abas__link");
const pilula = $("#abas-pilula");
// O período não muda nada nos recorrentes nem na importação; lá ele fica escondido.
const ABAS_SEM_PERIODO = ["recorrentes", "importar"];
let abasIniciadas = false;
let trocaAtual = 0; // ao clicar rápido em várias abas, só a última troca vale

// No celular a barra de abas rola de lado: a ponta que ainda tem abas escondidas
// fica esmaecida, para mostrar que dá para rolar (no começo, "Importar" fica fora da tela).
const barraAbas = $(".abas");
function marcarPontasDasAbas() {
  const sobraDireita = barraAbas.scrollWidth - barraAbas.clientWidth - barraAbas.scrollLeft;
  barraAbas.classList.toggle("abas--mais-esquerda", barraAbas.scrollLeft > 2);
  barraAbas.classList.toggle("abas--mais-direita", sobraDireita > 2);
}

// Pílula do menu desliza até o link da aba ativa
function moverPilula() {
  marcarPontasDasAbas();
  const ativo = document.querySelector(".abas__link--ativo");
  if (!ativo) return;
  pilula.style.width = `${ativo.offsetWidth}px`;
  pilula.style.transform = `translateX(${ativo.offsetLeft}px)`;
}

function mostrarAba(focar) {
  // Os ids das abas são simples (sem acento nem espaço): o hash é comparado como veio,
  // sem decodeURIComponent, que quebraria a página com um endereço como "#%".
  const id = location.hash.slice(1);
  const atual = abas.find((aba) => aba.id === id) ?? abas[0];

  linksAbas.forEach((link) => {
    const ativo = link.getAttribute("href") === `#${atual.id}`;
    link.classList.toggle("abas__link--ativo", ativo);
    if (ativo) {
      link.setAttribute("aria-current", "page");
      // No celular a barra rola de lado: traz a aba escolhida para a vista.
      link.scrollIntoView({ block: "nearest", inline: "nearest" });
    } else {
      link.removeAttribute("aria-current");
    }
  });
  moverPilula();
  $("#periodo").classList.toggle("periodo--escondido", ABAS_SEM_PERIODO.includes(atual.id));
  const titulo = atual.querySelector(".aba__titulo");
  document.title = `${titulo.textContent} | Controle de Gastos`;

  const anterior = abasIniciadas && abas.find((aba) => !aba.hidden && aba !== atual);
  const estaTroca = ++trocaAtual;
  abasIniciadas = true;

  function entrar() {
    if (estaTroca !== trocaAtual) return;
    abas.forEach((aba) => {
      aba.hidden = aba !== atual;
      aba.classList.remove("aba--saindo");
    });
    atual.classList.remove("aba--entrando");
    void atual.offsetWidth; // força o navegador a reiniciar a animação
    atual.classList.add("aba--entrando");
    atual.classList.add("animar-barras");
    setTimeout(() => atual.classList.remove("animar-barras"), 1200);
    window.scrollTo({ top: 0, behavior: "instant" });
    if (focar) titulo.focus({ preventScroll: true });
  }

  // A aba anterior some rapidinho antes da nova entrar
  if (anterior) {
    anterior.classList.add("aba--saindo");
    setTimeout(entrar, 150);
  } else {
    entrar();
  }
}

function iniciarAbas() {
  document.documentElement.classList.add("com-abas");
  window.addEventListener("hashchange", () => mostrarAba(true));
  window.addEventListener("resize", moverPilula);
  barraAbas.addEventListener("scroll", marcarPontasDasAbas, { passive: true });
  document.fonts.ready.then(moverPilula);
  // Na primeira vez a pílula já nasce no lugar, sem deslizar a partir do canto
  pilula.style.transition = "none";
  mostrarAba(false);
  void pilula.offsetWidth;
  pilula.style.transition = "";
}

// Brilho que segue o mouse nos cartões (.spot). Um ouvinte só, na página toda,
// porque muitos cartões são recriados a cada recarga.
function iniciarBrilho() {
  document.addEventListener("pointermove", (evento) => {
    const cartao = evento.target.closest?.(".spot");
    if (!cartao) return;
    const caixa = cartao.getBoundingClientRect();
    cartao.style.setProperty("--mx", `${evento.clientX - caixa.left}px`);
    cartao.style.setProperty("--my", `${evento.clientY - caixa.top}px`);
  });
}

// ---------- Carregar tudo ----------

async function recarregar() {
  const mesOrcamento = estado.mes || mesDeHoje();
  // Os pedidos saem juntos (Promise.all) em vez de um esperar o outro.
  const [resumo, gastos, situacoes, recorrentes, categorias, meusNomes] = await Promise.all([
    api(`/resumo${filtroMes()}`),
    api(`/gastos${filtroMes()}`),
    api(`/orcamentos?mes=${mesOrcamento}`),
    api("/recorrentes"),
    api("/categorias"),
    api("/importar/meus-nomes"),
    carregarMeses(),
  ]);
  desenharNumeros(resumo, gastos);
  desenharBarras(resumo);
  desenharGastos(gastos);
  desenharUltimos(gastos);
  desenharOrcamentos(situacoes, mesOrcamento);
  desenharRecorrentes(recorrentes);
  desenharMeusNomes(meusNomes);
  $("#lista-categorias").replaceChildren(...categorias.map((c) => el("option", { value: c })));
  atualizarExportar(gastos.length > 0);
}

// Sem gastos no período, os botões de baixar ficam desativados (baixariam uma planilha vazia).
// Um link não tem "disabled": sem href ele não baixa nada, e o aria-disabled e o title explicam.
function atualizarExportar(temGastos) {
  for (const formato of ["xlsx", "csv"]) {
    const link = $(`#exportar-${formato}`);
    link.classList.toggle("botao--desativado", !temGastos);
    if (temGastos) {
      link.href = `/exportar?formato=${formato}${filtroMes().replace("?", "&")}`;
      link.removeAttribute("aria-disabled");
      link.removeAttribute("title");
      link.removeAttribute("tabindex");
      link.removeAttribute("role");
    } else {
      link.removeAttribute("href");
      link.setAttribute("aria-disabled", "true");
      link.setAttribute("title", "Nenhum gasto no período para baixar");
      // Continua alcançável pelo teclado, para o leitor de tela anunciar o motivo
      link.setAttribute("tabindex", "0");
      link.setAttribute("role", "link");
    }
  }
}

function iniciar() {
  iniciarAbas();
  iniciarBrilho();
  $("#data").value = hojeISO();
  $("#mes").addEventListener("change", (evento) => {
    estado.mes = evento.target.value;
    recarregar().catch((erro) => mostrarMensagem(erro.message, true));
  });
  $("#form-gasto").addEventListener("submit", salvarGasto);
  $("#botao-cancelar").addEventListener("click", cancelarEdicao);
  $("#form-orcamento").addEventListener("submit", definirOrcamento);
  $("#form-recorrente").addEventListener("submit", criarRecorrente);
  $("#arquivo-csv").addEventListener("change", lerArquivo);
  $("#botao-importar").addEventListener("click", importarRevisados);
  $("#form-meu-nome").addEventListener("submit", adicionarMeuNome);
  $("#botao-cancelar-importacao").addEventListener("click", esconderPrevia);
  recarregar().catch((erro) => mostrarMensagem(erro.message, true));
  iniciarConta();
}

iniciar();
