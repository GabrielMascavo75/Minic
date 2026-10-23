
# Otimizador da IR de três endereços do MINIC (modo -O1).

# Trabalha sobre a forma estruturada da IR (uma Instrucao por linha, como
# quádruplas), dividida em blocos básicos:

#   Locais (dentro de cada bloco básico)
#     - dobra de constantes            t1 = 2 + 3        ->  t1 = 5
#     - identidades algébricas         t1 = x + 0        ->  t1 = x
#     - propagação de constantes       a = 5; t = a * 4  ->  t = 5 * 4
#     - propagação de cópias           b = a; print b    ->  print a
#     - subexpressões comuns           t3 = a * b        ->  t3 = t1

#   Globais (entre blocos, sobre o grafo de fluxo)
#     - propagação global de constantes   (análise para a frente)
#     - variáveis vivas + código morto    (análise para trás)
#     - dobra de desvios                  ifFalse true goto L   ->  (some)
#     - remoção de código inalcançável    blocos sem caminho desde a entrada
#     - limpeza de saltos                 goto para a linha seguinte, saltos
#                                         encadeados e rótulos sem uso
#     - coalescência de cópias            t3 = i + 1; i = t3  ->  i = i + 1

#   Laços
#     - dominadores, arestas de retorno e laços naturais
#     - movimentação de código invariante para o pré-cabeçalho

# As passagens se repetem até a IR parar de mudar.

# Regras de corretude:
#   - divisões e restos só são dobrados ou removidos se o divisor for uma
#     constante diferente de zero (senão poderiam eliminar um erro);
#   - leituras de vetor (load) nunca são removidas: podem estar fora dos
#     limites;
#   - chamadas de função invalidam o que se sabe sobre variáveis globais,
#     pois a função chamada pode alterá-las;
#   - aritmética float não é dobrada: o arredondamento em compilação poderia
#     diferir do da execução (só itof de inteiros pequenos, que é exato).

import re

from src.ir.interpretador import palavras, literal, int32, divisao_c

LIMITE_ITERACOES = 60


# Forma estruturada

class Instrucao:
    """Uma instrução da IR.

    tipo      forma textual
    copia     dest = a
    binaria   dest = a op b
    unaria    dest = op a              (not, neg, itof, ctoi)
    load      dest = load alvo[a]
    store     store alvo[a], b
    param     param a                  (a pode ser None)
    call      dest = call alvo, n      (dest pode ser None)
    return    return a                 (a pode ser None)
    print     print a
    read      read dest
    goto      goto alvo
    iffalse   ifFalse a goto alvo
    iftrue    ifTrue a goto alvo
    rotulo    alvo:
    """

    def __init__(self, tipo, dest=None, op=None, a=None, b=None, alvo=None, n=None):
        self.tipo, self.dest, self.op = tipo, dest, op
        self.a, self.b, self.alvo, self.n = a, b, alvo, n

    def __str__(self):
        t = self.tipo
        if t == "copia":   return f"  {self.dest} = {self.a}"
        if t == "binaria": return f"  {self.dest} = {self.a} {self.op} {self.b}"
        if t == "unaria":  return f"  {self.dest} = {self.op} {self.a}"
        if t == "load":    return f"  {self.dest} = load {self.alvo}[{self.a}]"
        if t == "store":   return f"  store {self.alvo}[{self.a}], {self.b}"
        if t == "param":   return "  param" + (f" {self.a}" if self.a is not None else "")
        if t == "call":
            chamada = f"call {self.alvo}, {self.n}"
            return f"  {self.dest} = {chamada}" if self.dest else f"  {chamada}"
        if t == "return":  return "  return" + (f" {self.a}" if self.a is not None else "")
        if t == "print":   return f"  print {self.a}"
        if t == "read":    return f"  read {self.dest}"
        if t == "goto":    return f"  goto {self.alvo}"
        if t == "iffalse": return f"  ifFalse {self.a} goto {self.alvo}"
        if t == "iftrue":  return f"  ifTrue {self.a} goto {self.alvo}"
        if t == "rotulo":  return f"{self.alvo}:"
        raise ValueError(t)

    # Operandos lidos pela instrução (campos "a" e "b"), sem literais.
    def campos_lidos(self):
        if self.tipo in ("copia", "unaria", "load", "param", "return",
                         "print", "iffalse", "iftrue"):
            return ["a"]
        if self.tipo in ("binaria", "store"):
            return ["a", "b"]
        return []

    def usos(self):
        return [getattr(self, c) for c in self.campos_lidos()
                if eh_variavel(getattr(self, c))]

    def definicao(self):
        if self.tipo in ("copia", "binaria", "unaria", "load", "call", "read"):
            return self.dest
        return None

    def removivel(self):
        """Pode ser apagada se o resultado não for usado? (sem efeitos)"""
        if self.tipo in ("copia", "unaria"):
            return True
        if self.tipo == "binaria":
            if self.op in ("/", "%"):
                return divisor_seguro(self.b)
            return True
        return False   # load, call, read e comandos têm efeitos ou podem falhar


