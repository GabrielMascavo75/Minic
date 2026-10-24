/*
 * semantic.c — Análise semântica.
 *
 * Percorre a árvore produzida pelo parser, verificando nomes, escopos,
 * tipos e regras contextuais (seções 5, 6 e 7 da especificação). Os
 * diagnósticos seguem o catálogo SEMxxx do GABARITO.md.
 */
#include "util.h"
#include "scanner.h"
#include "semantic.h"

#include <stdlib.h>
#include <string.h>

/* ---------- Catálogo de códigos ---------- */
/* Definidos pelo gabarito: */
#define SEM001 "SEM001"  /* identificador não declarado */
#define SEM002 "SEM002"  /* declaração duplicada */
#define SEM003 "SEM003"  /* incompatibilidade de atribuição/conversão */
#define SEM004 "SEM004"  /* operando de tipo inválido para o operador */
#define SEM005 "SEM005"  /* condição não booleana */
#define SEM006 "SEM006"  /* índice (ou tamanho) de vetor inválido */
#define SEM007 "SEM007"  /* aridade incorreta */
#define SEM008 "SEM008"  /* tipo de argumento incompatível */
#define SEM009 "SEM009"  /* retorno incompatível */
#define SEM010 "SEM010"  /* break/continue fora de laço */
#define SEM011 "SEM011"  /* possível queda de função não void */
#define SEM012 "SEM012"  /* chamada void usada como valor */
#define SEM013 "SEM013"  /* destino não atribuível */
#define SEM014 "SEM014"  /* uso inválido de símbolo ou tipo */
#define SEM015 "SEM015"  /* divisão por zero constante */


/* Representação de tipos */

static const char *NOME_BASE[] = {
    "int", "float", "bool", "char", "void", "string", "erro"
};

Tipo tipo_de(Base base, int vetor)
{
    Tipo t;
    t.base = base;
    t.vetor = vetor;
    return t;
}

int tipo_igual(Tipo a, Tipo b)
{
    return a.base == b.base && a.vetor == b.vetor;
}

static const char *tipo_str(Tipo t)
{
    return fmt("%s%s", NOME_BASE[t.base], t.vetor ? "[]" : "");
}

/* Converte o lexema de um tipo ("int", "float", ...) em Base. */
static Base base_de(const char *nome)
{
    int i;
    for (i = 0; i <= B_STRING; i++)
        if (strcmp(nome, NOME_BASE[i]) == 0)
            return (Base)i;
    return B_ERRO;
}

static int eh_erro(Tipo t)
{
    return tipo_igual(t, ERRO);
}

static int eh_numerico(Tipo t)
{
    return !t.vetor && (t.base == B_INT || t.base == B_FLOAT || t.base == B_CHAR);
}

static int eh_inteiro(Tipo t)
{
    return !t.vetor && (t.base == B_INT || t.base == B_CHAR);
}

/* Conversões implícitas permitidas */
static int conversao_implicita(Base destino, Base origem)
{
    return (destino == B_FLOAT && origem == B_INT)
        || (destino == B_INT && origem == B_CHAR)
        || (destino == B_FLOAT && origem == B_CHAR);
}

static int compativel(Tipo destino, Tipo origem)
{
    if (eh_erro(destino) || eh_erro(origem))
        return 1;
    if (destino.vetor || origem.vetor)
        return tipo_igual(destino, origem);
    if (destino.base == origem.base)
        return destino.base != B_VOID && destino.base != B_STRING;
    return conversao_implicita(destino.base, origem.base);
}

const char *plural(int n, const char *singular, const char *plural_)
{
    return fmt("%d %s", n, n == 1 ? singular : plural_);
}


/* Tabela de símbolos */
/* Categoria e struct Simbolo estão declaradas em semantic.h, para que outras
 * etapas (ex.: geração de IR) possam ler os símbolos anotados na árvore. */

static Simbolo *novo_simbolo(const char *nome, Categoria categoria, Tipo tipo,
                             int nivel, int linha, int coluna)
{
    Simbolo *s = xmalloc(sizeof *s);
    memset(s, 0, sizeof *s);
    s->nome = nome;
    s->categoria = categoria;
    s->tipo = tipo;
    s->nivel = nivel;
    s->linha = linha;
    s->coluna = coluna;
    return s;
}

/* Pilha de escopos; cada escopo é uma lista de símbolos. */
typedef struct {
    Simbolo **itens;
    int n, cap;
} Escopo;

static Escopo *escopos;
static int n_escopos, cap_escopos;

