#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <wiringPi.h>

struct FDDARGS {
    int token; int step; int dir;
    int wavesize;
    int* wave;
};

struct FDDMon {
    int index, direction, active;
};

static struct FDDMon fddmon[8];
static pthread_t threads[8];

void setup() {
    wiringPiSetup();
}

void setup_fddmon(int token, int step, int dir) {
    pinMode(step, OUTPUT);
    pinMode(dir, OUTPUT);
    digitalWrite(step, 0);
    digitalWrite(dir, 0);
    fddmon[token].index = 0;
    fddmon[token].direction = 0;
    fddmon[token].active = 0;
}

void* local_play_fdd(void *fdda) {
    struct FDDARGS *data = fdda;
    int step = data->step;
    int dir = data->dir;
    int token = data->token;
    int wavesize = data->wavesize;
    int* wave = data->wave;
    int state = 0;
    int position = 0;

    printf("FDD: %d Active\n", token);

    fddmon[token].active = 1;
    while (fddmon[token].active == 1) {
        delay(wave[position]);
        position++;
        position %= wavesize;

        digitalWrite(step, state);
        digitalWrite(dir, fddmon[token].direction);
        state = ~state;
        fddmon[token].index++;
        if (fddmon[token].index == 120) {
            fddmon[token].direction = ~fddmon[token].direction;
            fddmon[token].index = 0;
            digitalWrite(dir, fddmon[token].direction);
        }
    }
    return fdda;
}

void play_fdd(int token, int step_pin, int dir_pin, int wavesize, int* wave) {
    struct FDDARGS *fdd_args = calloc(1, sizeof(*fdd_args));
    fdd_args->token = token;
    fdd_args->step = step_pin;
    fdd_args->dir = dir_pin;
    fdd_args->wavesize = wavesize;
    fdd_args->wave = wave;
    pthread_create(&threads[token], NULL, &local_play_fdd, fdd_args);
}

void stop_fdd(int token) {
    fddmon[token].active = 0;
}

void wait_for_end() {
    int i;
    for (i = 0; i < 8; i++) {
       pthread_join(threads[i], NULL);
    }
}