def eh_variavel(operando):
    return operando is not None and literal(operando) is None


def divisor_seguro(b):
    v = literal(b)
    return isinstance(v, int) and not isinstance(v, bool) and v != 0


def ler_instrucao(linha):
    """Converte uma linha de IR (sem func/endfunc/global) em Instrucao."""
    l = linha.strip()
    m = re.fullmatch(r"([A-Za-z_][\w#]*):", l)
    if m:
        return Instrucao("rotulo", alvo=m.group(1))
    p = palavras(l)
    if p[0] == "goto":
        return Instrucao("goto", alvo=p[1])
    if p[0] in ("ifFalse", "ifTrue"):
        return Instrucao(p[0].lower(), a=p[1], alvo=p[3])
    if p[0] == "param":
        return Instrucao("param", a=p[1] if len(p) > 1 else None)
    if p[0] == "call":
        return Instrucao("call", alvo=p[1], n=int(p[3]))
    if p[0] == "return":
        return Instrucao("return", a=p[1] if len(p) > 1 else None)
    if p[0] == "print":
        return Instrucao("print", a=l[len("print"):].strip())
    if p[0] == "read":
        return Instrucao("read", dest=p[1])
    if p[0] == "store":
        m = re.fullmatch(r"store\s+(\S+?)\[(.+)\]\s*,\s*(.+)", l)
        return Instrucao("store", alvo=m.group(1), a=m.group(2).strip(), b=m.group(3).strip())
    if len(p) >= 3 and p[1] == "=":
        dest, r = p[0], p[2:]
        if r[0] == "call":
            return Instrucao("call", dest=dest, alvo=r[1], n=int(r[3]))
        if r[0] == "load":
            m = re.fullmatch(r"load\s+(\S+?)\[(.+)\]", l.split("=", 1)[1].strip())
            return Instrucao("load", dest=dest, alvo=m.group(1), a=m.group(2).strip())
        if len(r) == 2:
            return Instrucao("unaria", dest=dest, op=r[0], a=r[1])
        if len(r) == 3:
            return Instrucao("binaria", dest=dest, a=r[0], op=r[1], b=r[2])
        if len(r) == 1:
            return Instrucao("copia", dest=dest, a=r[0])
    raise ValueError(f"instrução de IR não reconhecida: {linha}")


class Funcao:
    def __init__(self, cabecalho):
        self.cabecalho = cabecalho
        self.instrucoes = []
        m = re.fullmatch(r"func\s+\S+?\s*(?:\((.*)\))?", cabecalho)
        self.parametros = [p.strip() for p in ((m and m.group(1)) or "").split(",")
                           if p.strip()]