static int nivel_atual(void)
{
    return n_escopos - 1;
}

static void abrir_escopo(void)
{
    if (n_escopos == cap_escopos) {
        cap_escopos = cap_escopos ? cap_escopos * 2 : 16;
        escopos = xrealloc(escopos, (size_t)cap_escopos * sizeof *escopos);
    }
    memset(&escopos[n_escopos], 0, sizeof escopos[n_escopos]);
    n_escopos++;
}

static void fechar_escopo(void)
{
    n_escopos--;
}

static void inserir(Simbolo *s)
{
    Escopo *e = &escopos[n_escopos - 1];
    if (e->n == e->cap) {
        e->cap = e->cap ? e->cap * 2 : 8;
        e->itens = xrealloc(e->itens, (size_t)e->cap * sizeof *e->itens);
    }
    e->itens[e->n++] = s;
}

static Simbolo *buscar_no_escopo(Escopo *e, const char *nome)
{
    int i;
    for (i = 0; i < e->n; i++)
        if (strcmp(e->itens[i]->nome, nome) == 0)
            return e->itens[i];
    return NULL;
}

static Simbolo *buscar_no_escopo_atual(const char *nome)
{
    return buscar_no_escopo(&escopos[n_escopos - 1], nome);
}

static Simbolo *buscar(const char *nome)
{
    /* Do escopo mais interno para o mais externo: sombreamento léxico. */
    int i;
    for (i = n_escopos - 1; i >= 0; i--) {
        Simbolo *s = buscar_no_escopo(&escopos[i], nome);
        if (s)
            return s;
    }
    return NULL;
}


/* Diagnósticos */


Diagnostico *erros;
int n_erros;
static int cap_erros;

static void erro_em(const char *codigo, int linha, int coluna, const char *mensagem)
{
    if (n_erros == cap_erros) {
        cap_erros = cap_erros ? cap_erros * 2 : 16;
        erros = xrealloc(erros, (size_t)cap_erros * sizeof *erros);
    }
    erros[n_erros].codigo = codigo;
    erros[n_erros].linha = linha;
    erros[n_erros].coluna = coluna;
    erros[n_erros].mensagem = mensagem;
    n_erros++;
}

static void erro(const char *codigo, No *no, const char *mensagem)
{
    erro_em(codigo, no->linha, no->coluna, mensagem);
}

/* "Em ordem de origem". Ordenação por inserção, que é estável: empates
 * mantêm a ordem em que os erros foram detectados. */
static void ordenar_erros(void)
{
    int i, j;
    for (i = 1; i < n_erros; i++) {
        Diagnostico atual = erros[i];
        for (j = i - 1; j >= 0; j--) {
            if (erros[j].linha < atual.linha
                || (erros[j].linha == atual.linha && erros[j].coluna <= atual.coluna))
                break;
            erros[j + 1] = erros[j];
        }
        erros[j + 1] = atual;
    }
}


/* Estado do analisador */

static Simbolo *funcao_atual;   /* função sendo analisada */
static int nivel_laco;          /* > 0 quando dentro de while/for */

/* Trecho do código-fonte que originou a expressão. */
static const char *texto(No *no)
{
    if (!no->tem_trecho)
        return "";
    return xstrndup(fonte + no->ini, no->fim - no->ini);
}

static Tipo expr(No *no, const char *contexto);
static void visitar(No *no);

/* Contextos de uso de um valor */
#define COMO_VALOR "como valor"


/* Funções auxiliares (análise estática) */

/* Avalia expressões numéricas constantes; ok=0 se não for constante. */
Const valor_constante(No *no)
{
    Const nada;
    memset(&nada, 0, sizeof nada);

    if (no->tipo_no == N_LITERAL
        && (strcmp(no->tipo_literal, "int") == 0 || strcmp(no->tipo_literal, "real") == 0))
        return no->valor_lit;

    if (no->tipo_no == N_UNARIA && strcmp(no->operador, "-") == 0) {
        Const v = valor_constante(no->operando);
        if (!v.ok)
            return nada;
        if (v.inteiro) v.i = -v.i;
        else v.r = -v.r;
        return v;
    }

    if (no->tipo_no == N_BINARIA
        && (strcmp(no->operador, "+") == 0 || strcmp(no->operador, "-") == 0
            || strcmp(no->operador, "*") == 0)) {
        Const e = valor_constante(no->esquerda);
        Const d = valor_constante(no->direita);
        Const r;
        char op = no->operador[0];
        if (!e.ok || !d.ok)
            return nada;
        memset(&r, 0, sizeof r);
        r.ok = 1;
        if (e.inteiro && d.inteiro) {
            r.inteiro = 1;
            r.i = op == '+' ? e.i + d.i : op == '-' ? e.i - d.i : e.i * d.i;
        } else {
            double x = e.inteiro ? (double)e.i : e.r;
            double y = d.inteiro ? (double)d.i : d.r;
            r.r = op == '+' ? x + y : op == '-' ? x - y : x * y;
        }
        return r;
    }
    return nada;
}

