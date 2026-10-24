/*
 * ir.c — Geração de representação intermediária (IR) de três endereços.
 *
 * Recebe a árvore JÁ VALIDADA pela análise semântica (com no.tipo e
 * no.simbolo preenchidos) e produz uma lista de linhas de IR (ir_linhas).
 *
 * Conjunto de instruções:
 *
 *     x = y                      cópia (ASSIGN)
 *     x = y op z                 + - * / % < > <= >= == != and or
 *     x = not y                  NOT
 *     x = neg y                  NEG (menos unário)
 *     x = itof y                 conversão int -> float
 *     x = ctoi y                 conversão char -> int
 *     x = load v[i]              LOAD de elemento de vetor
 *     store v[i], y              STORE em elemento de vetor
 *     param y                    PARAM
 *     x = call f, n              CALL com resultado
 *     call f, n                  CALL sem resultado (void ou valor descartado)
 *     return / return y          RETURN
 *     print y / read x           saída e entrada
 *     goto L                     JUMP
 *     ifFalse x goto L           JUMP_IF_FALSE
 *     ifTrue x goto L            JUMP_IF_TRUE
 *     L:                         LABEL
 *     global x / global v[n]     declaração de variável global
 *
 * Decisões de implementação (não fixadas pela especificação — ver
 * minic-ir-test-cases/README.md):
 *   - Temporários (t1, t2, ...) e rótulos recomeçam em cada função.
 *   - Índices de vetor são em unidades de elemento: o endereço é i * 1.
 *   - && e || têm curto-circuito, como em C. Quando o operando da direita
 *     pode ser avaliado sempre sem efeito observável, a IR usa a operação
 *     direta (and/or); caso contrário, gera saltos reaproveitando um único
 *     temporário.
 *   - Argumentos são todos avaliados, da esquerda para a direita, antes
 *     dos "param": assim chamadas aninhadas não misturam seus parâmetros.
 *   - Variáveis com o mesmo nome em escopos diferentes recebem nomes
 *     distintos (x, x#2, ...), pois a IR não tem blocos.
 *   - Inicializadores de globais vão para a função especial "#init",
 *     executada antes de main.
 */
#include "util.h"
#include "semantic.h"
#include "ir.h"

#include <stdlib.h>
#include <string.h>

char **ir_linhas;
int n_ir_linhas;


/* ---------- Vetores de strings (saída, nomes usados) ---------- */

typedef struct { const char **itens; int n, cap; } VetorStr;

static void vs_push(VetorStr *v, const char *s)
{
    if (v->n == v->cap) {
        v->cap = v->cap ? v->cap * 2 : 8;
        v->itens = xrealloc(v->itens, (size_t)v->cap * sizeof *v->itens);
    }
    v->itens[v->n++] = s;
}

static int vs_contem(const VetorStr *v, const char *s)
{
    int i;
    for (i = 0; i < v->n; i++)
        if (strcmp(v->itens[i], s) == 0)
            return 1;
    return 0;
}

static char *juntar_virgula(const char **itens, int n)
{
    char *resultado = xstrndup("", 0);
    int i;
    for (i = 0; i < n; i++)
        resultado = fmt("%s%s%s", resultado, i == 0 ? "" : ", ", itens[i]);
    return resultado;
}


/* ---------- Pilha de laços (break/continue) ---------- */

typedef struct { const char *quebra, *continua; } RotuloLaco;
typedef struct { RotuloLaco *itens; int n, cap; } PilhaLacos;

static void lacos_empilhar(PilhaLacos *p, const char *quebra, const char *continua)
{
    if (p->n == p->cap) {
        p->cap = p->cap ? p->cap * 2 : 8;
        p->itens = xrealloc(p->itens, (size_t)p->cap * sizeof *p->itens);
    }
    p->itens[p->n].quebra = quebra;
    p->itens[p->n].continua = continua;
    p->n++;
}

static void lacos_desempilhar(PilhaLacos *p)
{
    p->n--;
}


/* ---------- Palavras reservadas e temporários ---------- */