def ler_programa(linhas):
    """Separa a IR em linhas de globais e funções estruturadas."""
    globais, funcoes = [], []
    atual = None
    for linha in linhas:
        l = linha.strip()
        if not l:
            continue
        if l.startswith("global "):
            globais.append(l)
        elif l.startswith("func "):
            atual = Funcao(l)
            funcoes.append(atual)
        elif l == "endfunc":
            atual = None
        else:
            atual.instrucoes.append(ler_instrucao(l))
    return globais, funcoes


def nomes_globais(linhas_globais):
    return {l[len("global "):].split("[")[0].strip() for l in linhas_globais}


# Blocos básicos e grafo de fluxo

DESVIOS = ("goto", "iffalse", "iftrue", "return")


def blocos_basicos(instrucoes):
    """Líderes: a primeira instrução, todo rótulo e toda instrução logo
    após um desvio. Cada bloco vai de um líder até antes do próximo."""
    blocos, atual = [], []
    for ins in instrucoes:
        if ins.tipo == "rotulo" and atual:
            blocos.append(atual)
            atual = []
        atual.append(ins)
        if ins.tipo in DESVIOS:
            blocos.append(atual)
            atual = []
    if atual:
        blocos.append(atual)
    return blocos


def sucessores(blocos):
    """Para cada bloco, os índices dos blocos que podem executar a seguir."""
    rotulo_bloco = {b[0].alvo: i for i, b in enumerate(blocos) if b[0].tipo == "rotulo"}
    succ = []
    for i, bloco in enumerate(blocos):
        ultima = bloco[-1]
        proximo = [i + 1] if i + 1 < len(blocos) else []
        if ultima.tipo == "goto":
            succ.append([rotulo_bloco[ultima.alvo]])
        elif ultima.tipo in ("iffalse", "iftrue"):
            succ.append(sorted(set([rotulo_bloco[ultima.alvo]] + proximo)))
        elif ultima.tipo == "return":
            succ.append([])
        else:
            succ.append(proximo)
    return succ


# Dobra de constantes e identidades algébricas

def tipo_literal(texto):
    v = literal(texto)
    if v is None:
        return None
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    return "char" if texto.startswith("'") else "string"


