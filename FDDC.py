from ctypes import CDLL, c_int, c_double
import os
import sys
import time
import threading
import random
from MidiInterpreter import MIDIInterpreter

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

PINS = [(1, 0)]
# PINS = [(1, 0), (2, 3), (4, 5), (7, 6), (9, 8), (11, 10)]

CFDDC = CDLL("./liblib.so")
CFDDC.setup()

def dither(wavelength):
    sample_size = 100
    n = round(wavelength * sample_size, 0)
    out = [0] * sample_size
    i = 0
    for _ in range(n):
        out[i] += 1
        i = (i + 1) % sample_size
    for  x in range( sample_size ):
        while True:
            a = random.randint(0, sample_size - 1)
            if out[a] > 1:
                break
            b = random.randint(0, sample_size - 1)
            out[a] -= 1
            out[b] += 1
    random.shuffle(out)
    return out

class FDD(object):
    def __init__(self, index, step, direction):
        self.id = index + 0
        self.step_pin = step
        self.dir_pin = direction
        self.in_use = False
        CFDDC.setup_fddmon(index, step, direction)

    def note_on(self, wave):
        self.in_use = True
        carr = (c_int * len(wave))(*wave)
        CFDDC.play_fdd(c_int(self.id), c_int(self.step_pin), c_int(self.dir_pin), c_int(len(wave)), carr)
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
    def __init__(self, ticks, seconds_per_tick):
        self.spt = seconds_per_tick
        self.ticks = ticks
        self.fake_pipe = []
        self.playing = False

    def read(self):
        if not self.playing:
            thread = threading.Thread(target=self.__play)
            thread.daemon = True
            thread.start()

        while not self.fake_pipe:
            pass
        return self.fake_pipe.pop(0)

    def close(self):
        self.fake_pipe = []
        self.playing = False

    def __play(self):
        time.sleep(1) # Give the controller a second to call read() before playing
        ptick = 0
        start = time.time()
        self.playing = True
        for x, t in enumerate(self.ticks):
            tick, events = t
            delay = (tick - ptick) * self.spt # ideal delay
            drift = (ptick * self.spt) - (time.time() - start) # how much the timing has drifted
            time.sleep(max(0, delay + drift))
            for event in events:
                if event.eid == event.NOTE_ON:
                    if event.velocity != 0:
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
        self.available = set()
        self.in_use = {}
        self.playing = False
        for i, pair in enumerate(pinout):
            new_fdd = FDD(i, pair[0], pair[1])
            self.fdds.append(new_fdd)
            self.available.add(i)
        self.lambdahash = {}
        base_freq = 27.50 / 2 # Bring down 1 octaves
        base_note = 21
        for i in range(88):
            f = ((2 ** (i / 12.0)) * base_freq)
            n = base_note + i
            wave = dither(1000 / f)
            self.lambdahash[n] = wave

    def get_available_fdd(self):
        if self.available:
            return self.available.pop()
        else:
            return -1

    def play_note(self, note):
        fdd_index = self.get_available_fdd()
        if fdd_index == -1:
            return

        self.in_use[note] = fdd_index
        self.fdds[fdd_index].note_on(self.lambdahash[note])

    def stop_note(self, note):
        try:
            fdd_index = self.in_use[note]
            self.available.add(fdd_index)
            del self.in_use[note]
            self.fdds[fdd_index].note_off()
        except KeyError:
            return

    def play(self, controller):
        self.playing = True
        print("Playing")
        while self.playing:
            try:
                byte_one = controller.read()
                if byte_one & 0xF0 == 0x90:
                    note = controller.read()
                    controller.read() # velocity
                    self.play_note(note)
                elif byte_one & 0xF0 == 0x80:
                    note = controller.read()
                    controller.read() # velocity
                    self.stop_note(note)
            except KeyboardInterrupt:
                self.playing = False
        print("Done")

    def passive_play(self, midilike):
        ticks_per_second = midilike.tpqn * 1.5
        seconds_per_tick = 1 / ticks_per_second

        ticks = []
        for tick in range(len(midilike)):
            tmp_events = []
            for track in midilike.tracks:
                for event in track.get_events(tick):
                    if event.eid == event.NOTE_ON or event.eid == event.NOTE_OFF:
                        tmp_events.append(event)
            if tmp_events:
                ticks.append((tick, tmp_events))
        passive_controller = PassiveController(ticks, seconds_per_tick)
        self.play(passive_controller)
        CFDDC.wait_for_end()

    def active_play(self):
        active = ActiveController()
        self.play(active)

if __name__ == "__main__":
    a = dither(1.14)
    print(sum(a) / len(a))

    sys.exit()
    fddc = FDDC(PINS)
    if len(sys.argv) > 1:
        mi = MIDIInterpreter()
        fddc.passive_play(mi(sys.argv[1]))
    else:
        fddc.active_play()