static const char *RESERVADAS_IR[] = {
    "func", "endfunc", "global", "param", "call", "return", "print", "read",
    "goto", "ifFalse", "load", "store", "not", "neg", "itof", "ctoi",
    "and", "or", "true", "false",
};
#define N_RESERVADAS ((int)(sizeof(RESERVADAS_IR) / sizeof(RESERVADAS_IR[0])))

static int eh_palavra_reservada(const char *nome)
{
    int i;
    for (i = 0; i < N_RESERVADAS; i++)
        if (strcmp(nome, RESERVADAS_IR[i]) == 0)
            return 1;
    return 0;
}

/* "t" seguido de um ou mais dígitos e nada mais. */
static int eh_temporario(const char *nome)
{
    int i;
    if (nome[0] != 't' || nome[1] == '\0')
        return 0;
    for (i = 1; nome[i] != '\0'; i++)
        if (nome[i] < '0' || nome[i] > '9')
            return 0;
    return 1;
}


/* ---------- Estado do gerador ---------- */

static VetorStr linhas;
static VetorStr usados_global;
static VetorStr usados;
static PilhaLacos lacos;
static int n_temp;
static int n_construcao;
static Tipo tipo_retorno_atual;

static const char *ir_expr(No *no);  /* dispatcher: ir.c é mutuamente recursivo */
static void comando(No *no);         /* dispatcher: ir.c é mutuamente recursivo */


/* ---------- Utilidades de emissão ---------- */

static void emitir(const char *instrucao)
{
    vs_push(&linhas, fmt("  %s", instrucao));
}

static void emitir_rotulo(const char *rotulo)
{
    vs_push(&linhas, fmt("%s:", rotulo));
}

static char *novo_temp(void)
{
    n_temp++;
    return fmt("t%d", n_temp);
}

/* Rótulos de uma construção: L_base (1ª), L_base2, L_base3... */
static void novos_rotulos(int n, const char *const *bases, char **saida)
{
    int i;
    n_construcao++;
    for (i = 0; i < n; i++)
        saida[i] = n_construcao == 1
            ? fmt("L_%s", bases[i])
            : fmt("L_%s%d", bases[i], n_construcao);
}


/* ---------- Nomes de símbolos na IR ---------- */

/* Escolhe o nome do símbolo na IR, evitando colisões. */
static const char *nomear(Simbolo *simbolo, VetorStr *usados_destino)
{
    const char *base = simbolo->nome;
    const char *candidato = base;
    int k = 1;
    while (vs_contem(usados_destino, candidato) || eh_palavra_reservada(candidato)
           || eh_temporario(candidato)) {
        k++;
        candidato = fmt("%s#%d", base, k);
    }
    vs_push(usados_destino, candidato);
    simbolo->nome_ir = candidato;
    return candidato;
}

static const char *nome(Simbolo *simbolo)
{
    return simbolo->nome_ir;
}


/* ---------- Conversão e endereçamento ---------- */

/* Insere as conversões implícitas anotadas pela semântica. */
static const char *converter(const char *operando, Tipo de, Tipo para)
{
    char *t;

    if (tipo_igual(para, FLOAT) && tipo_igual(de, CHAR)) {
        operando = converter(operando, CHAR, INT);
        de = INT;
    }
    if (tipo_igual(para, FLOAT) && tipo_igual(de, INT)) {
        t = novo_temp();
        emitir(fmt("%s = itof %s", t, operando));
        return t;
    }
    if (tipo_igual(para, INT) && tipo_igual(de, CHAR)) {
        t = novo_temp();
        emitir(fmt("%s = ctoi %s", t, operando));
        return t;
    }
    return operando;
}

/* Calcula o deslocamento de um elemento: indice * escala (escala = 1). */
static const char *endereco(No *indice)
{
    const char *i = ir_expr(indice);
    char *t;
    i = converter(i, indice->tipo, INT);
    t = novo_temp();
    emitir(fmt("%s = %s * 1", t, i));
    return t;
}


/* ---------- Análise estática auxiliar (privada à geração de IR) ---------- */

static int zero_ou_desconhecido(Const c)
{
    return !c.ok || (c.inteiro ? c.i == 0 : c.r == 0.0);
}

/* A expressão pode ser avaliada mesmo quando o programa não a avaliaria?
 * (sem efeitos observáveis e sem possibilidade de erro em execução) */