def texto_literal(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


COMPARACOES = {"<": lambda x, y: x < y, ">": lambda x, y: x > y,
               "<=": lambda x, y: x <= y, ">=": lambda x, y: x >= y,
               "==": lambda x, y: x == y, "!=": lambda x, y: x != y}


def dobrar_binaria(op, a, b):
    ta, tb = tipo_literal(a), tipo_literal(b)
    if ta is None or ta != tb:
        return None
    x, y = literal(a), literal(b)

    if ta == "int":
        if op == "+": return int32(x + y)
        if op == "-": return int32(x - y)
        if op == "*": return int32(x * y)
        if op in ("/", "%"):
            if y == 0:
                return None   # erro de execução: preserva a instrução
            return int32(divisao_c(x, y, resto=(op == "%")))
        if op in COMPARACOES: return COMPARACOES[op](x, y)
    if ta == "bool":
        if op == "and": return x and y
        if op == "or":  return x or y
        if op == "==":  return x == y
        if op == "!=":  return x != y
    if ta == "char" and op in COMPARACOES:
        return COMPARACOES[op](ord(x), ord(y))
    return None   # float e cadeias: não dobrados


def simplificar_algebrica(op, a, b):
    ta, tb = tipo_literal(a), tipo_literal(b)
    va, vb = literal(a), literal(b)
    int_b = tb == "int"
    int_a = ta == "int"
    if op == "+":
        if int_b and vb == 0: return a
        if int_a and va == 0: return b
    if op == "-" and int_b and vb == 0: return a
    if op == "*":
        if int_b and vb == 1: return a
        if int_a and va == 1: return b
        if (int_b and vb == 0) or (int_a and va == 0): return "0"
    if op == "/" and int_b and vb == 1: return a
    if op in ("and", "or"):
        neutro, absorvente = (True, False) if op == "and" else (False, True)
        for lit, outro in ((a, b), (b, a)):
            if tipo_literal(lit) == "bool":
                return outro if literal(lit) == neutro else texto_literal(absorvente)
    return None


def dobrar_unaria(op, a):
    t, v = tipo_literal(a), literal(a)
    if op == "not" and t == "bool": return not v
    if op == "neg" and t == "int":  return int32(-v)
    if op == "ctoi" and t == "char": return ord(v)
    if op == "itof" and t == "int" and abs(v) <= 2 ** 24:   # exato em float
        return float(v)
    return None


def simplificar(ins):
    if ins.tipo == "binaria":
        v = dobrar_binaria(ins.op, ins.a, ins.b)
        if v is not None:
            ins.tipo, ins.a, ins.op, ins.b = "copia", texto_literal(v), None, None
            return True
        r = simplificar_algebrica(ins.op, ins.a, ins.b)
        if r is not None:
            ins.tipo, ins.a, ins.op, ins.b = "copia", r, None, None
            return True
    elif ins.tipo == "unaria":
        v = dobrar_unaria(ins.op, ins.a)
        if v is not None:
            ins.tipo, ins.a, ins.op = "copia", texto_literal(v), None
            return True
    return False


# Passagem local: propagação, dobra e subexpressões comuns

COMUTATIVOS = {"+", "*", "==", "!=", "and", "or"}


def chave(ins):
    a, b = ins.a, ins.b
    if ins.op in COMUTATIVOS and b < a:
        a, b = b, a
    return (ins.op, a, b)


def otimizar_bloco(bloco, globais):
    mudou = False
    valores = {}      # variável -> constante ou variável que ela copia
    disponiveis = {}  # (op, a, b) -> variável que já guarda o resultado

    def esquecer(var):
        for k in [k for k, v in valores.items() if k == var or v == var]:
            del valores[k]
        for k in [k for k, v in disponiveis.items() if v == var or var in k[1:]]:
            del disponiveis[k]

    for ins in bloco:
        # 1. Propagação de constantes e cópias nos operandos lidos.
        for campo in ins.campos_lidos():
            atual = getattr(ins, campo)
            if atual in valores:
                setattr(ins, campo, valores[atual])
                mudou = True

        # 2. Dobra de constantes e identidades algébricas.
        mudou |= simplificar(ins)

        # 3. Subexpressão comum: o mesmo cálculo já está numa variável.
        if ins.tipo == "binaria" and chave(ins) in disponiveis:
            ins.tipo, ins.a, ins.op, ins.b = "copia", disponiveis[chave(ins)], None, None
            mudou = True

        # 4. Atualiza o que se sabe depois da instrução.
        destino = ins.definicao()
        if destino is not None:
            esquecer(destino)
            if ins.tipo == "copia" and ins.a != destino:
                valores[destino] = ins.a
            elif ins.tipo == "binaria" and destino not in (ins.a, ins.b):
                disponiveis[chave(ins)] = destino
        if ins.tipo == "call":
            for g in globais:    # a função chamada pode alterar globais
                esquecer(g)
    return mudou


# Variáveis vivas e código morto

def usos_com_globais(ins, globais):
    usos = set(ins.usos())
    if ins.tipo in ("call", "return"):
        usos |= globais   # a chamada ou quem chamou pode ler globais
    return usos


def variaveis_vivas(blocos, succ, globais):
    use, defs = [], []
    for bloco in blocos:
        u, d = set(), set()
        for ins in bloco:
            u |= usos_com_globais(ins, globais) - d
            if ins.definicao():
                d.add(ins.definicao())
        use.append(u)
        defs.append(d)

    entrada = [set() for _ in blocos]
    saida = [set() for _ in blocos]
    mudou = True
    while mudou:
        mudou = False
        for i in reversed(range(len(blocos))):
            novo_out = set().union(*(entrada[s] for s in succ[i])) if succ[i] else set()
            novo_in = use[i] | (novo_out - defs[i])
            if novo_out != saida[i] or novo_in != entrada[i]:
                saida[i], entrada[i] = novo_out, novo_in
                mudou = True
    return saida, entrada


def eliminar_codigo_morto(blocos, globais):
    succ = sucessores(blocos)
    saida, _ = variaveis_vivas(blocos, succ, globais)
    mudou = False
    for i, bloco in enumerate(blocos):
        vivas = set(saida[i])
        for j in reversed(range(len(bloco))):
            ins = bloco[j]
            destino = ins.definicao()
            if ins.tipo == "copia" and ins.a == destino:
                bloco[j] = None       # x = x
                mudou = True
                continue
            # Coalescência: "t = <cálculo>; x = t" com t morto depois da
            # cópia vira "x = <cálculo>". O conjunto de vivas depois da
            # instrução anterior passa a ser exatamente o de agora.
            anterior = bloco[j - 1] if j > 0 else None
            if (ins.tipo == "copia" and eh_variavel(ins.a) and ins.a not in vivas
                    and anterior is not None and anterior.definicao() == ins.a
                    and anterior.tipo in ("copia", "binaria", "unaria", "load", "call")):
                anterior.dest = destino
                bloco[j] = None
                mudou = True
                continue
            if destino is not None and destino not in vivas:
                if ins.removivel():
                    bloco[j] = None
                    mudou = True
                    continue
                if ins.tipo == "call":
                    ins.dest = None   # o resultado é descartado; a chamada fica
                    mudou = True
            if destino is not None:
                vivas.discard(destino)
            vivas |= usos_com_globais(ins, globais)
        bloco[:] = [ins for ins in bloco if ins is not None]
    return mudou


# Ponto de entrada

# Propagação global de constantes 
# Reticulado por variável: ausente no dicionário = UNDEF (nenhuma definição
# vista); um literal = constante; NAC = "não é constante".

NAC = object()


def encontro(estados):
    resultado = {}
    for estado in estados:
        for var, valor in estado.items():
            if var not in resultado:
                resultado[var] = valor
            elif resultado[var] is not NAC and resultado[var] != valor:
                resultado[var] = NAC
    return resultado


def valor_de(operando, estado):
    if not eh_variavel(operando):
        return operando
    return estado.get(operando)    # None = UNDEF


def transferir(ins, estado, globais):
    destino = ins.definicao()
    if destino is not None:
        if ins.tipo == "copia":
            v = valor_de(ins.a, estado)
        elif ins.tipo in ("binaria", "unaria"):
            a = valor_de(ins.a, estado)
            b = valor_de(ins.b, estado) if ins.tipo == "binaria" else None
            if a is None or a is NAC or (ins.tipo == "binaria" and (b is None or b is NAC)):
                v = NAC
            else:
                r = (dobrar_binaria(ins.op, a, b) if ins.tipo == "binaria"
                     else dobrar_unaria(ins.op, a))
                v = NAC if r is None else texto_literal(r)
        else:
            v = NAC        # load, call, read: valor desconhecido
        if v is None:
            estado.pop(destino, None)
        else:
            estado[destino] = v
    if ins.tipo == "call":
        for g in globais:  # a função chamada pode alterar globais
            estado[g] = NAC


def propagar_constantes_global(blocos, funcao, globais):
    succ = sucessores(blocos)
    pred = [[] for _ in blocos]
    for i, ss in enumerate(succ):
        for j in ss:
            pred[j].append(i)

    # Na entrada da função, parâmetros e globais têm valor desconhecido.
    estado_entrada = {v: NAC for v in list(funcao.parametros) + list(globais)}
    saida = [None] * len(blocos)    # None: bloco ainda não alcançado
    entrada = [None] * len(blocos)

    pendentes = list(range(len(blocos)))
    while pendentes:
        i = pendentes.pop(0)
        anteriores = [saida[p] for p in pred[i] if saida[p] is not None]
        if i == 0:
            anteriores.append(estado_entrada)
        if not anteriores:
            continue
        estado = encontro(anteriores)
        entrada[i] = dict(estado)
        for ins in blocos[i]:
            transferir(ins, estado, globais)
        if estado != saida[i]:
            saida[i] = estado
            pendentes.extend(j for j in succ[i] if j not in pendentes)

    mudou = False
    for i, bloco in enumerate(blocos):
        if entrada[i] is None:
            continue    # inalcançável: removido por outra passagem
        estado = dict(entrada[i])
        for ins in bloco:
            for campo in ins.campos_lidos():
                atual = getattr(ins, campo)
                v = estado.get(atual) if eh_variavel(atual) else None
                if v is not None and v is not NAC:
                    setattr(ins, campo, v)
                    mudou = True
            transferir(ins, estado, globais)
    return mudou


# Desvios, código inalcançável e saltos

def dobrar_desvios(instrucoes):
    """ifFalse/ifTrue com condição constante viram goto ou desaparecem."""
    mudou = False
    for k, ins in enumerate(instrucoes):
        if ins.tipo in ("iffalse", "iftrue") and tipo_literal(ins.a) == "bool":
            salta = literal(ins.a) == (ins.tipo == "iftrue")
            instrucoes[k] = Instrucao("goto", alvo=ins.alvo) if salta else None
            mudou = True
    instrucoes[:] = [ins for ins in instrucoes if ins is not None]
    return mudou


def remover_inalcancavel(instrucoes):
    """Mantém só os blocos alcançáveis a partir da entrada da função."""
    blocos = blocos_basicos(instrucoes)
    if not blocos:
        return instrucoes, False
    succ = sucessores(blocos)
    alcancados, pilha = {0}, [0]
    while pilha:
        for j in succ[pilha.pop()]:
            if j not in alcancados:
                alcancados.add(j)
                pilha.append(j)
    if len(alcancados) == len(blocos):
        return instrucoes, False
    return [ins for i, b in enumerate(blocos) if i in alcancados for ins in b], True


def limpar_saltos(instrucoes):
    mudou = False

    # Saltos encadeados: "goto L" onde L: goto M  ->  goto M.
    def destino_final(rotulo):
        vistos = set()
        while rotulo not in vistos:
            vistos.add(rotulo)
            k = next(i for i, x in enumerate(instrucoes)
                     if x.tipo == "rotulo" and x.alvo == rotulo)
            seguinte = next((x for x in instrucoes[k + 1:] if x.tipo != "rotulo"), None)
            if seguinte is None or seguinte.tipo != "goto":
                break
            rotulo = seguinte.alvo
        return rotulo

    for ins in instrucoes:
        if ins.tipo in ("goto", "iffalse", "iftrue"):
            novo = destino_final(ins.alvo)
            if novo != ins.alvo:
                ins.alvo = novo
                mudou = True

    # Inversão de desvio:
    #   ifFalse c goto L1; goto L2; L1:   ->   ifTrue c goto L2; L1:
    invertidas = []
    k = 0
    while k < len(instrucoes):
        ins = instrucoes[k]
        seguinte = instrucoes[k + 1] if k + 1 < len(instrucoes) else None
        if (ins.tipo in ("iffalse", "iftrue") and seguinte is not None
                and seguinte.tipo == "goto"):
            rotulos_depois = set()
            for x in instrucoes[k + 2:]:
                if x.tipo != "rotulo":
                    break
                rotulos_depois.add(x.alvo)
            if ins.alvo in rotulos_depois:
                tipo = "iftrue" if ins.tipo == "iffalse" else "iffalse"
                invertidas.append(Instrucao(tipo, a=ins.a, alvo=seguinte.alvo))
                k += 2
                mudou = True
                continue
        invertidas.append(ins)
        k += 1
    instrucoes = invertidas

    # Salto para o rótulo que vem logo a seguir: inútil (a condição de um
    # ifFalse é só um operando, sem efeitos).
    resultado = []
    for k, ins in enumerate(instrucoes):
        if ins.tipo in ("goto", "iffalse", "iftrue"):
            rotulos_seguintes = set()
            for x in instrucoes[k + 1:]:
                if x.tipo != "rotulo":
                    break
                rotulos_seguintes.add(x.alvo)
            if ins.alvo in rotulos_seguintes:
                mudou = True
                continue
        resultado.append(ins)

    # Rótulos sem nenhum salto para eles.
    usados = {x.alvo for x in resultado if x.tipo in ("goto", "iffalse", "iftrue")}
    final = [x for x in resultado if x.tipo != "rotulo" or x.alvo in usados]
    return final, mudou or len(final) != len(resultado)


# Laços: dominadores, laços naturais e código invariante

def predecessores(succ):
    pred = [[] for _ in succ]
    for i, ss in enumerate(succ):
        for j in ss:
            pred[j].append(i)
    return pred


def dominadores(succ):
    n = len(succ)
    pred = predecessores(succ)
    todos = set(range(n))
    dom = [set(todos) for _ in range(n)]
    dom[0] = {0}
    mudou = True
    while mudou:
        mudou = False
        for i in range(1, n):
            anteriores = [dom[p] for p in pred[i]]
            novo = {i} | (set.intersection(*anteriores) if anteriores else set())
            if novo != dom[i]:
                dom[i] = novo
                mudou = True
    return dom


def lacos_naturais(blocos):
    succ = sucessores(blocos)
    pred = predecessores(succ)
    dom = dominadores(succ)
    lacos = {}
    for a, ss in enumerate(succ):
        for h in ss:
            if h in dom[a]:                   # aresta de retorno
                corpo, pilha = {h, a}, [a]
                while pilha:
                    for p in pred[pilha.pop()]:
                        if p not in corpo:
                            corpo.add(p)
                            pilha.append(p)
                lacos.setdefault(h, set()).update(corpo)
    return lacos


def novo_rotulo(instrucoes, base):
    existentes = {x.alvo for x in instrucoes if x.tipo == "rotulo"}
    k = 1
    while f"{base}{k}" in existentes:
        k += 1
    return f"{base}{k}"


def mover_invariantes(instrucoes, globais):
    blocos = blocos_basicos(instrucoes)
    if not blocos:
        return instrucoes, False
    succ = sucessores(blocos)
    pred = predecessores(succ)
    _, vivas_entrada = variaveis_vivas(blocos, succ, globais)

    for h, corpo in sorted(lacos_naturais(blocos).items(), key=lambda kv: len(kv[1])):
        instr_laco = [ins for i in sorted(corpo) for ins in blocos[i]]

        # O que o laço modifica: destinos e, se há chamada, as globais.
        definicoes = {}
        for ins in instr_laco:
            if ins.definicao():
                definicoes[ins.definicao()] = definicoes.get(ins.definicao(), 0) + 1
        modificadas = set(definicoes)
        if any(ins.tipo == "call" for ins in instr_laco):
            modificadas |= globais

        movidas, destinos_movidos = [], set()
        divididas = []   # (instrução no laço, temporário novo)
        achou = True
        while achou:
            achou = False
            for ins in instr_laco:
                if ins in movidas or ins.tipo not in ("copia", "binaria", "unaria"):
                    continue
                if any(ins is d for d, _ in divididas):
                    continue
                destino = ins.definicao()
                if not ins.removivel() or definicoes.get(destino) != 1:
                    continue      # efeito / pode falhar / mais de uma definição
                if not all(not eh_variavel(op) or op not in modificadas
                           or op in destinos_movidos for op in ins.usos()):
                    continue      # algum operando muda dentro do laço
                if destino in vivas_entrada[h] or destino in globais:
                    # O valor anterior do destino ainda é usado (ou o laço
                    # pode não executar): só o CÁLCULO sai do laço, para um
                    # temporário novo; a atribuição fica. Cópias não são
                    # divididas (isso se repetiria indefinidamente).
                    if ins.tipo != "copia":
                        divididas.append((ins, None))
                        achou = True
                    continue
                movidas.append(ins)                      # ordem = dependências
                destinos_movidos.add(destino)
                achou = True
        if not movidas and not divididas:
            continue

        # Cada instrução dividida: "x = a * b" no laço vira "x = tN", e
        # "tN = a * b" vai para o pré-cabeçalho, depois das outras movidas.
        usados = {op for x in instrucoes for op in (x.dest, x.a, x.b) if op}
        n_temp = max([int(m.group(1)) for u in usados
                      for m in [re.fullmatch(r"t(\d+)", u)] if m] + [0])
        for k, (ins, _) in enumerate(divididas):
            n_temp += 1
            temp = f"t{n_temp}"
            calculo = Instrucao(ins.tipo, dest=temp, op=ins.op, a=ins.a, b=ins.b)
            movidas.append(calculo)
            ins.tipo, ins.a, ins.op, ins.b = "copia", temp, None, None

        # Pré-cabeçalho: as instruções movidas ficam logo antes do rótulo do
        # cabeçalho, onde o bloco anterior no código cai. Se esse bloco for
        # parte do laço e cair no cabeçalho, não há onde colocá-las.
        anterior = h - 1
        if anterior in corpo and h in succ[anterior] and blocos[anterior][-1].tipo != "goto":
            continue

        # Entradas que SALTAM para o cabeçalho vindas de fora do laço passam
        # a saltar para um rótulo novo, antes das instruções movidas.
        entradas = [p for p in pred[h] if p not in corpo
                    and blocos[p][-1].tipo in ("goto", "iffalse", "iftrue")
                    and blocos[h][0].tipo == "rotulo"
                    and blocos[p][-1].alvo == blocos[h][0].alvo]
        pre = []
        if entradas:
            rotulo_pre = novo_rotulo(instrucoes, "L_pre")
            for p in entradas:
                blocos[p][-1].alvo = rotulo_pre
            pre.append(Instrucao("rotulo", alvo=rotulo_pre))

        removidas = {id(x) for x in movidas}
        for i in corpo:
            blocos[i][:] = [x for x in blocos[i] if id(x) not in removidas]
        resultado = []
        for i, bloco in enumerate(blocos):
            if i == h:
                resultado += pre + movidas
            resultado += bloco
        return resultado, True

    return instrucoes, False


# Ciclo de otimização

def otimizar_funcao(funcao, globais):
    for _ in range(LIMITE_ITERACOES):
        mudou = False

        blocos = blocos_basicos(funcao.instrucoes)
        mudou |= propagar_constantes_global(blocos, funcao, globais)
        for bloco in blocos:
            mudou |= otimizar_bloco(bloco, globais)
        instrucoes = [ins for bloco in blocos for ins in bloco]

        mudou |= dobrar_desvios(instrucoes)
        instrucoes, m = remover_inalcancavel(instrucoes)
        mudou |= m
        instrucoes, m = limpar_saltos(instrucoes)
        mudou |= m

        blocos = blocos_basicos(instrucoes)
        mudou |= eliminar_codigo_morto(blocos, globais)
        instrucoes = [ins for bloco in blocos for ins in bloco]

        instrucoes, m = mover_invariantes(instrucoes, globais)
        mudou |= m
        funcao.instrucoes = instrucoes
        if not mudou:
            break


def renumerar_temporarios(linhas):
    mapa = {}

    def trocar(m):
        if m.group(0)[0] in "'\"":
            return m.group(0)          # literal char/cadeia: não mexe
        return mapa.setdefault(m.group(0), f"t{len(mapa) + 1}")

    padrao = r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])'|\bt\d+\b(?!#)"
    return [re.sub(padrao, trocar, l) for l in linhas]


def otimizar(linhas):
    linhas_globais, funcoes = ler_programa(linhas)
    globais = nomes_globais(linhas_globais)

    saida = list(linhas_globais)
    for funcao in funcoes:
        otimizar_funcao(funcao, globais)
        corpo = renumerar_temporarios([str(ins) for ins in funcao.instrucoes])
        saida += [funcao.cabecalho] + corpo + ["endfunc"]
    return saida
