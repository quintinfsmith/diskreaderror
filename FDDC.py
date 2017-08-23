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
PINS = [(0, 2), (3, 12), (13, 14), (8, 9), (15, 16)]

SAMPLE_SIZE = 200

CFDDC = CDLL("./fddcontroller.so")
#CFDDC = CDLL("./fddtest.so")
CFDDC.setup()

class FDD(object):
    def __init__(self, index, step, direction):
        self.id = index + 0
        self.step_pin = step
        self.dir_pin = direction
        self.in_use = False
        CFDDC.setup_fddmon(c_int(self.id), c_int(step), c_int(direction))

    def note_on(self, wave):
        self.in_use = True
        succ = CFDDC.play_fdd(c_int(self.id), c_int(int(wave)))

    def note_off(self):
        self.in_use = False
        CFDDC.stop_fdd(c_int(self.id))

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

    def start(self):
        pass

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
        ptick = 0
        time.sleep(.4)
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
        self.fake_pipe.append(0xFF)
        self.fake_pipe.append(0x2F)
        self.fake_pipe.append(0x00)
        self.playing = False

class FDDC(object):
    def __init__(self, pinout=None):
        if not pinout:
            pinout = []

        self.high_threshold = 81 # The note at which multiple fdds are required to be able to hear it
        self.fdds = []
        self.available = []
        self.in_use = {}
        self.playing = False
        for i, pair in enumerate(pinout):
            new_fdd = FDD(i, pair[0], pair[1])
            self.fdds.append(new_fdd)
            self.available.append(i)
        self.lambdahash = {}
        base_freq = 16.35 #27.50
        base_note = 12 #21
        for i in range(127):
            f = ((2 ** (i / 12.0)) * base_freq)
            n = base_note + i
            wavelength = (1000000 / f)
            self.lambdahash[n] = wavelength

    def get_available_fdd(self):
        if self.available:
            return self.available.pop(0)
        else:
            return -1

    def purge_all(self):
        for fdd in self.available:
            CFDDC.purge(c_int(fdd))

    def play_note(self, note, channel):
        if (note, channel) in self.in_use.keys():
            return

        if note > self.high_threshold:
            req = 2
        else:
            req = 1

        fdd_indecies = []

        for _ in range(req):
            fdd_index = self.get_available_fdd()
            if fdd_index == -1 and not fdd_indecies:
                return
            fdd_indecies.append(fdd_index)
            self.fdds[fdd_index].note_on(self.lambdahash[note])

        self.in_use[(note, channel)] = fdd_indecies

    def stop_note(self, note, channel):
        try:
            fdd_indexes = self.in_use[(note, channel)]
            for fdd_index in fdd_indexes:
                self.available.append(fdd_index)
                self.fdds[fdd_index].note_off()

            del self.in_use[(note, channel)]
        except KeyError:
            return

    def test(self):
        for x in range(1):
            for i in range(12):
                self.play_note(60 + i, 1)
                time.sleep(.1)
            for i in range(12):
                self.stop_note(60 + i, 1)
                time.sleep(.1)

    def play(self, controller):
        controller.start()
        self.playing = True
        print("Playing")
        os.system("clear")
        sys.stdout.write("\033[?25l\n")

        display_offsets = [
            [0, 0], [17, 5],
            [0, 15], [17, 20],
            [0, 30]
        ]
        
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
                elif byte_one == 0xFF:
                    if controller.read() == 0x2F and controller.read() == 0x00:
                        self.playing = False
            except KeyboardInterrupt:
                self.playing = False

            for i, fdd in enumerate(self.fdds):
                if i in self.available:
                    colorbg =  41
                    colorfg =  30
                else:
                    colorbg =  44
                    colorfg =  34
                offx, offy = display_offsets[i]
                for y in range(14):
                    sys.stdout.write("\033[%s;%sH\033[%d;%dm              " % (y + offy, offx, colorbg, colorfg))
                    sys.stdout.write("\033[%s;%sH\033[0m" % (y + offy, offx + 30))
        
        sys.stdout.write("\033[?25h\n")
        os.system("clear")

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
        self.play(passive_controller)
        #CFDDC.wait_for_end()

    def active_play(self):
        active = ActiveController()
        self.play(active)

def getKey(item):
    return item.eid

if __name__ == "__main__":
    fddc = FDDC(PINS)
    fddc.purge_all()
    CFDDC.play_fdd_loop()
    if len(sys.argv) > 1:
        mi = MIDIInterpreter()
        ml = mi(sys.argv[1])
        fddc.passive_play(ml)
    else:
        fddc.active_play()
    CFDDC.kill_loop()
