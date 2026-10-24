/*
 * util.c — Utilidades gerais (alocação de memória e formatação).
 */
#include "util.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>

void *xmalloc(size_t n)
{
    void *p = malloc(n ? n : 1);
    if (!p) {
        fputs("Erro: memória insuficiente.\n", stderr);
        exit(1);
    }
    return p;
}

void *xrealloc(void *p, size_t n)
{
    p = realloc(p, n ? n : 1);
    if (!p) {
        fputs("Erro: memória insuficiente.\n", stderr);
        exit(1);
    }
    return p;
}

char *xstrndup(const char *s, size_t n)
{
    char *r = xmalloc(n + 1);
    memcpy(r, s, n);
    r[n] = '\0';
    return r;
}

char *fmt(const char *formato, ...)
{
    va_list ap;
    int n;
    char *buf;

    va_start(ap, formato);
    n = vsnprintf(NULL, 0, formato, ap);
    va_end(ap);

    buf = xmalloc((size_t)n + 1);
    va_start(ap, formato);
    vsnprintf(buf, (size_t)n + 1, formato, ap);
    va_end(ap);
    return buf;
}
