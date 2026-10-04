animal_shogi.so: animal_shogi.c animal_shogi.h hot_layout.ld
	gcc -O2 -fno-semantic-interposition -march=native -ffunction-sections animal_shogi.c -o animal_shogi.so -Wall -fPIC -shared -Wl,-T,hot_layout.ld
