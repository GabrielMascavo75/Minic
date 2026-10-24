# MINIC em C

Conversão do pipeline Python enviado para C, mantendo a organização conceitual:

- `scanner.c/.h` — análise léxica;
- `arvore.c/.h` — AST;
- `parser.c/.h` — análise sintática e construção da AST;
- `semantic.c/.h` — análise semântica, tabela de símbolos, tipos e diagnósticos `SEMxxx`;
- `ir.c/.h` — geração de representação intermediária (IR) de três endereços;
- `util.c/.h` — utilidades gerais (alocação de memória e formatação);
- `minic.c` — driver do compilador;
- `Makefile` — compilação.

## Compilar

Linux/macOS/WSL com GCC:

```bash
make
```

Executável gerado:

```bash
./minic programa.c
./minic --ir programa.c
```

## Uso

```
minic [--ir] [-O0 | -O1] <arquivo.c>
```

- Sem `--ir`: executa léxico, sintático e semântico, e imprime o relatório da análise semântica.
- Com `--ir`: se o programa for aceito (zero erros semânticos), imprime a IR gerada (uma
  instrução por linha) em vez do relatório semântico. Se houver erros, o relatório de sempre é
  impresso normalmente — a IR nunca é gerada sobre um programa rejeitado.
- `-O0`/`-O1`: aceitos por compatibilidade com a interface do driver Python, mas o otimizador
  (etapa `-O1`) ainda não foi portado para C; a IR emitida é sempre a não otimizada.

O `minic` retorna:

- `0` — programa aceito;
- `2` — erro léxico;
- `3` — erro sintático;
- `4` — programa rejeitado pela análise semântica.

## Observação

A implementação foi feita a partir dos arquivos Python fornecidos. A etapa semântica preserva
os tipos, escopos, tabela de símbolos, conversões implícitas e os códigos `SEM001` a `SEM015`
usados pelo projeto. A geração de IR segue o conjunto de instruções de três endereços descrito
em `src/ir/ir.py` (conversão implícita, curto-circuito de `&&`/`||`, endereçamento de vetor,
etc.); a suíte independente `minic-ir-test-cases/` documenta que a IR esperada é uma referência
estrutural, não uma exigência de igualdade byte a byte.