static int const_eh_zero(Const c)
{
    return c.ok && (c.inteiro ? c.i == 0 : c.r == 0.0);
}

/* Há um break que sai DESTE laço? (ignora laços aninhados) */
static int contem_break(No *no)
{
    int i;
    switch (no->tipo_no) {
    case N_BREAK:
        return 1;
    case N_BLOCO:
        for (i = 0; i < no->lista.n; i++)
            if (contem_break(no->lista.itens[i]))
                return 1;
        return 0;
    case N_IF:
        return contem_break(no->entao) || (no->senao && contem_break(no->senao));
    default:
        return 0;
    }
}

/* while(true) ou for(;;) sem break: o fim do laço é inalcançável. */
int laco_infinito(No *no)
{
    No *cond = no->condicao;
    int sempre = cond == NULL
        || (cond->tipo_no == N_LITERAL && strcmp(cond->tipo_literal, "bool") == 0
            && strcmp(cond->lexema, "true") == 0);
    return sempre && !contem_break(no->corpo);
}


/* Cobertura de retornos */

/* Marcador: "este comando não retorna", sem motivo específico. */
static const char CAI_MARCADOR[] = "";
#define CAI CAI_MARCADOR

/* NULL se todo caminho por `no` executa return; senão, o motivo
 * (ou CAI, quando não há um motivo mais específico). */
static const char *motivo_queda(No *no)
{
    int i;

    switch (no->tipo_no) {
    case N_RETURN:
        return NULL;

    case N_BLOCO: {
        const char **motivos;
        if (no->lista.n == 0)
            return CAI;
        motivos = xmalloc((size_t)no->lista.n * sizeof *motivos);
        for (i = 0; i < no->lista.n; i++)
            motivos[i] = motivo_queda(no->lista.itens[i]);
        for (i = 0; i < no->lista.n; i++)
            if (motivos[i] == NULL)
                return NULL;
        /* Explica pelo último comando que tem um motivo específico. */
        for (i = no->lista.n - 1; i >= 0; i--)
            if (motivos[i] != CAI)
                return motivos[i];
        return CAI;
    }

    case N_IF: {
        const char *cond = texto(no->condicao);
        const char *m_entao = motivo_queda(no->entao);
        const char *m_senao;
        if (m_entao == CAI)
            return fmt("o ramo em que “%s” é verdadeiro alcança o fim do corpo", cond);
        if (m_entao != NULL)
            return m_entao;
        if (no->senao == NULL)
            return fmt("o ramo em que “%s” é falso alcança o fim do corpo", cond);
        m_senao = motivo_queda(no->senao);
        if (m_senao == CAI)
            return fmt("o ramo em que “%s” é falso alcança o fim do corpo", cond);
        return m_senao;
    }

    case N_WHILE:
    case N_FOR:
        if (laco_infinito(no))
            return NULL;   /* só sai por return: não alcança o fim */
        return fmt("o laço %s pode terminar sem executar return "
                   "e alcançar o fim do corpo",
                   no->tipo_no == N_WHILE ? "while" : "for");

    default:
        return CAI;
    }
}


/* Declarações, nomes e escopos */

/* Insere no escopo atual, rejeitando duplicidade */
static int declarar(Simbolo *simbolo)
{
    Simbolo *anterior = buscar_no_escopo_atual(simbolo->nome);
    if (anterior) {
        const char *descricao = anterior->categoria == CAT_FUNCAO
            ? fmt("função de retorno %s", tipo_str(anterior->tipo))
            : fmt("tipo %s", tipo_str(anterior->tipo));
        erro_em(SEM002, simbolo->linha, simbolo->coluna,
                fmt("“%s” já declarado neste escopo; declaração anterior na "
                    "linha %d, coluna %d (%s).", simbolo->nome,
                    anterior->linha, anterior->coluna, descricao));
        return 0;
    }
    inserir(simbolo);
    return 1;
}

