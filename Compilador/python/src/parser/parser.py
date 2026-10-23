import json
import os
import sys
import subprocess

from arvore import (
    Programa, Funcao, Parametro, DeclVar, ListaDecl, Bloco, If, While, For,
    Return, Break, Continue, Print, Read, ExprStmt, Atribuicao, Binaria,
    Unaria, Chamada, Indice, Identificador, Literal,
)

DIRETORIO = os.path.dirname(os.path.abspath(__file__))


class ErroLexico(Exception):
    pass


class ErroSintatico(Exception):
    pass


# Obtenção de tokens a partir da saída do scanner para determinado código C.
def obter_tokens(nome_arquivo):
    # Caminho absoluto: funciona mesmo se o programa for chamado de outra pasta.
    resultado = subprocess.run(
        [sys.executable, os.path.join(DIRETORIO, "scanner.py"), nome_arquivo],
        capture_output=True,
        text=True
    )

    tokens = []
    for linha in resultado.stdout.splitlines():
        if not linha.strip():
            continue
        item = json.loads(linha)
        if "error" in item:
            raise ErroLexico(
                f"{item['error']} ('{item['lexeme']}') na linha "
                f"{item['line']}, coluna {item['column']}"
            )
        tokens.append(item)

    if not tokens or tokens[-1].get("token") != "EOF":
        raise ErroLexico("tokens inválidos retornados pelo scanner")

    return tokens


TIPOS = ("INT", "FLOAT", "BOOL", "CHAR", "VOID")


def pos(token):
    """Posição de origem de um token, no formato aceito pelos nós."""
    return {"linha": token["line"], "coluna": token["column"]}


