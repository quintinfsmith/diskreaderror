void setup(int fddcount);
void setup_fddmon(int token, int step, int dir);
void play_fdd_loop();
int _play_fdd_loop();
void play_fdd(int token, int wavelength);
void purge(int token);
void stop_fdd(int token);
int get_direction(int token);
void kill_loop();