static void visitar_declvar(No *no)
{
    Tipo tipo;
    Const tamanho;
    Simbolo *simbolo;

    if (strcmp(no->tipo_base, "void") == 0) {
        erro(SEM014, no, fmt("Variável “%s” não pode ter tipo void.", no->nome));
        tipo = ERRO;
    } else {
        tipo = tipo_de(base_de(no->tipo_base), no->tamanho != NULL);
    }

    memset(&tamanho, 0, sizeof tamanho);
    if (no->tamanho) {
        Tipo t_tamanho = expr(no->tamanho, "como tamanho de vetor");
        if (!eh_erro(t_tamanho) && !eh_inteiro(t_tamanho))
            erro(SEM006, no->tamanho,
                 fmt("Tamanho do vetor “%s” deve ser int; recebeu %s "
                     "(expressão “%s”).", no->nome, tipo_str(t_tamanho),
                     texto(no->tamanho)));
        tamanho = valor_constante(no->tamanho);
        if (tamanho.ok && tamanho.inteiro && tamanho.i <= 0)
            erro(SEM006, no->tamanho,
                 fmt("Tamanho do vetor “%s” deve ser positivo; recebeu %lld.",
                     no->nome, tamanho.i));
    }

    /* O inicializador é analisado ANTES de inserir o nome:
     * em "int x = x;" o x da direita não é o que está sendo declarado. */
    if (no->inicializador) {
        Tipo t_init = expr(no->inicializador, "como inicializador");
        if (tipo.vetor)
            erro(SEM003, no->inicializador,
                 fmt("Vetor “%s” não pode receber inicializador.", no->nome));
        else if (!compativel(tipo, t_init))
            erro(SEM003, no->inicializador,
                 fmt("Não é possível atribuir %s a %s sem conversão permitida "
                     "(destino “%s”; expressão “%s”).", tipo_str(t_init),
                     tipo_str(tipo), no->nome, texto(no->inicializador)));
    }

    simbolo = novo_simbolo(no->nome, tipo.vetor ? CAT_VETOR : CAT_VARIAVEL,
                           tipo, nivel_atual(), no->linha, no->coluna);
    simbolo->tamanho = tamanho;
    simbolo->inicializado = no->inicializador != NULL;
    no->simbolo = simbolo;
    declarar(simbolo);
}

static void visitar_funcao(No *no)
{
    int i, n = no->lista.n;
    Tipo *tipos_params = xmalloc((size_t)(n ? n : 1) * sizeof *tipos_params);
    Simbolo *simbolo;

    for (i = 0; i < n; i++) {
        No *p = no->lista.itens[i];
        tipos_params[i] = tipo_de(base_de(p->tipo_base), p->eh_vetor);
    }

    /* O símbolo fica na posição do NOME;
     * o nó fica na posição do tipo de retorno. */
    simbolo = novo_simbolo(no->nome, CAT_FUNCAO,
                           tipo_de(base_de(no->tipo_base), 0), nivel_atual(),
                           no->linha_nome, no->coluna_nome);
    simbolo->parametros = tipos_params;
    simbolo->n_parametros = n;
    no->simbolo = simbolo;

    /* A função entra na tabela antes do corpo: permite recursão. */
    declarar(simbolo);

    funcao_atual = simbolo;
    abrir_escopo();

    for (i = 0; i < n; i++) {
        No *param = no->lista.itens[i];
        Tipo tipo = tipos_params[i];
        Simbolo *s;
        if (strcmp(param->tipo_base, "void") == 0) {
            erro(SEM014, param,
                 fmt("Parâmetro “%s” não pode ter tipo void.", param->nome));
            tipo = ERRO;
        }
        s = novo_simbolo(param->nome, CAT_PARAMETRO, tipo, nivel_atual(),
                         param->linha, param->coluna);
        s->inicializado = 1;
        param->simbolo = s;
        declarar(s);
    }

    /* Parâmetros e corpo compartilham o mesmo escopo (como em C):
     * "int f(int a) { int a; }" é declaração duplicada. */
    for (i = 0; i < no->corpo->lista.n; i++)
        visitar(no->corpo->lista.itens[i]);

    if (!tipo_igual(simbolo->tipo, VOID)) {
        const char *motivo = motivo_queda(no->corpo);
        if (motivo != NULL) {
            if (motivo == CAI)
                motivo = "o fim do corpo é alcançado sem executar return";
            erro(SEM011, no,
                 fmt("A função “%s” pode terminar sem retornar %s; %s.",
                     no->nome, tipo_str(simbolo->tipo), motivo));
        }
    }

    fechar_escopo();
    funcao_atual = NULL;
}

