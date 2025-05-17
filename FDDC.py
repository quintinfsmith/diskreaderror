from ctypes import CDLL, c_int, c_double
from __future__ import annotations

import os
import sys
import time
import threading
import random
import tty
import termios
import math
import json

from apres import MIDI, NoteOn, NoteOff, SetTempo

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

PINS = [(9, 8), (16, 15), (4, 1), (2, 0), (11, 10), (12, 3), (6, 5), (14, 13)]

SAMPLE_SIZE = 200
CFDDC = CDLL("./fddcontroller.so")
CFDDC.setup()

class FDD(object):
    def __init__(self, index, step, direction):
        self.id = index + 0
        self.step_pin = step
        self.dir_pin = direction
        self.in_use = False
        CFDDC.setup_fddmon(c_int(self.id), c_int(step), c_int(direction))

    def get_direction(self):
        return CFDDC.get_direction(self.id)

    def get_index(self):
        return CFDDC.get_index(self.id)

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
                if isinstance(event, SetTempo):
                    seconds_per_tick =  60 / (self.initial_ppqn * event.get_bpm())
                elif isinstance(event, NoteOn) and event.channel != 9:
                    if event.velocity > 0:
                        self.fake_pipe.extend(list(bytes(event)))
                    else:
                        new_event = NoteOff(
                            channel=event.channel,
                            note=event.note,
                            velocity=event.velocity
                        )
                        self.fake_pipe.extend(list(bytes(new_event)))
                elif isinstance(event, NoteOff) and event.channel != 9:
                    self.fake_pipe.extend(list(bytes(event)))

        self.playing = False

class FDDC(object):

    fdd_channel_map = [list(range(8))] * 16
    reqmap = {}
    # index'd by Midi Channel, value is fdd index

    # TODO: Do this nicer
    def __init__(self, pinout=None):
        if not pinout:
            pinout = []

        # The note at which multiple fdds are required to be able to hear it
        self.high_threshold = 81

        self.available = []
        self.fdds = []
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

    def reset_map(self):
        self.fdd_channel_map = [[],[],[],[],[],[],[],[],[],[],[],[],[],[],[],[]]
    def reset_reqmap(self):
        self.reqmap = {}

    def set_map(self, channel, fdds):
    self.fdd_channel_map[channel] = fdds
    def set_fdds_per_note(self, channel, count):
        self.reqmap[channel] = count

    def release_fdd(self, index):
        self.available.append(index)

    def get_available_fdd(self, note, channel):
        potentials = self.fdd_channel_map[channel]

        a_index = -1
        for i, a in enumerate(self.available):
            for j, p in enumerate(self.fdd_channel_map[channel]):
                if p == a:
                    a_index = i
                    break

            if a_index != -1:
                break

        index = -1
        if a_index != -1:
            index = self.available.pop(a_index)

        return index


    def purge_all(self):
        for fdd in self.available:
            CFDDC.purge(c_int(fdd))

    def play_note(self, note, channel):
        if (note, channel) in self.in_use.keys():
            return

        try:
            req = self.reqmap[channel]
        except:
            req = 1

        fdd_indecies = []

        for _ in range(req):
            fdd_index = self.get_available_fdd(note, channel)

            if fdd_index == -1 and not fdd_indecies:
                return

            fdd_indecies.append(fdd_index)

            self.fdds[fdd_index].note_on(self.lambdahash[note])

        self.in_use[(note, channel)] = fdd_indecies

    def stop_note(self, note, channel):
        try:
            fdd_indexes = self.in_use[(note, channel)]
            for fdd_index in fdd_indexes:
                self.release_fdd(fdd_index)
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

        #thread = threading.Thread(target=self.visualizer_thread)
        #thread.start()

        while self.playing:
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


    def passive_play(self, midilike):
        ticks = {}
        all_events = midilike.get_all_events()
        for tick, event in midilike.get_all_events():
            if not tick in ticks:
                ticks[tick] = []
            if type(event) in [NoteOn, NoteOff, SetTempo]:
                ticks[tick].append(event)
        sorted_ticks = []
        for tick, events in ticks.items():
            sorted_ticks.append((tick, sorted(events, key=getKey)))
        sorted_ticks.sort()

        passive_controller = PassiveController(sorted_ticks, midilike.ppqn)
        self.play(passive_controller)
        #CFDDC.wait_for_end()

    def active_play(self):
        fddc.set_maps(**{
            "req": {
                0: 4,
                1: 1,
                2: 2
            },
            "map": {
                "0": [0,1,2,3],
                "1": [6],
                "2": [4, 5]
            }
        })

        active = ActiveController()
        self.play(active)

def getKey(item):
    if isinstance(item, NoteOff):
        return 1
    elif isinstance(item, NoteOn):
        return 2
    else:
        return 3

def parse_args(argv: list[str]) -> tuple[list[str], dict, dict]:
    mapped_fdds = {}
    req_fdds = {}
    paths = []

    m_active = False
    r_active = False
    for arg in argv:
        if m_active:
            i_str, drives_unsplit = arg.split(":")
            drives_split = drives_str.split(",")
            mapped_fdds[int(i_str)] = [drives_split[int(x)] for x in drives_split]
            m_active = False
        elif r_active:
            i_str, count = arg.split(":")
            req_fdds[int(i_str)] = int(count)
            r_active = False
        elif arg == "-m":
            m_active = True
        elif arg == "-r"
            r_active = True
        else:
            paths.append(arg)

    return (path, mapped_fdds, req_fdds)



if __name__ == "__main__":
    try:
        paths, fdd_maps, channel_counts = parse_args(sys.argv[1:])
    except Exception as e:
        print(""" Usage:
python FDDC.py [options] [midi_path]
Options:
    -m i:j,k,l      Map channel i to Floppy drives in comma delimited list
    -r i:n          Channel i will play n drives per note (for volume)
""")

    fddc = FDDC(PINS)
    fddc.purge_all()

    if fdd_maps:
        fddc.reset_map()
        for (key, fdds) in fdd_maps:
            fddc.set_map[key] = fdds

    if channel_counts:
        for (channel, count) in channel_counts:
            fddc.set_req_map(channel, count)

    if paths:
        for file_path in paths:
            CFDDC.play_fdd_loop()
            filename = file_path[file_path.rfind("/") + 1:]
            if filename in maps.keys():
                fddc.set_maps(**maps[filename])
            ml = MIDI.load(file_path)
            fddc.passive_play(ml)
            CFDDC.kill_loop()
    else:
        CFDDC.play_fdd_loop()
        fddc.active_play()
        CFDDC.kill_loop()

