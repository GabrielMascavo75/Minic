
# Nós da Árvore Sintática do MINIC.

# Cada nó guarda:
#   - seus filhos (atributos específicos de cada classe);
#   - linha e coluna de origem, usadas nos diagnósticos;
#   - campos de anotação preenchidos pelo analisador semântico (tipo inferido e símbolo associado).

# O método __str__ de cada nó reproduz exatamente o formato textual que o
# parser imprimia antes, para que a saída do --ast não mude.

def _texto(no):
    # Converte um nó opcional em texto (None vira NULL).
    return "NULL" if no is None else str(no)


class No:
    def __init__(self, linha=0, coluna=0):
        self.linha = linha
        self.coluna = coluna
        # Fim (exclusivo) do trecho no fonte; preenchido para expressões.
        self.fim_linha = None
        self.fim_coluna = None
        # Anotações da análise semântica
        self.tipo = None      # tipo inferido (para expressões)
        self.simbolo = None   # símbolo da tabela (para Id, Chamada, decl.)


# Programa e declarações

class Programa(No):
    def __init__(self, declaracoes, **pos):
        super().__init__(**pos)
        self.declaracoes = declaracoes

    def __str__(self):
        return "Program(" + ", ".join(map(str, self.declaracoes)) + ")"


class Funcao(No):
    def __init__(self, tipo_retorno, nome, parametros, corpo, **pos):
        super().__init__(**pos)
        self.tipo_retorno = tipo_retorno
        self.nome = nome
        self.parametros = parametros
        self.corpo = corpo

    def __str__(self):
        params = ",".join(map(str, self.parametros))
        return f"Function({self.tipo_retorno} {self.nome}({params}) {self.corpo})"


class Parametro(No):
    def __init__(self, tipo_base, nome, eh_vetor=False, **pos):
        super().__init__(**pos)
        self.tipo_base = tipo_base
        self.nome = nome
        self.eh_vetor = eh_vetor

    def __str__(self):
        return f"{self.tipo_base} {self.nome}" + ("[]" if self.eh_vetor else "")


class DeclVar(No):
    def __init__(self, tipo_base, nome, tamanho=None, inicializador=None, **pos):
        super().__init__(**pos)
        self.tipo_base = tipo_base
        self.nome = nome
        self.tamanho = tamanho              # expressão ou None
        self.inicializador = inicializador  # expressão ou None

    def __str__(self):
        texto = f"{self.tipo_base} {self.nome}"
        if self.tamanho is not None:
            texto += f" size={self.tamanho}"
        if self.inicializador is not None:
            texto += f"={self.inicializador}"
        return f"VarDecl({texto})"


class ListaDecl(No):
    """Declaração com vários declaradores: int a, b = 2, c[3];"""

    def __init__(self, declaracoes, **pos):
        super().__init__(**pos)
        self.declaracoes = declaracoes

    def __str__(self):
        return ", ".join(map(str, self.declaracoes))


# Comandos

class Bloco(No):
    def __init__(self, comandos, **pos):
        super().__init__(**pos)
        self.comandos = comandos

    def __str__(self):
        return "Block(" + ", ".join(map(str, self.comandos)) + ")"


class If(No):
    def __init__(self, condicao, entao, senao=None, **pos):
        super().__init__(**pos)
        self.condicao = condicao
        self.entao = entao
        self.senao = senao

    def __str__(self):
        return f"If({self.condicao},{self.entao},{_texto(self.senao)})"


class While(No):
    def __init__(self, condicao, corpo, **pos):
        super().__init__(**pos)
        self.condicao = condicao
        self.corpo = corpo

    def __str__(self):
        return f"While({self.condicao},{self.corpo})"


class For(No):
    def __init__(self, inicio, condicao, passo, corpo, **pos):
        super().__init__(**pos)
        self.inicio = inicio
        self.condicao = condicao
        self.passo = passo
        self.corpo = corpo

    def __str__(self):
        return (f"For({_texto(self.inicio)},{_texto(self.condicao)},"
                f"{_texto(self.passo)},{self.corpo})")


class Return(No):
    def __init__(self, expressao=None, **pos):
        super().__init__(**pos)
        self.expressao = expressao

    def __str__(self):
        return f"Return({_texto(self.expressao)})"


class Break(No):
    def __str__(self):
        return "Break"


class Continue(No):
    def __str__(self):
        return "Continue"


class Print(No):
    def __init__(self, argumento, **pos):
        super().__init__(**pos)
        self.argumento = argumento

    def __str__(self):
        return f"Print({self.argumento})"


class Read(No):
    def __init__(self, alvo, **pos):
        super().__init__(**pos)
        self.alvo = alvo

    def __str__(self):
        return f"Read({self.alvo})"


class ExprStmt(No):
    def __init__(self, expressao=None, **pos):
        super().__init__(**pos)
        self.expressao = expressao   # None no comando vazio ";"

    def __str__(self):
        return f"ExprStmt({_texto(self.expressao)})"


# Expressões

class Atribuicao(No):
    def __init__(self, alvo, valor, **pos):
        super().__init__(**pos)
        self.alvo = alvo
        self.valor = valor

    def __str__(self):
        return f"Assign({self.alvo},{self.valor})"


class Binaria(No):
    def __init__(self, operador, esquerda, direita, **pos):
        super().__init__(**pos)
        self.operador = operador
        self.esquerda = esquerda
        self.direita = direita

    def __str__(self):
        return f"Binary({self.operador},{self.esquerda},{self.direita})"


class Unaria(No):
    def __init__(self, operador, operando, **pos):
        super().__init__(**pos)
        self.operador = operador
        self.operando = operando

    def __str__(self):
        return f"Unary({self.operador},{self.operando})"


class Chamada(No):
    def __init__(self, funcao, argumentos, **pos):
        super().__init__(**pos)
        self.funcao = funcao          # normalmente um Identificador
        self.argumentos = argumentos

    def __str__(self):
        if self.argumentos:
            return f"Call({self.funcao}," + ",".join(map(str, self.argumentos)) + ")"
        return f"Call({self.funcao})"


class Indice(No):
    def __init__(self, vetor, indice, **pos):
        super().__init__(**pos)
        self.vetor = vetor
        self.indice = indice

    def __str__(self):
        return f"Index({self.vetor},{self.indice})"


class Identificador(No):
    def __init__(self, nome, **pos):
        super().__init__(**pos)
        self.nome = nome

    def __str__(self):
        return f"Id({self.nome})"


class Literal(No):
    """tipo_literal: 'int', 'real', 'bool', 'char' ou 'string'."""

    def __init__(self, tipo_literal, lexema, valor=None, **pos):
        super().__init__(**pos)
        self.tipo_literal = tipo_literal
        self.lexema = lexema
        self.valor = valor   # atributo vindo do scanner (int, float, ...)

    def __str__(self):
        return f"Lit({self.tipo_literal},{self.lexema})"