static void visitar_programa(No *no)
{
    Simbolo *main_;
    int i;

    for (i = 0; i < no->lista.n; i++) {
        No *decl = no->lista.itens[i];
        if (decl->tipo_no == N_FUNCAO || decl->tipo_no == N_DECLVAR
            || decl->tipo_no == N_LISTADECL)
            visitar(decl);
        else
            erro(SEM014, decl, "Comando fora de função.");
    }

    /* A ausência de main não é erro (a suíte usa "principal"), mas,
     * se main existir, sua assinatura é verificada. */
    main_ = buscar("main");
    if (main_ && main_->categoria == CAT_FUNCAO) {
        if (!tipo_igual(main_->tipo, INT))
            erro_em(SEM014, main_->linha, main_->coluna,
                    "A função “main” deve retornar int.");
        if (main_->n_parametros > 0)
            erro_em(SEM014, main_->linha, main_->coluna,
                    "A função “main” não deve ter parâmetros.");
    }
}


/* Comandos e regras contextuais */

static void condicao(No *e, const char *comando)
{
    Tipo tipo = expr(e, "como condição");
    if (!eh_erro(tipo) && !tipo_igual(tipo, BOOL))
        erro(SEM005, e, fmt("Condição de %s deve ter tipo bool; recebeu %s "
                            "(expressão “%s”).", comando, tipo_str(tipo), texto(e)));
}

static void visitar_return(No *no)
{
    Tipo esperado = funcao_atual->tipo;
    const char *nome = funcao_atual->nome;
    Tipo tipo;

    if (no->expressao == NULL) {
        if (!tipo_igual(esperado, VOID))
            erro(SEM009, no, fmt("Retorno sem valor na função “%s”, que deve "
                                 "retornar %s.", nome, tipo_str(esperado)));
        return;
    }

    if (tipo_igual(esperado, VOID)) {
        expr(no->expressao, NULL);
        erro(SEM009, no->expressao,
             fmt("A função “%s” é void e não pode retornar valor "
                 "(expressão “%s”).", nome, texto(no->expressao)));
        return;
    }

    tipo = expr(no->expressao, "como valor de retorno");
    if (!compativel(esperado, tipo))
        erro(SEM009, no->expressao,
             fmt("Retorno %s incompatível com o tipo %s da função “%s”; "
                 "conversão implícita de %s para %s não permitida.",
                 tipo_str(tipo), tipo_str(esperado), nome,
                 tipo_str(tipo), tipo_str(esperado)));
}

static Tipo destino(No *alvo, const char *operacao);

static void visitar(No *no)
{
    int i;
    Tipo tipo;

    switch (no->tipo_no) {
    case N_PROGRAMA:
        visitar_programa(no);
        break;

    case N_FUNCAO:
        visitar_funcao(no);
        break;

    case N_DECLVAR:
        visitar_declvar(no);
        break;

    case N_LISTADECL:
        for (i = 0; i < no->lista.n; i++)
            visitar(no->lista.itens[i]);
        break;

    case N_BLOCO:
        /* Todo bloco interno cria um escopo próprio (sombreamento). */
        abrir_escopo();
        for (i = 0; i < no->lista.n; i++)
            visitar(no->lista.itens[i]);
        fechar_escopo();
        break;

    case N_IF:
        condicao(no->condicao, "if");
        visitar(no->entao);
        if (no->senao)
            visitar(no->senao);
        break;

    case N_WHILE:
        condicao(no->condicao, "while");
        nivel_laco++;
        visitar(no->corpo);
        nivel_laco--;
        break;

    case N_FOR:
        if (no->inicio)
            expr(no->inicio, NULL);
        if (no->condicao)
            condicao(no->condicao, "for");
        if (no->passo)
            expr(no->passo, NULL);
        nivel_laco++;
        visitar(no->corpo);
        nivel_laco--;
        break;

    case N_BREAK:
        if (nivel_laco == 0)
            erro(SEM010, no, "Comando “break” fora de laço.");
        break;

    case N_CONTINUE:
        if (nivel_laco == 0)
            erro(SEM010, no, "Comando “continue” fora de laço.");
        break;

    case N_RETURN:
        visitar_return(no);
        break;

    case N_PRINT:
        if (no->argumento->tipo_no == N_LITERAL
            && strcmp(no->argumento->tipo_literal, "string") == 0) {
            no->argumento->tipo = STRING;   /* cadeia só é aceita aqui */
            break;
        }
        tipo = expr(no->argumento, "como argumento de print");
        if (!eh_erro(tipo) && tipo.vetor)
            erro(SEM014, no->argumento,
                 fmt("print não aceita um vetor inteiro (expressão “%s”).",
                     texto(no->argumento)));
        break;

    case N_READ:
        destino(no->alvo, "leitura");
        break;

    case N_EXPRSTMT:
        /* NULL: chamada void permitida, o valor é descartado. */
        if (no->expressao)
            expr(no->expressao, NULL);
        break;

    default:
        break;
    }
}