static int avaliacao_segura(No *no)
{
    if (no->tipo_no == N_LITERAL || no->tipo_no == N_IDENTIFICADOR)
        return 1;
    if (no->tipo_no == N_UNARIA)
        return avaliacao_segura(no->operando);
    if (no->tipo_no == N_BINARIA) {
        if (strcmp(no->operador, "/") == 0 || strcmp(no->operador, "%") == 0) {
            if (zero_ou_desconhecido(valor_constante(no->direita)))
                return 0;
        }
        return avaliacao_segura(no->esquerda) && avaliacao_segura(no->direita);
    }
    return 0;   /* chamadas, acessos a vetor e atribuições */
}

/* Todo caminho pelo comando termina em return? (sem diagnósticos) */
static int sempre_retorna(No *no)
{
    int i;
    switch (no->tipo_no) {
    case N_RETURN:
        return 1;
    case N_BLOCO:
        for (i = 0; i < no->lista.n; i++)
            if (sempre_retorna(no->lista.itens[i]))
                return 1;
        return 0;
    case N_IF:
        return no->senao != NULL && sempre_retorna(no->entao) && sempre_retorna(no->senao);
    case N_WHILE:
    case N_FOR:
        return laco_infinito(no);
    default:
        return 0;
    }
}


/* ---------- Expressões: devolvem o operando (nome, temporário ou literal) ---------- */

static const char *ir_expr_literal(No *no)
{
    return no->lexema;
}

static const char *ir_expr_identificador(No *no)
{
    return nome(no->simbolo);
}

static const char *ir_expr_atribuicao(No *no)
{
    const char *valor, *desloc, *destino;

    if (no->alvo->tipo_no == N_IDENTIFICADOR) {
        valor = ir_expr(no->valor);
        valor = converter(valor, no->valor->tipo, no->alvo->tipo);
        destino = nome(no->alvo->simbolo);
        emitir(fmt("%s = %s", destino, valor));
        return destino;
    }

    /* Elemento de vetor: endereço, depois valor, depois store. */
    desloc = endereco(no->alvo->indice);
    valor = ir_expr(no->valor);
    valor = converter(valor, no->valor->tipo, no->alvo->tipo);
    emitir(fmt("store %s[%s], %s", nome(no->alvo->vetor->simbolo), desloc, valor));
    return valor;
}

static const char *ir_expr_unaria(No *no)
{
    const char *operando = ir_expr(no->operando);
    Tipo t_operando = no->operando->tipo;
    char *t;

    if (strcmp(no->operador, "!") == 0) {
        t = novo_temp();
        emitir(fmt("%s = not %s", t, operando));
        return t;
    }

    operando = converter(operando, t_operando, tipo_igual(t_operando, FLOAT) ? FLOAT : INT);
    t = novo_temp();
    emitir(fmt("%s = neg %s", t, operando));
    return t;
}

static const char *operador_ir(const char *op)
{
    if (strcmp(op, "&&") == 0) return "and";
    if (strcmp(op, "||") == 0) return "or";
    return op;
}

static const char *curto_circuito(No *no)
{
    char *rots[1];
    static const char *const bases[] = { "sc" };
    const char *esq, *dir_, *salto;
    char *t;

    novos_rotulos(1, bases, rots);
    esq = ir_expr(no->esquerda);
    t = novo_temp();
    emitir(fmt("%s = %s", t, esq));
    salto = strcmp(no->operador, "&&") == 0 ? "ifFalse" : "ifTrue";
    emitir(fmt("%s %s goto %s", salto, t, rots[0]));
    dir_ = ir_expr(no->direita);
    emitir(fmt("%s = %s", t, dir_));
    emitir_rotulo(rots[0]);
    return t;
}

