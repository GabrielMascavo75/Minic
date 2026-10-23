
#Interpretador da IR de três endereços do MINIC.

# Executa uma IR em texto (o formato produzido por ir.py e usado nos
# gabaritos) e devolve as linhas impressas. Serve para validar a geração de
# IR e, na etapa de otimização, para comparar -O0 com -O1: as duas versões
# de um programa precisam produzir a mesma saída.

# Uso como programa:  python3 src/ir/interpretador.py arquivo.ir


import re
import sys

LIMITE_PASSOS = 2_000_000

ROTULO = re.compile(r"^([A-Za-z_][\w#]*):$")
NOME = r"[A-Za-z_#][\w#]*"

# Palavras de uma instrução: literais char/cadeia (que podem conter espaços),
# vírgulas e o restante separado por espaços.
_PALAVRA = re.compile(r"'(?:\\.|[^'\\])'|\"(?:\\.|[^\"\\])*\"|,|[^\s,]+")


def palavras(texto):
    return _PALAVRA.findall(texto)


class ErroExecucao(Exception):
    pass


class Vetor:
    """Vetor passado por referência; elementos não escritos valem 0."""

    def __init__(self):
        self.elementos = {}


# Leitura da IR

def carregar(texto):
    """Separa a IR em globais e funções: {nome: (params, instrucoes, rotulos)}."""
    globais = {}   # nome -> é vetor?
    funcoes = {}
    atual = None

    for bruta in texto.splitlines():
        linha = bruta.strip()
        if not linha:
            continue

        if linha.startswith("global "):
            declaracao = linha[len("global "):]
            globais[declaracao.split("[")[0].strip()] = "[" in declaracao
            continue

        m = re.fullmatch(r"func\s+(" + NOME + r")\s*(?:\((.*)\))?", linha)
        if m:
            params = [p.strip() for p in (m.group(2) or "").split(",") if p.strip()]
            atual = (params, [], {})
            funcoes[m.group(1)] = atual
            continue

        if linha == "endfunc":
            atual = None
            continue

        if atual is None:
            raise ErroExecucao(f"instrução fora de função: {linha}")

        m = ROTULO.match(linha)
        if m:
            atual[2][m.group(1)] = len(atual[1])
        else:
            atual[1].append(linha)

    return globais, funcoes


# Valores

