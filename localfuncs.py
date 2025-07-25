import os
import tty
import termios
import sys

def get_terminal_size():
    '''return dimensions of current terminal session'''
    height, width = os.popen("stty size", "r").read().split()
    return (int(width), int(height))

def read_character():
    '''Read character from stdin'''
    init_fileno = sys.stdin.fileno() # store original pipe n
    init_attr = termios.tcgetattr(init_fileno)  # store original input settings
    try:
        tty.setraw(sys.stdin.fileno()) # remove wait for "return"
        ch = sys.stdin.read(1) # Read single character into memory
    finally:
        termios.tcsetattr(init_fileno, termios.TCSADRAIN, init_attr) # reset input settings
    return ch

def from_twos_comp(n, bits=8):
    '''Convert two's compliment representation of n'''
    f = 0
    for _ in range(bits):
        f <<= 2
        f += 1
    return (n - 1).__xor__(f)

def to_twos_comp(n, bits=8):
    '''Get two's compliment representation of n'''
    f = 0
    for _ in range(bits):
        f <<= 2
        f += 1
    return n.__xor__(f)

def pop_n(queue, nbytes=1):
    '''Get first N bytes from byte list'''
    out = 0
    for _ in range(nbytes):
        out <<=8
        out += int(queue.pop(0))
    return out

def get_variable_length(queue):
    '''Calculate variable length integer from byte list'''
    n = 0
    while True:
        n <<= 7
        c = int(queue.pop(0))
        n += c & 0x7F
        if not c & 0x80:
            break
    return n

def to_variable_length(n):
    '''create variable length byte list from integer'''
    out = []
    first = True
    while n > 0 or first:
        tmp = n & 0x7F
        n >>= 7
        if first:
            tmp |= 0x00
        else:
            tmp |= 0x80
        out.append(tmp)
        first = False
    out.reverse()
    return bytes(out)

def to_bytes(n, l=4):
    '''create byte list representation of integer'''
    out = b""
    first = True
    while n > 0 or first:
        out = bytes([n % 256]) + out
        n = int(n / 256)
        first = False

    out = (b"\x00" * (l - len(out))) + out
    return out
