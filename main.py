from si4703 import SI4703
from machine import I2C, Pin, SPI
import time
import st7789
import vga2_bold_16x32
import vga2_8x8
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
        self.wakeup_time = None

    async def update_time(self):
        while True:
            self.show_time()
            await asyncio.sleep(1)

    def show_time(self):
        import utime
        tm = utime.localtime()
        time_str = "{:02}:{:02}:{:02}".format(tm[3], tm[4], tm[5])
        self.display.text(vga2_bold_16x32, time_str, 50, 200, st7789.WHITE, st7789.BLACK)

    def set_wakeup_time(self, wakeup_time):
        self.wakeup_time = wakeup_time

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

class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

class Application:
    background = st7789.BLACK
    foreground = st7789.WHITE

    def __init__(self, name, display, radio, main_coords, mini_coords, selected):
        self.name = name
        self.display = display
        self.radio = radio
        self.main_coords = main_coords
        self.mini_coords = mini_coords
        self.selected = selected

    def get_fg_bg_color(self):
        if self.selected:
            return Application.background, Application.foreground
        else:
            return Application.foreground, Application.background

    def print_mini(self):
        fg, bg = self.get_fg_bg_color()
        self.display.text(vga2_8x8, self.name, self.mini_coords.x, self.mini_coords.y, fg, bg)

class RadioApp(Application):
#    def __init__(self, display, radio):
#        super().__init__(display, radio)

    async def event(self):
        pass

class AlarmApp(Application):

    async def event(self):
        pass

class ApplicationHandler:
    def __init__(self):
        self.rotary_flag = RotaryFlag()
        self.rotary_button_flag = PushButtonFlag()
        self.ko_button_flag = PushButtonFlag()

        self.pin_a = Pin(26, Pin.IN)
        self.pin_b = Pin(25, Pin.IN)
        self.rotary_button = Pin(33, Pin.IN)
        self.pin_a.irq(trigger=Pin.IRQ_FALLING, handler=self.rotary_handler)
        self.rotary_button.irq(trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, handler=self.rotary_button_handler)

        self.pin_ko = Pin(32, Pin.IN)
        self.pin_ko.irq(trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, handler=self.ko_handler)

        spi = SPI(2, baudrate=40000000, polarity=1, phase=1, sck=Pin(16), mosi=Pin(17))
        self.display = st7789.ST7789(spi, 240, 320, reset=Pin(5, Pin.OUT), dc=Pin(18, Pin.OUT), backlight=Pin(19, Pin.OUT), rotation=1, color_order=st7789.RGB)
        self.display.inversion_mode(False)
        self.display.init()

        self.clock = Clock(self.display)

        # Radio init
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

        self.radio = SI4703(i2c, reset_pin, sen_pin, irq_pin)

        try:
            ntptime.host = "fr.pool.ntp.org"
            ntptime.settime()
        except Exception as e:
            print("Failed to sync time: {}".format(e))

        self.clock.show_time()

        main_coords = Point(0, 100)

        self.apps = [ RadioApp("Radio", self.display, self.radio, main_coords, Point(240, 0), True ),
                      AlarmApp("Alarm1", self.display, self.radio, main_coords, Point(240, 40), False ),
                      AlarmApp("Alarm2", self.display, self.radio, main_coords, Point(240, 80), False ),
                    ]

        self.display.vline(238, 0, 240, st7789.WHITE)

        for ctr, app in enumerate(self.apps):
            self.display.hline(238, ctr*40, 42, st7789.WHITE)
            app.print_mini()

    def rotary_handler(self, pin):
        a_state = self.pin_a.value()
        b_state = self.pin_b.value()
        if a_state == 0 and b_state == 1:
            print("Rotated clockwise")
            self.rotary_flag.set_cw()
        elif a_state == 0 and b_state == 0:
            print("Rotated counter-clockwise")
            self.rotary_flag.set_ccw()

    def rotary_button_handler(self, pin):
        state = pin.value()
        if state == 0:
            print("Rotary button pressed")
            self.rotary_button_flag.set_pressed()
        else:
            print("Rotary button released")
            self.rotary_button_flag.set_released()

    def ko_handler(self, pin):
        state = pin.value()
        if state == 0:
            print("KO button pressed")
            self.ko_button_flag.set_pressed()
            # Implement KO button functionality here
        else:
            print("KO button released")
            self.ko_button_flag.set_released()
            # Implement KO button release functionality here

    def tuned_handler(self, frequency, rssi):
        print("Tuned to frequency: {:.1f} MHz, RSSI: {}".format(frequency, rssi))
        self.radio.enable_rds(True)  # Enable RDS when tuned

    def basic_tuning_handler(self, text):
        print("RDS Basic Tuning Text: {}".format(text))
        self.display.text(vga2_bold_16x32, text, 50, 100, st7789.WHITE, st7789.BLACK)

    def radio_text_handler(self, text):
        print("RDS Radio Text: {}".format(text))

    def start_radio(self):
        self.radio.power_cristal(True)
        self.radio.enable(True)
        self.radio.set_tuned_irq(self.tuned_handler)
        self.radio.set_basic_tuning_handler(self.basic_tuning_handler)
        self.radio.set_radio_text_irq(self.radio_text_handler)
        self.radio.set_frequency(98.2)   # Set frequency to 98.2 MHz
        self.radio.set_volume(15)         # Set volume to lowest level
        self.radio.mute(False)           # Unmute the audio

    async def rotary_task(self):
        while True:
            await self.rotary_flag.wait()
            if self.rotary_flag.cw:
                print("Rotary event: clockwise")
                self.radio.seek_up()
            else:
                print("Rotary event: counter-clockwise")
                self.radio.seek_down()

    async def rotary_button_task(self):
        while True:
            await self.rotary_button_flag.wait()
            if self.rotary_button_flag.pressed:
                print("Rotary button event: pressed")
                self.radio.mute(True)
            else:
                print("Rotary button event: released")
                self.radio.mute(False)

    async def ko_button_task(self):
        while True:
            await self.ko_button_flag.wait()
            if self.ko_button_flag.pressed:
                print("KO button event: pressed")
                # Implement KO button functionality here
            else:
                print("KO button event: released")
                # Implement KO button release functionality here

    async def main(self):
        asyncio.create_task(self.clock.update_time())
        asyncio.create_task(self.rotary_task())
        asyncio.create_task(self.rotary_button_task())
        asyncio.create_task(self.ko_button_task())
        while True:
            await asyncio.sleep(1)

app = ApplicationHandler()
app.start_radio()

asyncio.run(app.main())
