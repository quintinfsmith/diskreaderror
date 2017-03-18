from ctypes import CDLL, c_int, c_double
import os
import sys
import time
import threading
import random
from MidiLib.MidiInterpreter import MIDIInterpreter

# Using wiringPi, so the pins numbers are a bit funky
# wiringPi  :   GPIO    :   BCM (Rv2)
#   0       :   11      :   17
#   1       :   12      :   18
#   2       :   13      :   21 (27)
#   3       :   15      :   22
#   4       :   16      :   23
#   5       :   18      :   24
#   6       :   22      :   25
#   7       :   7       :   4
#   8       :   3       :   0   (2)
#   9       :   5       :   1   (3)
#   10      :   24      :   8
#   11      :   26      :   7
#   12      :   19      :   10
#   13      :   21      :   9
#   14      :   23      :   11
#   15      :   8       :   14
#   16      :   10      :   15

#PINS = [(2, 3)]
#PINS = [(1, 0), (7, 6), (9, 8), (11, 10),(2, 3), (4, 5)]
PINS = [(1, 0), (2,3), (7, 6), (9, 8), (11, 10)]

SAMPLE_SIZE = 200

#CFDDC = CDLL("./fddcontroller.so")
CFDDC = CDLL("./fddtest.so")
CFDDC.setup()

class FDD(object):
    def __init__(self, index, step, direction):
        self.id = index + 0
        self.step_pin = step
        self.dir_pin = direction
        self.in_use = False
        CFDDC.setup_fddmon(c_int(index), c_int(step), c_int(direction))

    def note_on(self, wave):
        self.in_use = True
        succ = CFDDC.play_fdd(c_int(self.id), c_int(int(wave)))
        return

    def note_off(self):
        self.in_use = False
        CFDDC.stop_fdd(c_int(self.id))
        return

class ActiveController(object):
    '''Read Input from Midi Device'''
    def __init__(self, midipath="/dev/midi1"):
        self.connected = os.path.exists(midipath)
        if not self.connected:
            self.pipe = open('/dev/zero', 'rb')
        else:
            self.pipe = open(midipath, 'rb')

    def read(self):
        p = self.pipe.read(1)
        return p[0]

    def close(self):
        self.pipe.close()

class PassiveController(object):
    def __init__(self, ticks, initial_ppqn):
        self.initial_ppqn = initial_ppqn
        self.ticks = ticks
        self.fake_pipe = []
        self.playing = False

    def start(self):
        thread = threading.Thread(target=self.__play)
        thread.daemon = True
        thread.start()

    def read(self):
        while not self.fake_pipe:
            pass
        return self.fake_pipe.pop(0)

    def close(self):
        self.fake_pipe = []
        self.playing = False

    def __play(self):
        time.sleep(.2) # Give the controller time to call read() before playing
        ptick = 0
        start = time.time()
        self.playing = True
        seconds_per_tick = 60 / (self.initial_ppqn * 120)
        delay_accum = 0

        for x, t in enumerate(self.ticks):
            tick, events = t

            delay = (tick - ptick) * seconds_per_tick # ideal delay
            drift = delay_accum - (time.time() - start) # how much the timing has drifted
            delay_accum += delay
            time.sleep(max(0, delay + drift))
            ptick = tick

            for event in events:
                if event.eid == event.SET_TEMPO:
                    bpm = 60000000 / event.tempo
                    seconds_per_tick =  60 / (self.initial_ppqn * bpm)
                elif event.eid == event.NOTE_ON:
                    if event.velocity > 0:
                        first_byte = 0x90 | event.channel
                        second_byte = event.note
                        third_byte = event.velocity
                        self.fake_pipe.append(first_byte)
                        self.fake_pipe.append(second_byte)
                        self.fake_pipe.append(third_byte)
                    else:
                        first_byte = 0x80 | event.channel
                        second_byte = event.note
                        self.fake_pipe.append(first_byte)
                        self.fake_pipe.append(second_byte)
                        self.fake_pipe.append(0)
                elif event.eid == event.NOTE_OFF:
                    first_byte = 0x80 | event.channel
                    second_byte = event.note
                    self.fake_pipe.append(first_byte)
                    self.fake_pipe.append(second_byte)
                    self.fake_pipe.append(0)
        self.playing = False

class FDDC(object):
    def __init__(self, pinout=None):
        if not pinout:
            pinout = []


        self.fdds = []
        self.available = []
        self.in_use = {}
        self.playing = False
        for i, pair in enumerate(pinout):
            new_fdd = FDD(i, pair[0], pair[1])
            self.fdds.append(new_fdd)
            self.available.append(i)
        self.lambdahash = {}
        base_freq = 27.50
        base_note = 21
        for i in range(88):
            f = ((2 ** (i / 12.0)) * base_freq)
            n = base_note + i
            wavelength = (1000000 / f)
            self.lambdahash[n] = wavelength

    def get_available_fdd(self):
        if self.available:
            return self.available.pop()
        else:
            return -1

    def purge_all(self):
        for fdd in self.available:
            print(fdd)
            CFDDC.purge(c_int(fdd))

    def play_note(self, note, channel):
        if (note, channel) in self.in_use.keys():
            return

        fdd_index = self.get_available_fdd()
        if fdd_index == -1:
            return

        self.in_use[(note, channel)] = fdd_index
        self.fdds[fdd_index].note_on(self.lambdahash[note])

    def stop_note(self, note, channel):
        try:
            fdd_index = self.in_use[(note, channel)]
            self.available.append(fdd_index)
            del self.in_use[(note, channel)]
            self.fdds[fdd_index].note_off()
        except KeyError:
            return

    def play(self, controller):
        self.playing = True
        print("Playing")
        os.system("clear")
        sys.stdout.write("\033[?25l\n")
        
        while self.playing:
            sys.stdout.write("\033[0;0H\n")
            try:
                byte_one = controller.read()
                if byte_one & 0xF0 == 0x90:
                    note = controller.read()
                    controller.read() # velocity
                    self.play_note(note, byte_one & 0x0F)
                elif byte_one & 0xF0 == 0x80:
                    note = controller.read()
                    controller.read() # velocity
                    self.stop_note(note, byte_one & 0x0F)
            except KeyboardInterrupt:
                self.playing = False
            for i, fdd in enumerate(self.fdds):
                if i in self.available: state = "0"
                else: state = "1"
                sys.stdout.write("%d: %s\n" % (i, state))
            sys.stdout.write("%s                      \n" % str(self.in_use))
        sys.stdout.write("\033[?25h\n")
        print("Done")

    def passive_play(self, midilike):
        ticks = []
        for tick in range(len(midilike)):
            tmp_events = []
            for track in midilike.tracks:
                for event in track.get_events(tick):
                    if event.eid == event.NOTE_ON or event.eid == event.NOTE_OFF or event.eid == event.SET_TEMPO:
                        tmp_events.append(event)
            if tmp_events:
                ticks.append((tick, tmp_events))
            tmp_events = sorted(tmp_events, key=getKey, reverse=True)
        passive_controller = PassiveController(ticks, midilike.ppqn)
        passive_controller.start()
        self.play(passive_controller)
        #CFDDC.wait_for_end()

    def active_play(self):
        active = ActiveController()
        self.play(active)

def getKey(item):
    return item.eid

if __name__ == "__main__":
    fddc = FDDC(PINS)
    CFDDC.play_fdd_loop()
    fddc.purge_all()
    if len(sys.argv) > 1:
        mi = MIDIInterpreter()
        fddc.passive_play(mi(sys.argv[1]))
    else:
        fddc.active_play()
    CFDDC.kill_loop()
