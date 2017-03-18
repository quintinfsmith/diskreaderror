#include <wiringPi.h>
#include <pthread.h>
#include <stdio.h>
#include <sys/mman.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdlib.h>

#define ST_BASE (0x20003000)
#define TIMER_OFFSET (4)


struct FDDMon {
    int index, direction, active, step, dir, wavelength;
    int w_index, state;
};

static int RUNNING = 0;
static int FDDCOUNT = 5;
static struct FDDMon fddmon[5];
static pthread_t mainloop;

void setup() {
    wiringPiSetup();
}

void setup_fddmon(int token, int step, int dir) {
    pinMode(step, OUTPUT);
    pinMode(dir, OUTPUT);
    digitalWrite(step, 0);
    digitalWrite(dir, 0);

    fddmon[token].index = 0;
    fddmon[token].w_index = 0;
    fddmon[token].direction = 0;
    fddmon[token].active = 0;
    fddmon[token].state = 0;
    fddmon[token].step = step;
    fddmon[token].dir = dir;
}

void* _play_fdd_loop() {
    int x;
    long long int t, prev, *timer;
    int fd;
    void *st_base;
    if (-1 == (fd = open("/dev/mem", O_RDONLY))) {
        fprintf(stderr, "open() failed.\n");
        return NULL;
    }

    if (MAP_FAILED == (st_base = mmap(NULL, 4096, PROT_READ, MAP_SHARED, fd, ST_BASE))) {
        fprintf(stderr, "mmap() failed.\n");
        return NULL;
    }

    timer = (long long int *)((char *)st_base + TIMER_OFFSET);
    prev = *timer;
    RUNNING = 1;
    while (RUNNING) {
        t = *timer;
        for (x = 0; x < FDDCOUNT; x++) {
            if (fddmon[x].active) {
                fddmon[x].w_index += (t - prev);
                if (fddmon[x].w_index >= fddmon[x].wavelength) {
                    fddmon[x].w_index = 0;
                    digitalWrite(fddmon[x].step, fddmon[x].state);
                    fddmon[x].state = ~fddmon[x].state;
                    fddmon[x].index++;
                    if (fddmon[x].index == 120) {
                        fddmon[x].index = 0;
                        digitalWrite(fddmon[x].dir, fddmon[x].direction);
                        fddmon[x].direction = ~fddmon[x].direction;
                    }
                }
            }
        }
        prev = t;
    }
    return NULL;
}

void play_fdd_loop() {
    pthread_create(&mainloop, NULL, &_play_fdd_loop, NULL);
    pthread_detach(mainloop);
}


void play_fdd(int token, int wavelength) {
    fddmon[token].active = 1;
    fddmon[token].w_index = wavelength;
    fddmon[token].wavelength = wavelength;
}

void stop_fdd(int token) {
    fddmon[token].active = 0;
}

void kill_loop() {
    RUNNING = 0;
}

