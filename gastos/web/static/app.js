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
      el("div", { class: "numero" },
        el("span", { class: "numero__valor", text: valor }),
        el("span", { class: "numero__rotulo", text: rotulo }),
      ),
    ),
  );
}

function desenharBarras(resumo) {
  if (!resumo.por_categoria.length) {
    $("#barras").replaceChildren(el("p", { class: "aviso", text: "Nada para mostrar ainda." }));
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
      ? `Nenhum gasto em ${nomeDoMes(estado.mes)}. Adicione o primeiro no formulário acima.`
      : "Nenhum gasto registrado ainda. Adicione o primeiro no formulário acima.";
    return;
  }
  // A API devolve em ordem cronológica; na tela, o mais recente vem primeiro.
  const recentes = [...gastos].reverse();
  $("#linhas").replaceChildren(
    ...recentes.map((gasto) => {
      const editar = el("button", { class: "botao-texto", type: "button", text: "Editar" });
      editar.addEventListener("click", () => comecarEdicao(gasto));
      const remover = el("button", {
        class: "botao-texto botao-texto--perigo", type: "button", text: "Remover",
      });
      remover.addEventListener("click", () => removerGasto(gasto));

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

// Igual ao terminal: depois de salvar, avisa se o orçamento da categoria está perto ou estourou.
async function avisoDeOrcamento(gasto) {
  const situacoes = await api(`/orcamentos?mes=${gasto.data.slice(0, 7)}`);
  const situacao = situacoes.find((s) => s.categoria === gasto.categoria);
  return situacao && situacao.nivel !== "ok" ? ` Orçamento: ${situacao.aviso}.` : "";
}

// ---------- Orçamento ----------

function desenharOrcamentos(situacoes, mes) {
  $("#nota-orcamento").textContent = estado.mes
    ? ""
    : `Mostrando ${nomeDoMes(mes)} (o orçamento é sempre de um mês).`;
  if (!situacoes.length) {
    $("#orcamentos").replaceChildren(
      el("p", { class: "aviso", text: "Defina um limite mensal para uma categoria abaixo." }),
    );
    return;
  }
  $("#orcamentos").replaceChildren(
    ...situacoes.map((s) => {
      const cheio = el("div", { class: "trilho__cheio" });
      cheio.style.width = `${Math.min(Number(s.gasto) / Number(s.limite), 1) * 100}%`;
      const remover = el("button", {
        class: "botao-texto botao-texto--perigo", type: "button", text: "Remover",
        "aria-label": `Remover o orçamento de ${s.categoria}`,
      });
      remover.addEventListener("click", () => removerOrcamento(s.categoria));
      return el("div", { class: `orcamento orcamento--${s.nivel}` },
        el("div", { class: "orcamento__topo" },
          el("span", { class: "orcamento__categoria", text: s.categoria }),
          el("span", {
            class: "orcamento__numeros",
            text: `${formatarReais(s.gasto)} de ${formatarReais(s.limite)} (${s.porcentagem}%)`,
          }),
        ),
        el("div", { class: "trilho", "aria-hidden": "true" }, cheio),
        el("div", { class: "orcamento__rodape" },
          el("span", { class: "orcamento__aviso", text: s.aviso }),
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
  $("#recorrentes").replaceChildren(
    ...recorrentes.map((r) => {
      const remover = el("button", {
        class: "botao-texto botao-texto--perigo", type: "button", text: "Remover",
        "aria-label": `Remover o gasto recorrente de ${r.categoria}`,
      });
      remover.addEventListener("click", () => removerRecorrente(r));
      return el("li", { class: "recorrente" },
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

// ---------- Importação do Nubank ----------

const importacao = { novos: [], camposCategoria: [] };

async function lerArquivo(evento) {
  const arquivo = evento.target.files[0];
  evento.target.value = ""; // permite escolher o mesmo arquivo de novo depois
  if (!arquivo) return;
  if (arquivo.size > 2_000_000) {
    return mostrarMensagem("Arquivo grande demais (o máximo é 2 MB).", true);
  }
  try {
    // O arquivo vai como veio (bytes): quem confere a codificação (UTF-8) é a API.
    const previa = await api("/importar/previa", {
      method: "POST",
      headers: { "Content-Type": "text/csv" },
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
      "aria-label": `Categoria de ${item.descricao || "gasto"}`,
    });
    campo.value = item.categoria;
    return campo;
  });

  const partes = [
    plural(previa.novos.length, "gasto novo", "gastos novos"),
    plural(previa.repetidos, "já importado antes", "já importados antes"),
    plural(previa.ignorados.length, "ignorado", "ignorados"),
  ];
  $("#previa-resumo").replaceChildren(
    el("strong", { text: previa.formato[0].toUpperCase() + previa.formato.slice(1) }),
    ` (${nomeDoArquivo}): ${partes.join(" · ")}.`,
    previa.novos.length ? " Confira as categorias antes de importar." : " Nada novo para importar.",
  );

  $("#previa-tabela").hidden = previa.novos.length === 0;
  $("#previa-linhas").replaceChildren(
    ...previa.novos.map((item, i) =>
      el("tr", {},
        el("td", { class: "tabela__data", text: formatarData(item.data) }),
        el("td", { class: "tabela__descricao", text: item.descricao || "—" }),
        el("td", { class: "tabela__categoria" }, importacao.camposCategoria[i]),
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

  const botao = $("#botao-importar");
  botao.disabled = previa.novos.length === 0;
  botao.textContent = previa.novos.length
    ? `Importar ${plural(previa.novos.length, "gasto", "gastos")}`
    : "Importar";
  $("#previa").hidden = false;
  $("#previa").scrollIntoView({ behavior: "smooth", block: "start" });
}

function esconderPrevia() {
  importacao.novos = [];
  importacao.camposCategoria = [];
  $("#previa").hidden = true;
}

async function importarRevisados() {
  const itens = importacao.novos.map((item, i) => ({
    ...item,
    categoria: importacao.camposCategoria[i].value.trim(),
  }));
  importacao.camposCategoria.forEach((campo) => marcarInvalido(campo, !campo.value.trim()));
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

// ---------- Carregar tudo ----------

async function recarregar() {
  const mesOrcamento = estado.mes || mesDeHoje();
  // Os pedidos saem juntos (Promise.all) em vez de um esperar o outro.
  const [resumo, gastos, situacoes, recorrentes, categorias] = await Promise.all([
    api(`/resumo${filtroMes()}`),
    api(`/gastos${filtroMes()}`),
    api(`/orcamentos?mes=${mesOrcamento}`),
    api("/recorrentes"),
    api("/categorias"),
    carregarMeses(),
  ]);
  desenharNumeros(resumo, gastos);
  desenharBarras(resumo);
  desenharGastos(gastos);
  desenharOrcamentos(situacoes, mesOrcamento);
  desenharRecorrentes(recorrentes);
  $("#lista-categorias").replaceChildren(...categorias.map((c) => el("option", { value: c })));
  $("#exportar-xlsx").href = `/exportar?formato=xlsx${filtroMes().replace("?", "&")}`;
  $("#exportar-csv").href = `/exportar?formato=csv${filtroMes().replace("?", "&")}`;
}

function iniciar() {
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
  $("#botao-cancelar-importacao").addEventListener("click", esconderPrevia);
  recarregar().catch((erro) => mostrarMensagem(erro.message, true));
  api("/info")
    .then((info) => ($("#aviso-demo").hidden = !info.demo))
    .catch(() => {}); // sem o aviso, a página continua funcionando
}

iniciar();
