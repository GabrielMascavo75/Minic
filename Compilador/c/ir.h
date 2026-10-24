/*
 * ir.h — Geração de representação intermediária (IR) de três endereços.
 */
#ifndef IR_H
#define IR_H

#include "arvore.h"

/* Gera a IR do programa (já validado pela análise semântica) e preenche
 * ir_linhas/n_ir_linhas. */
void gerar_ir(No *programa);

/* Linhas de texto da IR gerada, uma instrução/rótulo por linha. */
extern char **ir_linhas;
extern int n_ir_linhas;

#endif