def literal(texto):
    """Converte um literal da IR em valor Python, ou None se não for literal."""
    if re.fullmatch(r"-?\d+", texto):
        return int(texto)
    if re.fullmatch(r"-?\d+\.\d+", texto):
        return float(texto)
    if texto == "true":
        return True
    if texto == "false":
        return False
    if len(texto) >= 2 and texto[0] == texto[-1] and texto[0] in "'\"":
        corpo = texto[1:-1]
        corpo = (corpo.replace("\\n", "\n").replace("\\t", "\t")
                 .replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\"))
        return corpo   # char (1 caractere) ou cadeia
    return None


def int32(v):
    """int do MINIC: 32 bits em complemento de dois (decisão de implementação;
    a especificação não define o comportamento no overflow)."""
    if isinstance(v, bool) or not isinstance(v, int):
        return v
    return (v + 2**31) % 2**32 - 2**31


def numero(v):
    """char participa de aritmética pelo seu código."""
    if isinstance(v, str):
        return ord(v)
    return v


def divisao_c(a, b, resto):
    """Divisão e resto inteiros com truncamento em direção a zero (como C)."""
    if b == 0:
        raise ErroExecucao("divisão por zero")
    q = abs(a) // abs(b)
    if (a < 0) != (b < 0):
        q = -q
    return a - b * q if resto else q


def operar(op, a, b):
    if op == "and":
        return bool(a) and bool(b)
    if op == "or":
        return bool(a) or bool(b)
    if op in ("==", "!="):
        if isinstance(a, str) and isinstance(b, str):
            igual = a == b
        else:
            igual = numero(a) == numero(b)
        return igual if op == "==" else not igual

    a, b = numero(a), numero(b)
    if op == "+": return int32(a + b)
    if op == "-": return int32(a - b)
    if op == "*": return int32(a * b)
    if op == "/":
        if isinstance(a, float) or isinstance(b, float):
            if b == 0:
                raise ErroExecucao("divisão por zero")
            return a / b
        return int32(divisao_c(a, b, resto=False))
    if op == "%": return int32(divisao_c(a, b, resto=True))
    if op == "<": return a < b
    if op == ">": return a > b
    if op == "<=": return a <= b
    if op == ">=": return a >= b
    raise ErroExecucao(f"operador desconhecido: {op}")


def formatar(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return repr(v)
    return str(v)


# Execução

class Maquina:

    def __init__(self, texto, entrada=()):
        self.nomes_globais, self.funcoes = carregar(texto)
        self.globais = {}
        self.saida = []
        self.entrada = list(entrada)
        self.passos = 0

    def ler_var(self, quadro, nome):
        if nome in quadro:
            return quadro[nome]
        if nome in self.nomes_globais:
            return self.globais.setdefault(nome, 0)
        return quadro.setdefault(nome, 0)   # variável não inicializada

    def escrever_var(self, quadro, nome, valor):
        if nome not in quadro and nome in self.nomes_globais:
            self.globais[nome] = valor
        else:
            quadro[nome] = valor

    def vetor(self, quadro, nome):
        if nome in quadro and isinstance(quadro[nome], Vetor):
            return quadro[nome]
        if nome in self.nomes_globais:
            v = self.globais.get(nome)
            if not isinstance(v, Vetor):
                v = self.globais[nome] = Vetor()
            return v
        v = quadro[nome] = Vetor()   # vetores locais não são declarados na IR
        return v

    def valor(self, quadro, texto):
        v = literal(texto)
        if v is not None:
            return v
        return self.ler_var(quadro, texto)

    def executar(self):
        if "#init" in self.funcoes:
            self.chamar("#init", [])
        for entrada in ("main", "principal"):
            if entrada in self.funcoes:
                retorno = self.chamar(entrada, [])
                return self.saida, retorno
        raise ErroExecucao("nenhuma função main/principal")

    def chamar(self, nome, argumentos):
        if nome not in self.funcoes:
            raise ErroExecucao(f"função inexistente: {nome}")
        params, instrucoes, rotulos = self.funcoes[nome]
        quadro = dict(zip(params, argumentos))
        pendentes = []   # argumentos acumulados por "param"
        pc = 0

        while pc < len(instrucoes):
            self.passos += 1
            if self.passos > LIMITE_PASSOS:
                raise ErroExecucao("limite de passos excedido (laço infinito?)")

            ins = instrucoes[pc]
            pc += 1
            partes = palavras(ins)

            def salto(rotulo):
                if rotulo not in rotulos:
                    raise ErroExecucao(f"rótulo inexistente: {rotulo}")
                return rotulos[rotulo]

            if partes[0] == "goto":
                pc = salto(partes[1])
            elif partes[0] in ("ifFalse", "ifTrue") and partes[2] == "goto":
                cond = bool(self.valor(quadro, partes[1]))
                if cond == (partes[0] == "ifTrue"):
                    pc = salto(partes[3])
            elif partes[0] == "param":
                if len(partes) > 1:
                    arg = partes[1]
                    if literal(arg) is None and self.eh_vetor(quadro, arg):
                        pendentes.append(self.vetor(quadro, arg))
                    else:
                        pendentes.append(self.valor(quadro, arg))
            elif partes[0] == "call":
                self.fazer_chamada(partes[1], int(partes[3]), pendentes)
            elif partes[0] == "return":
                return self.valor(quadro, partes[1]) if len(partes) > 1 else None
            elif partes[0] == "print":
                arg = ins[len("print"):].strip()
                self.saida.append(formatar(self.valor(quadro, arg)))
            elif partes[0] == "read":
                destino = partes[1]
                if not self.entrada:
                    raise ErroExecucao("entrada esgotada")
                self.escrever_var(quadro, destino, literal(self.entrada.pop(0)))
            elif partes[0] == "store":
                m = re.fullmatch(r"store\s+(" + NOME + r")\[(.+)\]\s*,\s*(.+)", ins)
                v = self.vetor(quadro, m.group(1))
                v.elementos[numero(self.valor(quadro, m.group(2).strip()))] = \
                    self.valor(quadro, m.group(3).strip())
            elif len(partes) >= 3 and partes[1] == "=":
                self.atribuicao(quadro, ins, partes, pendentes)
            else:
                raise ErroExecucao(f"instrução desconhecida: {ins}")

        return None   # fim da função sem return

    def eh_vetor(self, quadro, nome):
        """Um "param nome" passa um vetor (por referência) ou um valor?"""
        if nome in quadro:
            return isinstance(quadro[nome], Vetor)
        if nome in self.nomes_globais:
            return self.nomes_globais[nome]
        # Nome nunca escrito nesta função: vetores locais não são declarados
        # na IR, enquanto escalares são sempre atribuídos antes do uso.
        return True

    def fazer_chamada(self, nome, n, pendentes):
        argumentos = pendentes[len(pendentes) - n:] if n else []
        del pendentes[len(pendentes) - n:]
        pendentes.clear()
        return self.chamar(nome, argumentos)

    def atribuicao(self, quadro, ins, partes, pendentes):
        destino = partes[0]
        resto = ins.split("=", 1)[1].strip()
        r = palavras(resto)

        if r[0] == "call":
            valor = self.fazer_chamada(r[1], int(r[3]), pendentes)
        elif r[0] == "load":
            m = re.fullmatch(r"load\s+(" + NOME + r")\[(.+)\]", resto)
            v = self.vetor(quadro, m.group(1))
            valor = v.elementos.get(numero(self.valor(quadro, m.group(2).strip())), 0)
        elif r[0] in ("not", "neg", "itof", "ctoi") and len(r) == 2:
            x = self.valor(quadro, r[1])
            valor = {"not": lambda: not x, "neg": lambda: int32(-numero(x)),
                     "itof": lambda: float(numero(x)),
                     "ctoi": lambda: numero(x)}[r[0]]()
        elif len(r) == 3:
            valor = operar(r[1], self.valor(quadro, r[0]), self.valor(quadro, r[2]))
        elif len(r) == 1 or literal(resto) is not None:
            valor = self.valor(quadro, resto)
        else:
            raise ErroExecucao(f"atribuição desconhecida: {ins}")

        self.escrever_var(quadro, destino, valor)


def executar(texto, entrada=()):
    """Executa a IR; devolve (linhas impressas, valor de retorno de main)."""
    return Maquina(texto, entrada).executar()


def executar_contando(texto, entrada=()):
    """Como executar(), mas devolve também quantas instruções foram executadas
    (medida do custo do programa, usada para avaliar as otimizações)."""
    maquina = Maquina(texto, entrada)
    saida, retorno = maquina.executar()
    return saida, retorno, maquina.passos


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python3 src/ir/interpretador.py <arquivo.ir>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], encoding="utf-8") as f:
        try:
            linhas, retorno = executar(f.read())
        except ErroExecucao as e:
            print(f"Erro de execução: {e}", file=sys.stderr)
            sys.exit(6)
    if linhas:
        print("\n".join(linhas))
    sys.exit(retorno if isinstance(retorno, int) and not isinstance(retorno, bool) else 0)