/* Expressões e tipos */

static Tipo expr_literal(No *no)
{
    if (strcmp(no->tipo_literal, "string") == 0) {
        size_t len = strlen(no->lexema);
        const char *interno = xstrndup(no->lexema + 1, len >= 2 ? len - 2 : 0);
        erro(SEM014, no, fmt("Cadeia “%s” só é permitida como argumento de print.",
                             interno));
        return ERRO;
    }
    if (strcmp(no->tipo_literal, "int") == 0)  return INT;
    if (strcmp(no->tipo_literal, "real") == 0) return FLOAT;
    if (strcmp(no->tipo_literal, "bool") == 0) return BOOL;
    return CHAR;
}

static Tipo expr_identificador(No *no)
{
    Simbolo *simbolo = buscar(no->nome);
    if (!simbolo) {
        erro(SEM001, no, fmt("Identificador “%s” não declarado neste escopo.",
                             no->nome));
        return ERRO;
    }

    no->simbolo = simbolo;
    if (simbolo->categoria == CAT_FUNCAO) {
        erro(SEM014, no, fmt("“%s” é uma função e não pode ser usada sem chamada.",
                             no->nome));
        return ERRO;
    }

    simbolo->usado = 1;
    return simbolo->tipo;
}

/* Valida o lado esquerdo de atribuição ou o alvo de read. */
static Tipo destino(No *alvo, const char *operacao)
{
    const char *prefixo = fmt("Destino de %s não é atribuível", operacao);
    const char *descricao;

    if (alvo->tipo_no == N_IDENTIFICADOR) {
        Simbolo *simbolo = buscar(alvo->nome);
        if (!simbolo) {
            erro(SEM001, alvo, fmt("Identificador “%s” não declarado neste escopo.",
                                   alvo->nome));
            return ERRO;
        }
        alvo->simbolo = simbolo;
        if (simbolo->categoria == CAT_FUNCAO) {
            erro(SEM013, alvo, fmt("%s; “%s” designa uma função, não uma variável "
                                   "ou elemento de vetor.", prefixo, alvo->nome));
            return ERRO;
        }
        if (simbolo->tipo.vetor) {
            erro(SEM013, alvo, fmt("%s; “%s” designa um vetor inteiro, não uma "
                                   "variável ou elemento de vetor.",
                                   prefixo, alvo->nome));
            return ERRO;
        }
        simbolo->inicializado = 1;
        alvo->tipo = simbolo->tipo;
        return simbolo->tipo;
    }

    if (alvo->tipo_no == N_INDICE)
        return expr(alvo, COMO_VALOR);

    /* Qualquer outra expressão: analisa (para achar erros internos) e
     * rejeita como destino. */
    expr(alvo, NULL);
    if (alvo->tipo_no == N_LITERAL) {
        const char *t = alvo->tipo_literal;
        descricao = strcmp(t, "int") == 0 ? "o literal inteiro"
                  : strcmp(t, "real") == 0 ? "o literal real"
                  : strcmp(t, "bool") == 0 ? "o literal booleano"
                  : strcmp(t, "char") == 0 ? "o literal caractere"
                  : "a cadeia";
    } else if (alvo->tipo_no == N_CHAMADA) {
        descricao = "a chamada";
    } else {
        descricao = "a expressão";
    }
    erro(SEM013, alvo, fmt("%s; %s “%s” não designa uma variável ou elemento "
                           "de vetor.", prefixo, descricao, texto(alvo)));
    return ERRO;
}