static const char *ir_expr_binaria(No *no)
{
    const char *op = no->operador;
    const char *esq, *dir_;
    Tipo te, td, comum;
    char *t;
    int eh_aditiva_etc, forca_int;

    if ((strcmp(op, "&&") == 0 || strcmp(op, "||") == 0) && !avaliacao_segura(no->direita))
        return curto_circuito(no);

    esq = ir_expr(no->esquerda);
    dir_ = ir_expr(no->direita);
    te = no->esquerda->tipo;
    td = no->direita->tipo;

    eh_aditiva_etc = strcmp(op, "+") == 0 || strcmp(op, "-") == 0 || strcmp(op, "*") == 0
        || strcmp(op, "/") == 0 || strcmp(op, "%") == 0;
    if (eh_aditiva_etc || strcmp(op, "<") == 0 || strcmp(op, ">") == 0
        || strcmp(op, "<=") == 0 || strcmp(op, ">=") == 0
        || strcmp(op, "==") == 0 || strcmp(op, "!=") == 0) {
        forca_int = eh_aditiva_etc;
        if (tipo_igual(te, FLOAT) || tipo_igual(td, FLOAT))
            comum = FLOAT;
        else if (tipo_igual(te, INT) || tipo_igual(td, INT) || forca_int)
            comum = INT;
        else
            comum = te;
        esq = converter(esq, te, comum);
        dir_ = converter(dir_, td, comum);
    }

    t = novo_temp();
    emitir(fmt("%s = %s %s %s", t, esq, operador_ir(op), dir_));
    return t;
}

static const char *chamada(No *no, int descartar)
{
    Simbolo *simbolo = no->simbolo;
    int i, n = no->lista.n;
    const char **args = xmalloc((size_t)(n ? n : 1) * sizeof *args);
    char *t;

    for (i = 0; i < n; i++) {
        No *arg = no->lista.itens[i];
        const char *valor = ir_expr(arg);
        args[i] = converter(valor, arg->tipo, simbolo->parametros[i]);
    }
    for (i = 0; i < n; i++)
        emitir(fmt("param %s", args[i]));

    if (descartar || tipo_igual(simbolo->tipo, VOID)) {
        emitir(fmt("call %s, %d", no->funcao->nome, n));
        return NULL;
    }
    t = novo_temp();
    emitir(fmt("%s = call %s, %d", t, no->funcao->nome, n));
    return t;
}

static const char *ir_expr_indice(No *no)
{
    const char *desloc = endereco(no->indice);
    char *t = novo_temp();
    emitir(fmt("%s = load %s[%s]", t, nome(no->vetor->simbolo), desloc));
    return t;
}

static const char *ir_expr(No *no)
{
    switch (no->tipo_no) {
    case N_LITERAL:       return ir_expr_literal(no);
    case N_IDENTIFICADOR: return ir_expr_identificador(no);
    case N_ATRIBUICAO:    return ir_expr_atribuicao(no);
    case N_UNARIA:        return ir_expr_unaria(no);
    case N_BINARIA:       return ir_expr_binaria(no);
    case N_CHAMADA:       return chamada(no, 0);
    case N_INDICE:        return ir_expr_indice(no);
    default:              return "";
    }
}

/* Expressão usada como comando (init e passo do for; chamadas-comando). */
static void expr_comando(No *no)
{
    if (no->tipo_no == N_CHAMADA)
        chamada(no, 1);
    else
        ir_expr(no);
}


/* ---------- Comandos ---------- */

static void declaracao(No *no)
{
    const char *valor;
    if (no->simbolo->tipo.vetor)
        return;   /* vetores locais não geram instrução */
    if (no->inicializador != NULL) {
        valor = ir_expr(no->inicializador);
        valor = converter(valor, no->inicializador->tipo, no->simbolo->tipo);
        emitir(fmt("%s = %s", nome(no->simbolo), valor));
    }
}

static void cmd_declvar(No *no)
{
    nomear(no->simbolo, &usados);
    declaracao(no);
}

static void cmd_listadecl(No *no)
{
    int i;
    for (i = 0; i < no->lista.n; i++)
        cmd_declvar(no->lista.itens[i]);
}

static void cmd_bloco(No *no)
{
    int i;
    for (i = 0; i < no->lista.n; i++)
        comando(no->lista.itens[i]);
}

static void cmd_exprstmt(No *no)
{
    if (no->expressao == NULL)
        return;
    if (no->expressao->tipo_no == N_CHAMADA)
        chamada(no->expressao, 1);
    else
        ir_expr(no->expressao);
}

