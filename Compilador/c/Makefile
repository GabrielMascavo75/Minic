CC=gcc
CFLAGS=-std=c11 -Wall -Wextra -O2

minic: minic.c util.c util.h scanner.c scanner.h arvore.c arvore.h parser.c parser.h semantic.c semantic.h ir.c ir.h
	$(CC) $(CFLAGS) minic.c -o $@

clean:
	rm -f minic
