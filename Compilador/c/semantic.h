/*
 * semantic.h — Análise semântica (equivalente ao semantic.py).
 */
#ifndef SEMANTIC_H
#define SEMANTIC_H

#include "arvore.h"

typedef struct {
    const char *codigo;
    int linha, coluna;
    const char *mensagem;
} Diagnostico;

/* Diagnósticos encontrados, já em ordem de origem após a análise. */
extern Diagnostico *erros;
extern int n_erros;

/* Verifica nomes, escopos, tipos e regras contextuais da árvore. */
void analisar_semantica(No *programa);

/* "1 erro", "2 erros"... */
const char *plural(int n, const char *singular, const char *plural_);


/* Tabela de símbolos — exposta para que outras etapas (ex.: geração de IR)
 * leiam os símbolos anotados pela análise semântica em cada No. */

typedef enum { CAT_VARIAVEL, CAT_PARAMETRO, CAT_VETOR, CAT_FUNCAO } Categoria;

struct Simbolo {
    const char *nome;
    Categoria categoria;
    Tipo tipo;            /* para FUNÇÃO, é o tipo de retorno */
    int nivel;            /* nível léxico (0 = global) */
    int linha, coluna;
    Tipo *parametros;     /* tipos dos parâmetros (funções) */
    int n_parametros;
    Const tamanho;        /* tamanho constante do vetor, se conhecido */
    int inicializado;
    int usado;
    const char *nome_ir;  /* nome escolhido pela geração de IR; NULL até ser nomeado */
};

/* Construtores e utilidades de tipo, usados pela análise semântica e pela
 * geração de IR. */
Tipo tipo_de(Base base, int vetor);
int tipo_igual(Tipo a, Tipo b);

#define INT    tipo_de(B_INT, 0)
#define FLOAT  tipo_de(B_FLOAT, 0)
#define BOOL   tipo_de(B_BOOL, 0)
#define CHAR   tipo_de(B_CHAR, 0)
#define VOID   tipo_de(B_VOID, 0)
#define STRING tipo_de(B_STRING, 0)
/* Tipo "coringa" usado após um erro, para não gerar erros em cascata. */
#define ERRO   tipo_de(B_ERRO, 0)

/* Avalia expressões numéricas constantes; ok=0 se não for constante. */
Const valor_constante(No *no);

/* while(true) ou for(;;) sem break: o fim do laço é inalcançável. */
int laco_infinito(No *no);

#endif