static void cmd_if(No *no)
{
    char *rots[2];
    static const char *const bases1[] = { "end_if" };
    static const char *const bases2[] = { "else", "end" };
    const char *cond;

    if (no->senao == NULL) {
        novos_rotulos(1, bases1, rots);
        cond = ir_expr(no->condicao);
        emitir(fmt("ifFalse %s goto %s", cond, rots[0]));
        comando(no->entao);
        emitir_rotulo(rots[0]);
    } else {
        novos_rotulos(2, bases2, rots);
        cond = ir_expr(no->condicao);
        emitir(fmt("ifFalse %s goto %s", cond, rots[0]));
        comando(no->entao);
        emitir(fmt("goto %s", rots[1]));
        emitir_rotulo(rots[0]);
        comando(no->senao);
        emitir_rotulo(rots[1]);
    }
}

static void cmd_while(No *no)
{
    char *rots[2];
    static const char *const bases[] = { "test", "end" };
    const char *cond;

    novos_rotulos(2, bases, rots);
    emitir_rotulo(rots[0]);
    cond = ir_expr(no->condicao);
    emitir(fmt("ifFalse %s goto %s", cond, rots[1]));
    lacos_empilhar(&lacos, rots[1], rots[0]);    /* continue volta ao teste */
    comando(no->corpo);
    lacos_desempilhar(&lacos);
    emitir(fmt("goto %s", rots[0]));
    emitir_rotulo(rots[1]);
}

/* A linha, após remover espaços à esquerda, é exatamente "goto <rotulo>"? */
static int eh_goto_para(const char *linha, const char *rotulo)
{
    const char *alvo;
    while (*linha == ' ')
        linha++;
    alvo = fmt("goto %s", rotulo);
    return strcmp(linha, alvo) == 0;
}

static void cmd_for(No *no)
{
    char *rots[3];
    static const char *const bases[] = { "test", "end", "step" };
    const char *cond;
    int inicio_corpo, i, usa_passo = 0;

    novos_rotulos(3, bases, rots);
    if (no->inicio != NULL)
        expr_comando(no->inicio);
    emitir_rotulo(rots[0]);
    if (no->condicao != NULL) {
        cond = ir_expr(no->condicao);
        emitir(fmt("ifFalse %s goto %s", cond, rots[1]));
    }

    lacos_empilhar(&lacos, rots[1], rots[2]);    /* continue vai para o passo */
    inicio_corpo = linhas.n;
    comando(no->corpo);
    lacos_desempilhar(&lacos);

    /* O rótulo do passo só é emitido se algum continue o usa. */
    for (i = inicio_corpo; i < linhas.n; i++)
        if (eh_goto_para(linhas.itens[i], rots[2])) { usa_passo = 1; break; }
    if (usa_passo)
        emitir_rotulo(rots[2]);
    if (no->passo != NULL)
        expr_comando(no->passo);
    emitir(fmt("goto %s", rots[0]));
    emitir_rotulo(rots[1]);
}

static void cmd_break(No *no)
{
    (void)no;
    emitir(fmt("goto %s", lacos.itens[lacos.n - 1].quebra));
}

static void cmd_continue(No *no)
{
    (void)no;
    emitir(fmt("goto %s", lacos.itens[lacos.n - 1].continua));
}

static void cmd_return(No *no)
{
    const char *valor;
    if (no->expressao == NULL) {
        emitir("return");
        return;
    }
    valor = ir_expr(no->expressao);
    valor = converter(valor, no->expressao->tipo, tipo_retorno_atual);
    emitir(fmt("return %s", valor));
}

static void cmd_print(No *no)
{
    emitir(fmt("print %s", ir_expr(no->argumento)));
}

static void cmd_read(No *no)
{
    No *alvo = no->alvo;
    const char *desloc, *t;

    if (alvo->tipo_no == N_IDENTIFICADOR) {
        emitir(fmt("read %s", nome(alvo->simbolo)));
    } else {
        desloc = endereco(alvo->indice);
        t = novo_temp();
        emitir(fmt("read %s", t));
        emitir(fmt("store %s[%s], %s", nome(alvo->vetor->simbolo), desloc, t));
    }
}

