/*
 * util.h — Utilidades gerais (alocação de memória e formatação).
 */
#ifndef UTIL_H
#define UTIL_H

#include <stddef.h>

void *xmalloc(size_t n);
void *xrealloc(void *p, size_t n);
char *xstrndup(const char *s, size_t n);
char *fmt(const char *formato, ...);

#endif
