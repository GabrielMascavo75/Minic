# MINIC — compilador em Python

Compilador da linguagem educacional MINIC (ver `docs/especificacao-completa-minic.pdf`),
organizado conforme a seção 14 da especificação.

## Uso

```bash
python3 minic.py programa.c              # análise léxica, sintática e semântica
python3 minic.py --ir programa.c         # imprime a IR de três endereços (-O0)
python3 minic.py --ir -O1 programa.c     # IR otimizada
python3 src/ir/interpretador.py p.ir     # executa uma IR
```

Códigos de saída (seção 11.1): 0 sucesso, 1 uso inválido, 2 erro léxico,
3 erro sintático, 4 erro semântico.


## Estrutura

| Pasta | Conteúdo |
|---|---|
| `src/lexer/` | `scanner.py` — tokens com linha e coluna |
| `src/parser/` | `parser.py` — parser descendente recursivo |
| `src/ast/` | `arvore.py` — nós da árvore sintática |
| `src/semantic/` | `semantic.py` — escopos, tipos e diagnósticos SEMxxx |
| `src/ir/` | `ir.py` (gerador de IR) e `interpretador.py` (execução da IR) |
| `src/optimizer/` | `otimizador.py` — passagens do modo -O1 |

Requisitos: Python 3.8+; `gcc` apenas para o teste diferencial.