static void comando(No *no)
{
    switch (no->tipo_no) {
    case N_DECLVAR:   cmd_declvar(no);   break;
    case N_LISTADECL: cmd_listadecl(no); break;
    case N_BLOCO:     cmd_bloco(no);     break;
    case N_IF:        cmd_if(no);        break;
    case N_WHILE:     cmd_while(no);     break;
    case N_FOR:       cmd_for(no);       break;
    case N_BREAK:     cmd_break(no);     break;
    case N_CONTINUE:  cmd_continue(no);  break;
    case N_RETURN:    cmd_return(no);    break;
    case N_PRINT:     cmd_print(no);     break;
    case N_READ:      cmd_read(no);      break;
    case N_EXPRSTMT:  cmd_exprstmt(no);  break;
    default:          break;
    }
}


/* ---------- Programa e funções ---------- */

static void iniciar_funcao(void)
{
    int i;
    usados.n = 0;
    for (i = 0; i < usados_global.n; i++)
        vs_push(&usados, usados_global.itens[i]);
    n_temp = 0;
    n_construcao = 0;
    lacos.n = 0;
}

static void funcao(No *no)
{
    int i, n = no->lista.n;
    const char **params = xmalloc((size_t)(n ? n : 1) * sizeof *params);

    iniciar_funcao();
    tipo_retorno_atual = no->simbolo->tipo;

    for (i = 0; i < n; i++) {
        No *p = no->lista.itens[i];
        params[i] = nomear(p->simbolo, &usados);
    }

    if (n > 0)
        vs_push(&linhas, fmt("func %s(%s)", no->nome, juntar_virgula(params, n)));
    else
        vs_push(&linhas, fmt("func %s", no->nome));

    for (i = 0; i < no->corpo->lista.n; i++)
        comando(no->corpo->lista.itens[i]);

    /* Função void que pode chegar ao fim: return implícito. (Funções não
     * void sempre retornam: a semântica garante — SEM011.) */
    if (tipo_igual(no->simbolo->tipo, VOID) && !sempre_retorna(no->corpo))
        emitir("return");

    vs_push(&linhas, "endfunc");
}

static void gerar(No *programa)
{
    Lista globais, funcoes;
    int i, j, tem_inicializadas;

    memset(&globais, 0, sizeof globais);
    memset(&funcoes, 0, sizeof funcoes);

    for (i = 0; i < programa->lista.n; i++) {
        No *decl = programa->lista.itens[i];
        if (decl->tipo_no == N_FUNCAO) {
            lista_adicionar(&funcoes, decl);
        } else if (decl->tipo_no == N_LISTADECL) {
            for (j = 0; j < decl->lista.n; j++)
                lista_adicionar(&globais, decl->lista.itens[j]);
        } else {
            lista_adicionar(&globais, decl);
        }
    }

    /* Globais: declaração e, se houver, inicialização em "#init". */
    for (i = 0; i < globais.n; i++) {
        No *decl = globais.itens[i];
        const char *nome_g = nomear(decl->simbolo, &usados_global);
        if (decl->simbolo->tipo.vetor) {
            if (decl->simbolo->tamanho.ok && decl->simbolo->tamanho.inteiro)
                vs_push(&linhas, fmt("global %s[%lld]", nome_g, decl->simbolo->tamanho.i));
            else
                vs_push(&linhas, fmt("global %s[0]", nome_g));
        } else {
            vs_push(&linhas, fmt("global %s", nome_g));
        }
    }

    tem_inicializadas = 0;
    for (i = 0; i < globais.n; i++)
        if (((No *)globais.itens[i])->inicializador != NULL) { tem_inicializadas = 1; break; }

    if (tem_inicializadas) {
        iniciar_funcao();
        vs_push(&linhas, "func #init");
        for (i = 0; i < globais.n; i++) {
            No *decl = globais.itens[i];
            if (decl->inicializador != NULL)
                declaracao(decl);
        }
        emitir("return");
        vs_push(&linhas, "endfunc");
    }

    for (i = 0; i < funcoes.n; i++)
        funcao(funcoes.itens[i]);
}

void gerar_ir(No *programa)
{
    gerar(programa);
    ir_linhas = (char **)linhas.itens;
    n_ir_linhas = linhas.n;
}
