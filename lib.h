void play_fdd(int fddpos, int step_pin, int dir_pin, double wavelength);
void stop_fdd(int fddpos);
void* local_play_fdd(void *fdda);
void setup();
void setup_fddmon(int fddpos, int step, int dir);
void wait_for_end();
