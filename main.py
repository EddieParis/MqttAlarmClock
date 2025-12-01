from si4703 import SI4703
from machine import I2C, Pin, SPI
import time
import st7789
import vga2_bold_16x32
import ntptime
import uasyncio as asyncio

# display
# BLK 19
# A 26
# B 25
# push 33
# KO 32


class Clock:
    def __init__(self, display):
        self.display = display

    async def update_time(self):
        while True:
            self.show_time()
            await asyncio.sleep(1)

    def show_time(self):
        import utime
        tm = utime.localtime()
        time_str = "{:02}:{:02}:{:02}".format(tm[3], tm[4], tm[5])
        self.display.text(vga2_bold_16x32, time_str, 50, 200, st7789.WHITE, st7789.BLACK)

spi = SPI(2, baudrate=40000000, polarity=1, phase=1, sck=Pin(16), mosi=Pin(17))
display = st7789.ST7789(spi, 240, 320, reset=Pin(5, Pin.OUT), dc=Pin(18, Pin.OUT), backlight=Pin(19, Pin.OUT), rotation=1, color_order=st7789.RGB)
display.inversion_mode(False)
display.init()

clock = Clock(display)

try:
    ntptime.host = "fr.pool.ntp.org"
    ntptime.settime()
except Exception as e:
    print("Failed to sync time: {}".format(e))

clock.show_time()

pin_a = Pin(26, Pin.IN)
pin_b = Pin(25, Pin.IN)
push_button = Pin(33, Pin.IN)

class RotaryFlag(asyncio.ThreadSafeFlag):
    def __init__(self):
        super().__init__()
        self.cw = True

    def set_cw(self):
        self.cw = True
        self.set()

    def set_ccw(self):
        self.cw = False
        self.set()    

class PushButtonFlag(asyncio.ThreadSafeFlag):
    def __init__(self):
        super().__init__()
        self.pressed = False

    def set_pressed(self):
        self.pressed = True
        self.set()

    def set_released(self):
        self.pressed = False
        self.set()



rotary_flag = RotaryFlag()

def rotary_handler(pin):
    global rotary_flag
    a_state = pin_a.value()
    b_state = pin_b.value()
    if a_state == 0 and b_state == 1:
        print("Rotated clockwise")
        rotary_flag.set_cw()
    elif a_state == 0 and b_state == 0:
        print("Rotated counter-clockwise")
        rotary_flag.set_ccw()

push_button_flag = PushButtonFlag()

def push_button_handler(pin):
    global push_button_flag
    state = pin.value()
    if state == 0:
        print("Push button pressed")
        push_button_flag.set_pressed()
    else:
        print("Push button released")
        push_button_flag.set_released()

pin_a.irq(trigger=Pin.IRQ_FALLING, handler=rotary_handler)
push_button.irq(trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, handler=push_button_handler)

sda = Pin(21, Pin.OUT)
scl = Pin(22, Pin.OUT)

sen_pin = Pin(0, Pin.OUT)
reset_pin = Pin(27, Pin.OUT)
irq_pin = Pin(14, Pin.IN, Pin.PULL_UP)

sda.value(0)
sen_pin.value(1)    # Enable I2C mode

# Reset the chip
reset_pin.value(0)
time.sleep(0.2)
reset_pin.value(1)
time.sleep(0.1)

sda.value(1)
i2c = I2C(1, scl=scl, sda=sda, freq=400000)

radio = SI4703(i2c, reset_pin, sen_pin, irq_pin)

old_radio_text = ""

def tuned_handler(frequency, rssi):
    print("Tuned to frequency: {:.1f} MHz, RSSI: {}".format(frequency, rssi))
    radio.enable_rds(True)  # Enable RDS when tuned

def basic_tuning_handler(text):
    global old_radio_text
    if text != old_radio_text:
        global display
        print("RDS Basic Tuning Text: {}".format(text))
        old_radio_text = text
        display.text(vga2_bold_16x32, text, 50, 100, st7789.WHITE, st7789.BLACK)

def radio_text_handler(text):
    print("RDS Radio Text: {}".format(text))

radio.power_cristal(True)
radio.enable(True)
radio.set_tuned_irq(tuned_handler)
radio.set_basic_tuning_handler(basic_tuning_handler)
radio.set_radio_text_irq(radio_text_handler)
radio.set_frequency(98.2)   # Set frequency to 98.2 MHz
radio.set_volume(15)         # Set volume to lowest level
radio.mute(False)           # Unmute the audio

radio.seek_down()

async def rotary_task():
    global rotary_flag
    while True:
        await rotary_flag.wait()
        if rotary_flag.cw:
            print("Rotary event: clockwise")
            radio.seek_up()
        else:
            print("Rotary event: counter-clockwise")
            radio.seek_down()
        rotary_flag.clear()

async def push_button_task():
    global push_button_flag
    while True:
        await push_button_flag.wait()
        if push_button_flag.pressed:
            print("Push button event: pressed")
            radio.mute(True)
        else:
            print("Push button event: released")
            radio.mute(False)
        push_button_flag.clear()

async def main():
    asyncio.create_task(clock.update_time())
    asyncio.create_task(rotary_task())
    asyncio.create_task(push_button_task())
    while True:
        await asyncio.sleep(1)

asyncio.run(main())