static Tipo expr_atribuicao(No *no)
{
    Tipo t_valor = expr(no->valor, "como expressão de atribuição");
    Tipo t_alvo = destino(no->alvo, "atribuição");

    if (eh_erro(t_alvo) || eh_erro(t_valor))
        return ERRO;
    if (!compativel(t_alvo, t_valor)) {
        erro(SEM003, no->valor,
             fmt("Não é possível atribuir %s a %s sem conversão permitida "
                 "(destino “%s”; expressão “%s”).", tipo_str(t_valor),
                 tipo_str(t_alvo), texto(no->alvo), texto(no->valor)));
        return ERRO;
    }
    return t_alvo;
}

static Tipo expr_unaria(No *no)
{
    Tipo tipo = expr(no->operando, "como operando");
    if (eh_erro(tipo))
        return ERRO;

    if (strcmp(no->operador, "!") == 0) {
        if (!tipo_igual(tipo, BOOL)) {
            erro(SEM004, no, fmt("Operador “!” exige operando bool; recebeu %s "
                                 "(expressão “%s”).", tipo_str(tipo), texto(no)));
            return ERRO;
        }
        return BOOL;
    }

    /* "-" unário */
    if (!eh_numerico(tipo)) {
        erro(SEM004, no, fmt("Operador “-” exige operando numérico; recebeu %s "
                             "(expressão “%s”).", tipo_str(tipo), texto(no)));
        return ERRO;
    }
    return tipo_igual(tipo, FLOAT) ? FLOAT : INT;
}

static void checar_divisor(No *no)
{
    if (const_eh_zero(valor_constante(no->direita)))
        erro(SEM015, no->direita,
             fmt("Divisão por zero constante (expressão “%s”).", texto(no)));
}

static Tipo rejeitar_binaria(No *no, const char *exigencia, Tipo te, Tipo td)
{
    erro(SEM004, no, fmt("Operador “%s” %s; recebeu %s e %s (expressão “%s”).",
                         no->operador, exigencia, tipo_str(te), tipo_str(td),
                         texto(no)));
    return ERRO;
}

static Tipo expr_binaria(No *no)
{
    const char *op = no->operador;
    Tipo te = expr(no->esquerda, "como operando");
    Tipo td = expr(no->direita, "como operando");

    if (eh_erro(te) || eh_erro(td))
        return ERRO;

    if (strcmp(op, "&&") == 0 || strcmp(op, "||") == 0) {
        if (!tipo_igual(te, BOOL) || !tipo_igual(td, BOOL))
            return rejeitar_binaria(no, "exige operandos bool", te, td);
        return BOOL;
    }

    if (strcmp(op, "==") == 0 || strcmp(op, "!=") == 0) {
        if (eh_numerico(te) && eh_numerico(td))
            return BOOL;
        if (tipo_igual(te, td) && !te.vetor)
            return BOOL;
        return rejeitar_binaria(no, "exige operandos de tipos comparáveis", te, td);
    }

    if (strcmp(op, "<") == 0 || strcmp(op, ">") == 0
        || strcmp(op, "<=") == 0 || strcmp(op, ">=") == 0) {
        if (!(eh_numerico(te) && eh_numerico(td)))
            return rejeitar_binaria(no, "exige operandos numéricos", te, td);
        return BOOL;
    }

    if (strcmp(op, "%") == 0) {
        if (!(eh_inteiro(te) && eh_inteiro(td)))
            return rejeitar_binaria(no, "exige operandos inteiros", te, td);
        checar_divisor(no);
        return INT;
    }

    /* + - * / */
    if (!(eh_numerico(te) && eh_numerico(td)))
        return rejeitar_binaria(no, "exige operandos numéricos", te, td);
    if (strcmp(op, "/") == 0)
        checar_divisor(no);
    return (tipo_igual(te, FLOAT) || tipo_igual(td, FLOAT)) ? FLOAT : INT;
}

static Tipo *analisar_argumentos(No *no)
{
    int i, n = no->lista.n;
    Tipo *tipos = xmalloc((size_t)(n ? n : 1) * sizeof *tipos);
    for (i = 0; i < n; i++)
        tipos[i] = expr(no->lista.itens[i], "como argumento");
    return tipos;
}