class Parser:

    def __init__(self, tokens, estrito=True):
        self.tokens = tokens
        self.posicao = 0
        self.ultimo = None   # último token consumido (fim das expressões)
        # estrito=True: alvo de atribuição/read que não seja variável ou
        # elemento de vetor é erro SINTÁTICO (comportamento do parser.py).
        # estrito=False: a AST é construída e a análise semântica emite
        # o diagnóstico SEM013 (usado pelo minic.py).
        self.estrito = estrito

    # Utilidades de navegação

    def token_atual(self):
        if self.posicao < len(self.tokens):
            return self.tokens[self.posicao]
        return self.tokens[-1]

    def tipo_atual(self):
        return self.token_atual()["token"]

    def checar(self, *tipos):
        return self.tipo_atual() in tipos

    def avancar(self):
        token = self.token_atual()
        if self.posicao < len(self.tokens) - 1:
            self.posicao += 1
        self.ultimo = token
        return token

    def marcar(self, no, origem):
        """Define o trecho do fonte coberto por uma expressão.

        Início: posição de `origem` (um token ou outro nó).
        Fim (exclusivo): logo após o último token consumido.
        """
        if isinstance(origem, dict):
            no.linha, no.coluna = origem["line"], origem["column"]
        else:
            no.linha, no.coluna = origem.linha, origem.coluna
        no.fim_linha = self.ultimo["line"]
        no.fim_coluna = self.ultimo["column"] + len(self.ultimo["lexeme"])
        return no

    def consumir(self, tipo_esperado):
        if self.tipo_atual() != tipo_esperado:
            self.erro(f"esperado {tipo_esperado}")
        return self.avancar()

    def erro(self, mensagem):
        token = self.token_atual()
        raise ErroSintatico(
            f"{mensagem}, encontrado {token['token']} "
            f"('{token['lexeme']}') na linha {token['line']}, "
            f"coluna {token['column']}"
        )

    # Programa / Declarações globais

    def parse_programa(self):
        inicio = self.token_atual()
        declaracoes = []

        while not self.checar("EOF"):
            declaracoes.append(self.parse_declaracao_global())

        return Programa(declaracoes, **pos(inicio))

    def parse_declaracao_global(self):
        if self.checar(*TIPOS):
            tok_tipo = self.avancar()
            tok_nome = self.consumir("IDENT")

            if self.checar("LPAREN"):
                return self.parse_funcao(tok_tipo, tok_nome)

            return self.parse_var_decl_resto(tok_tipo, tok_nome)

        return self.parse_comando()

    def parse_funcao(self, tok_tipo, tok_nome):
        self.consumir("LPAREN")

        parametros = []
        if not self.checar("RPAREN"):
            parametros.append(self.parse_parametro())
            while self.checar("COMMA"):
                self.avancar()
                parametros.append(self.parse_parametro())

        self.consumir("RPAREN")

        # A gramática não admite protótipo: o corpo é obrigatório.
        corpo = self.parse_bloco()

        funcao = Funcao(tok_tipo["lexeme"], tok_nome["lexeme"], parametros,
                        corpo, **pos(tok_tipo))
        funcao.linha_nome = tok_nome["line"]
        funcao.coluna_nome = tok_nome["column"]
        return funcao

    def parse_parametro(self):
        if not self.checar(*TIPOS):
            self.erro("esperado tipo de parâmetro")

        tipo = self.avancar()["lexeme"]
        tok_nome = self.consumir("IDENT")

        # parametro ::= tipo identificador "[" "]"
        eh_vetor = False
        if self.checar("LBRACKET"):
            self.avancar()
            self.consumir("RBRACKET")
            eh_vetor = True

        return Parametro(tipo, tok_nome["lexeme"], eh_vetor, **pos(tok_nome))

    def parse_declarador(self, tipo, tok_nome):
        tamanho = None
        if self.checar("LBRACKET"):
            self.avancar()
            tamanho = self.parse_expressao()
            self.consumir("RBRACKET")

        inicializador = None
        if self.checar("ASSIGN"):
            self.avancar()
            inicializador = self.parse_expressao()

        return DeclVar(tipo, tok_nome["lexeme"], tamanho, inicializador,
                       **pos(tok_nome))

    def parse_var_decl_resto(self, tok_tipo, tok_nome):
        # declaracao_local ::= tipo declarador ("," declarador)* ";"
        tipo = tok_tipo["lexeme"]
        declaracoes = [self.parse_declarador(tipo, tok_nome)]

        while self.checar("COMMA"):
            self.avancar()
            proximo = self.consumir("IDENT")
            declaracoes.append(self.parse_declarador(tipo, proximo))

        self.consumir("SEMICOLON")

        if len(declaracoes) == 1:
            return declaracoes[0]
        return ListaDecl(declaracoes, **pos(tok_tipo))

    # Comandos

    def parse_bloco(self):
        tok = self.consumir("LBRACE")

        comandos = []
        while not self.checar("RBRACE"):
            if self.checar("EOF"):
                self.erro("esperado RBRACE")
            comandos.append(self.parse_comando())

        self.consumir("RBRACE")

        return Bloco(comandos, **pos(tok))

    def parse_comando(self):
        if self.checar(*TIPOS):
            tok_tipo = self.avancar()
            tok_nome = self.consumir("IDENT")
            return self.parse_var_decl_resto(tok_tipo, tok_nome)

        if self.checar("IF"):
            return self.parse_if()
        if self.checar("WHILE"):
            return self.parse_while()
        if self.checar("FOR"):
            return self.parse_for()
        if self.checar("RETURN"):
            return self.parse_return()
        if self.checar("BREAK"):
            tok = self.avancar()
            self.consumir("SEMICOLON")
            return Break(**pos(tok))
        if self.checar("CONTINUE"):
            tok = self.avancar()
            self.consumir("SEMICOLON")
            return Continue(**pos(tok))
        if self.checar("PRINT"):
            return self.parse_print()
        if self.checar("READ"):
            return self.parse_read()
        if self.checar("LBRACE"):
            return self.parse_bloco()

        return self.parse_expr_stmt()

    def parse_if(self):
        tok = self.consumir("IF")
        self.consumir("LPAREN")
        condicao = self.parse_expressao()
        self.consumir("RPAREN")

        entao = self.parse_comando()

        senao = None
        if self.checar("ELSE"):
            self.avancar()
            senao = self.parse_comando()

        return If(condicao, entao, senao, **pos(tok))

    def parse_while(self):
        tok = self.consumir("WHILE")
        self.consumir("LPAREN")
        condicao = self.parse_expressao()
        self.consumir("RPAREN")

        corpo = self.parse_comando()

        return While(condicao, corpo, **pos(tok))

    def parse_for(self):
        # comando_for ::= "for" "(" expr? ";" expr? ";" expr? ")" comando
        tok = self.consumir("FOR")
        self.consumir("LPAREN")

        inicio = None if self.checar("SEMICOLON") else self.parse_expressao()
        self.consumir("SEMICOLON")

        condicao = None if self.checar("SEMICOLON") else self.parse_expressao()
        self.consumir("SEMICOLON")

        passo = None if self.checar("RPAREN") else self.parse_expressao()
        self.consumir("RPAREN")

        corpo = self.parse_comando()

        return For(inicio, condicao, passo, corpo, **pos(tok))

    def parse_return(self):
        tok = self.consumir("RETURN")

        if self.checar("SEMICOLON"):
            self.avancar()
            return Return(None, **pos(tok))

        expressao = self.parse_expressao()
        self.consumir("SEMICOLON")

        return Return(expressao, **pos(tok))

    def parse_print(self):
        tok = self.consumir("PRINT")
        self.consumir("LPAREN")
        argumento = self.parse_expressao()
        self.consumir("RPAREN")
        self.consumir("SEMICOLON")
        return Print(argumento, **pos(tok))

    def parse_read(self):
        tok = self.consumir("READ")
        self.consumir("LPAREN")
        alvo = self.parse_expressao()
        if self.estrito and not isinstance(alvo, (Identificador, Indice)):
            self.erro("read exige uma variável ou posição de vetor")
        self.consumir("RPAREN")
        self.consumir("SEMICOLON")
        return Read(alvo, **pos(tok))

    def parse_expr_stmt(self):
        tok = self.token_atual()

        # comando_expressao ::= expressao? ";"
        if self.checar("SEMICOLON"):
            self.avancar()
            return ExprStmt(None, **pos(tok))

        expressao = self.parse_expressao()
        self.consumir("SEMICOLON")

        return ExprStmt(expressao, **pos(tok))

    # Expressões (precedência crescente)

    def parse_expressao(self):
        return self.parse_atribuicao()

    def parse_atribuicao(self):
        esquerda = self.parse_or()

        if self.checar("ASSIGN"):
            if self.estrito and not isinstance(esquerda, (Identificador, Indice)):
                self.erro("alvo de atribuição inválido")

            self.avancar()
            direita = self.parse_atribuicao()   # associativa à direita
            return self.marcar(Atribuicao(esquerda, direita), esquerda)

        return esquerda

    def _binaria(self, proximo, *operadores):
        """Laço genérico para operadores binários associativos à esquerda."""
        esquerda = proximo()
        while self.checar(*operadores):
            tok = self.avancar()
            direita = proximo()
            esquerda = self.marcar(
                Binaria(tok["lexeme"], esquerda, direita), esquerda)
        return esquerda

    def parse_or(self):
        return self._binaria(self.parse_and, "OR")

    def parse_and(self):
        return self._binaria(self.parse_igualdade, "AND")

    def parse_igualdade(self):
        return self._binaria(self.parse_relacional, "EQ", "NE")

    def parse_relacional(self):
        return self._binaria(self.parse_aditiva, "LT", "GT", "LE", "GE")

    def parse_aditiva(self):
        return self._binaria(self.parse_multiplicativa, "PLUS", "MINUS")

    def parse_multiplicativa(self):
        return self._binaria(self.parse_unaria, "STAR", "SLASH", "PERCENT")

    def parse_unaria(self):
        if self.checar("MINUS", "NOT"):
            tok = self.avancar()
            operando = self.parse_unaria()
            return self.marcar(Unaria(tok["lexeme"], operando), tok)
        return self.parse_pos_fixo()

    def parse_pos_fixo(self):
        expressao = self.parse_primario()

        while True:
            if self.checar("LPAREN"):
                tok = self.avancar()
                argumentos = []
                if not self.checar("RPAREN"):
                    argumentos.append(self.parse_expressao())
                    while self.checar("COMMA"):
                        self.avancar()
                        argumentos.append(self.parse_expressao())
                self.consumir("RPAREN")
                expressao = self.marcar(Chamada(expressao, argumentos),
                                        expressao)

            elif self.checar("LBRACKET"):
                self.avancar()
                indice = self.parse_expressao()
                self.consumir("RBRACKET")
                expressao = self.marcar(Indice(expressao, indice), expressao)

            else:
                break

        return expressao

    LITERAIS = {
        "INT_LIT": "int",
        "FLOAT_LIT": "real",
        "TRUE": "bool",
        "FALSE": "bool",
        "STRING_LIT": "string",
        "CHAR_LIT": "char",
    }

    def parse_primario(self):
        token = self.token_atual()
        tipo = token["token"]

        if tipo == "IDENT":
            self.avancar()
            return self.marcar(Identificador(token["lexeme"]), token)

        if tipo in self.LITERAIS:
            self.avancar()
            return self.marcar(Literal(self.LITERAIS[tipo], token["lexeme"],
                                       token.get("attribute")), token)

        if tipo == "LPAREN":
            self.avancar()
            expressao = self.parse_expressao()
            self.consumir("RPAREN")
            # O trecho passa a incluir os parênteses; assim o texto de
            # "(a + b) * c" é recortado corretamente do fonte.
            return self.marcar(expressao, token)

        self.erro("esperado identificador, literal ou '('")


def analisar_sintaxe(nome_arquivo, estrito=True):
    """Ponto de entrada usado pelas fases seguintes: devolve a AST (objetos)."""
    tokens = obter_tokens(nome_arquivo)
    return Parser(tokens, estrito).parse_programa()


MENSAGEM_REJEICAO = "NÃO HÁ AST: o parser deve rejeitar a entrada."


def main():
    if len(sys.argv) != 2:
        print("Uso: python parser.py <arquivo.c>", file=sys.stderr)
        return 2

    try:
        ast = analisar_sintaxe(sys.argv[1])
        print(ast)
        return 0

    except Exception:
        # Qualquer falha léxica ou sintática rejeita a entrada.
        print(MENSAGEM_REJEICAO)
        return 1


if __name__ == "__main__":
    sys.exit(main())