static Tipo expr_chamada(No *no)
{
    const char *nome;
    Simbolo *simbolo;
    Tipo *tipos_args;
    int i, n_args = no->lista.n;

    if (no->funcao->tipo_no != N_IDENTIFICADOR) {
        erro(SEM014, no, fmt("Apenas funções nomeadas podem ser chamadas "
                             "(expressão “%s”).", texto(no)));
        analisar_argumentos(no);
        return ERRO;
    }

    nome = no->funcao->nome;
    simbolo = buscar(nome);
    if (!simbolo) {
        erro(SEM001, no->funcao, fmt("Identificador “%s” não declarado neste "
                                     "escopo.", nome));
        analisar_argumentos(no);
        return ERRO;
    }
    if (simbolo->categoria != CAT_FUNCAO) {
        erro(SEM014, no->funcao, fmt("“%s” não é uma função e não pode ser "
                                     "chamado.", nome));
        analisar_argumentos(no);
        return ERRO;
    }

    no->funcao->simbolo = simbolo;
    no->simbolo = simbolo;
    simbolo->usado = 1;

    tipos_args = analisar_argumentos(no);

    if (n_args != simbolo->n_parametros) {
        erro(SEM007, no, fmt("“%s” espera %s, mas recebeu %d.", nome,
                             plural(simbolo->n_parametros, "argumento", "argumentos"),
                             n_args));
    } else {
        for (i = 0; i < n_args; i++) {
            if (!compativel(simbolo->parametros[i], tipos_args[i]))
                erro(SEM008, no->lista.itens[i],
                     fmt("Argumento %d de “%s”: esperado %s, recebido %s "
                         "(expressão “%s”).", i + 1, nome,
                         tipo_str(simbolo->parametros[i]), tipo_str(tipos_args[i]),
                         texto(no->lista.itens[i])));
        }
    }
    return simbolo->tipo;
}

static Tipo expr_indice(No *no)
{
    Tipo t_vetor = expr(no->vetor, "como operando");
    Tipo t_indice = expr(no->indice, "como índice");
    const char *nome_vetor = texto(no->vetor);
    Simbolo *simbolo;
    Const indice;

    if (!eh_erro(t_indice) && !eh_inteiro(t_indice))
        erro(SEM006, no->indice,
             fmt("Índice do vetor “%s” deve ser int; recebeu %s (expressão “%s”).",
                 nome_vetor, tipo_str(t_indice), texto(no->indice)));

    if (eh_erro(t_vetor))
        return ERRO;
    if (!t_vetor.vetor) {
        erro(SEM014, no->vetor, fmt("“%s” não é um vetor e não pode ser indexado "
                                    "(tipo %s).", nome_vetor, tipo_str(t_vetor)));
        return ERRO;
    }

    /* Limites: verificáveis em compilação quando índice e tamanho são
     * constantes inteiras. */
    simbolo = no->vetor->tipo_no == N_IDENTIFICADOR ? no->vetor->simbolo : NULL;
    indice = valor_constante(no->indice);
    if (simbolo && simbolo->tamanho.ok && simbolo->tamanho.inteiro
        && indice.ok && indice.inteiro
        && !(indice.i >= 0 && indice.i < simbolo->tamanho.i))
        erro(SEM006, no->indice,
             fmt("Índice %lld fora dos limites do vetor “%s” (tamanho %lld).",
                 indice.i, nome_vetor, simbolo->tamanho.i));

    return tipo_de(t_vetor.base, 0);
}

/* Analisa uma expressão, anota no->tipo e devolve o tipo.
 * `contexto` descreve onde o valor é usado (para o SEM012);
 * NULL significa posição de comando: void é permitido. */
static Tipo expr(No *no, const char *contexto)
{
    Tipo tipo;

    switch (no->tipo_no) {
    case N_LITERAL:       tipo = expr_literal(no);       break;
    case N_IDENTIFICADOR: tipo = expr_identificador(no); break;
    case N_ATRIBUICAO:    tipo = expr_atribuicao(no);    break;
    case N_UNARIA:        tipo = expr_unaria(no);        break;
    case N_BINARIA:       tipo = expr_binaria(no);       break;
    case N_CHAMADA:       tipo = expr_chamada(no);       break;
    case N_INDICE:        tipo = expr_indice(no);        break;
    default:              tipo = ERRO;                   break;
    }

    if (tipo_igual(tipo, VOID) && contexto != NULL) {
        const char *nome = (no->tipo_no == N_CHAMADA
                            && no->funcao->tipo_no == N_IDENTIFICADOR)
            ? no->funcao->nome : texto(no);
        erro(SEM012, no, fmt("Função “%s” não produz valor (retorno void) e não "
                             "pode ser usada %s.", nome, contexto));
        tipo = ERRO;
    }

    no->tipo = tipo;
    return tipo;
}

void analisar_semantica(No *programa)
{
    n_escopos = 0;
    abrir_escopo();   /* escopo global */
    funcao_atual = NULL;
    nivel_laco = 0;
    visitar(programa);
    ordenar_erros();
}
