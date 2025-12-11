from si4703 import SI4703
from rotary import RotaryEncoder
from event import *

from machine import I2C, Pin, SPI

import time
import st7789
import vga2_bold_16x32
import vga2_8x8
import ntptime
import time
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
            curr_time = time.time()
            self.show_time()
            await asyncio.sleep(1)


    def show_time(self):
        import utime
        tm = utime.localtime()
        time_str = "{:02}:{:02}:{:02}".format(tm[3], tm[4], tm[5])
        self.display.text(vga2_bold_16x32, time_str, 50, 200, st7789.WHITE, st7789.BLACK)

    def set_wakeup_time(self, wakeup_time):
        self.wakeup_time = wakeup_time

class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

class Application:
    background = st7789.BLACK
    foreground = st7789.WHITE

    def __init__(self, name, main_app, main_coords, mini_coords, modes=[]):
        self.name = name
        self.display = main_app.display
        self.radio = main_app.radio
        self.main_app = main_app
        self.main_coords = main_coords
        self.mini_coords = mini_coords
        self.selected = False
        self.modes = modes
        self.mode_index = 0
        self.selected_mode = None

    def get_fg_bg_color(self):
        if self.selected:
            return Application.background, Application.foreground
        else:
            return Application.foreground, Application.background

    def print_mini(self):
        fg, bg = self.get_fg_bg_color()
        #self.display.fill_rect(self.mini_coords.x+2, self.mini_coords.y-2, 318-self.mini_coords.x, 36, bg)
        self.display.text(vga2_8x8, self.name, self.mini_coords.x+2, self.mini_coords.y-2, fg, bg)
        #self.display()

    def print_active(self):
        fg, bg = self.get_fg_bg_color()
        #self.display.fill_rect(self.main_coords.x, self.main_coords.y, 238, 220, bg)
        #self.display.text(vga2_8x8, "Radio", self.main_coords.x+2, self.main_coords.y+2, fg, bg)
        self.print_modes()

    def print_arrow_mode(self, clear_all=False):
        x = 8
        for ctr, mode in enumerate(self.modes):
            if ctr == self.mode_index and not clear_all:
                self.display.text(vga2_8x8, "\x1e", x, 8, Application.foreground)
            else:
                self.display.text(vga2_8x8, " ", x, 8, Application.foreground)
            x += len(mode.name)*8 + 16

    def print_modes(self, selected=None):
        x = 0
        for ctr, mode in enumerate(self.modes):
            #for prev_mode in self.modes[:ctr]:
            #    x += len(prev_mode)*8 + 16
            if selected is not None and ctr == selected:
                self.display.text(vga2_8x8, mode.name, x, 0, Application.background, Application.foreground)
            else:
                self.display.text(vga2_8x8, mode.name, x, 0, Application.foreground)
            x += len(mode.name)*8 + 16
        self.print_arrow_mode()

    def handle_event(self, event):
        if self.selected_mode is not None:
            self.selected_mode = self.selected_mode.handle_event(event)
            if self.selected_mode is None:
                self.print_modes()
        else:
            if event.type == Event.ROT_CW:
                self.mode_index += 1
                if self.mode_index > len(self.modes)-1:
                    self.mode_index = 0
                self.print_arrow_mode()
            elif event.type == Event.ROT_CCW:
                self.mode_index -= 1
                if self.mode_index < 0:
                    self.mode_index = len(self.modes)-1
                self.print_arrow_mode()
            elif event.type == Event.ROT_REL:
                #switch mode
                self.selected_mode = self.modes[self.mode_index]
                self.selected_mode.selected = True
                self.print_modes(selected=self.mode_index)
                self.print_arrow_mode(clear_all=True)
                self.handle_event(Event(Event.MODE_ENTER))
            elif event.type == Event.KO_PUSH:
                self.display.fill_rect(0, 0, 237, 16, Application.background)
                self.selected = False
                self.print_mini()
                self.print_arrow_mode(clear_all=True)
                return None
        return self

class Mode:
    def __init__(self, name):
        self.name = name

    def handle_event(self, event):
        if event.type == Event.KO_PUSH:
            return None
        return self

class RadioOn(Mode):
    def __init__(self, main_app):
        super().__init__("on")
        self.radio = main_app.radio
        self.main_app = main_app

    def handle_event(self, event):
        self.radio.mute(False)
        self.main_app.radio_on = True
        return None

class RadioOff(Mode):
    def __init__(self, main_app):
        super().__init__("off")
        self.radio = main_app.radio
        self.main_app = main_app

    def handle_event(self, event):
        self.radio.mute(True)
        self.main_app.radio_on = False
        return None

class RadioSeekMode(Mode):
    def __init__(self, main_app):
        super().__init__("seek")
        self.radio = main_app.radio
        self.display = main_app.display
        self.main_app = main_app

    def handle_event(self, event):
        if event.type == Event.ROT_CW:
            self.radio.seek_up()
        elif event.type == Event.ROT_CCW:
            self.radio.seek_down()
        elif event.type == Event.KO_PUSH:
            return None
        return self    

class RadioManualMode(Mode):
    def __init__(self, main_app):
        super().__init__("manual")
        self.radio = main_app.radio
        self.display = main_app.display
        self.main_app = main_app

    def handle_event(self, event):
        if event.type == Event.ROT_CW:
            self.radio.set_frequency((int(10*self.radio.get_frequency())+1)/10)
        elif event.type == Event.ROT_CCW:
            self.radio.set_frequency((int(10*self.radio.get_frequency())-1)/10)
        elif event.type == Event.KO_PUSH:
            return None
        return self

class RadioFavMode(Mode):
    def __init__(self, main_app):
        super().__init__("fav.")


class RadioApp(Application):

    def __init__(self, name, main_app, main_coords, mini_coords):
        modes = [ RadioOn(main_app),
                  RadioOff(main_app),
                  RadioSeekMode(main_app),
                  RadioManualMode(main_app),
                  RadioFavMode(main_app)
                ]
        super().__init__(name, main_app, main_coords, mini_coords, modes=modes)

class AlarmOn(Mode):
    def __init__(self, alarm_app):
        super().__init__("on")
        self.alarm_app = alarm_app

    def handle_event(self, event):
        self.alarm_app.active = True
        return None

class AlarmOff(Mode):
    def __init__(self, alarm_app):
        super().__init__("off")
        self.alarm_app = alarm_app  

    def handle_event(self, event):
        self.alarm_app.active = False
        return None

class AlarmStation(Mode):
    def __init__(self, alarm_app):
        super().__init__("station")
        self.alarm_app = alarm_app

class AlarmSet(Mode):
    def __init__(self, alarm_app):
        super().__init__("set")
        self.alarm_app = alarm_app
        self.hour = 0
        self.minute = 0
        self.setting_hour = True

    def handle_event(self, event):
        if event.type == Event.ROT_CW:
            if self.setting_hour:
                self.hour += 5 if event.fast else 1
                if self.hour > 23:
                    self.hour = 0
            else:
                self.minute += 5 if event.fast else 1
                if self.minute > 59:
                    self.minute = 0
        elif event.type == Event.ROT_CCW:
            if self.setting_hour:
                self.hour -= 5 if event.fast else 1
                if self.hour < 0:
                    self.hour = 23
            else:
                self.minute -= 5 if event.fast else 1
                if self.minute < 0:
                    self.minute = 59
        elif event.type == Event.ROT_REL:
            if self.setting_hour:
                self.setting_hour = False
            else:
                #finish setting
                self.alarm_app.wakeup = (self.hour, self.minute)
                self.setting_hour = False
                return None
        elif event.type == Event.KO_PUSH:
            return None
        self.print_time()
        return self

    def print_time(self):
        time_str = "{:02}:{:02}".format(self.hour, self.minute)
        fg, bg = self.alarm_app.get_fg_bg_color()
        self.alarm_app.display.text(vga2_bold_16x32, time_str, self.alarm_app.main_coords.x+50, self.alarm_app.main_coords.y+50, fg, bg)

class AlarmApp(Application):

    def __init__(self, name, main_app, main_coords, mini_coords):
        modes = [AlarmOn(self),
                 AlarmOff(self),
                 AlarmStation(self),
                 AlarmSet(self)]
        super().__init__(name, main_app, main_coords, mini_coords, modes=modes)
        self.wakeup = None
        self.active = False

    #async def handle_event(self):
    #    pass

    def print_mini(self):
        super().print_mini()
        status = "--:--"
        if self.wakeup:
            status = "07:40"

        status += " on" if self.active else " off"

        fg, bg = self.get_fg_bg_color()
        self.display.text(vga2_8x8, status, self.mini_coords.x+2, self.mini_coords.y+8, fg, bg)

class ApplicationHandler:
    def __init__(self):
        self.event_flag = asyncio.ThreadSafeFlag()
        self.events = EventsQueue(self.event_flag)

        self.pin_a = Pin(26, Pin.IN)
        self.pin_b = Pin(25, Pin.IN)
        self.rotary_button = Pin(33, Pin.IN)
        self.rotary = RotaryEncoder(self.pin_a, self.pin_b, self.rotary_button, self.events)

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

        self.apps = [ RadioApp("Radio", self, main_coords, Point(240, 10) ),
                      AlarmApp("Alarm1", self, main_coords, Point(240, 50) ),
                      AlarmApp("Alarm2", self, main_coords, Point(240, 94) ),
                    ]

        self.display.vline(238, 0, 240, st7789.WHITE)

        self.pre_app = 0
        self.selected_app = None

        self.radio_on = False
        self.setting_volume = False
        self.volume_set = False

        for ctr, app in enumerate(self.apps):
            self.display.hline(238, ctr*40, 82, st7789.WHITE)
            app.print_mini()

        self.print_arrow_app()

    def print_arrow_app(self, clear_all=False):
        y = 10
        for ctr, app in enumerate(self.apps):
            if ctr == self.pre_app and not clear_all:
                self.display.text(vga2_8x8, "\x10", 230, y, Application.foreground)
            else:
                self.display.text(vga2_8x8, " ", 230, y, Application.foreground)
            y += 40

    def handle_events(self):
        event = self.events.pop()
        while event is not None:
            if self.radio_on:
                # volume setting handling when radio is on
                # priority over app handling
                # pushing rotary button without rotation is considered as a normal click.
                if event.type == Event.ROT_PUSH:
                    self.setting_volume = True
                    event = self.events.pop()
                    continue
                elif self.setting_volume:
                    if event.type == Event.ROT_REL and self.volume_set:
                        self.setting_volume = False
                        self.volume_set = False
                        event = self.events.pop()
                        continue
                    elif event.type == Event.ROT_REL:
                        self.setting_volume = False
                    elif event.type == Event.ROT_CW :
                        # volume adjustment
                        self.radio.set_volume(self.radio.get_volume() + 1)
                        self.volume_set = True
                        event = self.events.pop()
                        continue
                    elif event.type == Event.ROT_CCW:
                        # volume adjustment
                        self.radio.set_volume(self.radio.get_volume() - 1)
                        self.volume_set = True
                        event = self.events.pop()
                        continue
            if self.selected_app is not None:
                self.selected_app = self.selected_app.handle_event(event)
                if self.selected_app is None:
                    self.print_arrow_app()
            else:
                if event.type == Event.ROT_CW:
                    self.pre_app += 1
                    if self.pre_app > len(self.apps)-1:
                        self.pre_app = 0
                    self.print_arrow_app()
                elif event.type == Event.ROT_CCW:
                    self.pre_app -= 1
                    if self.pre_app < 0:
                        self.pre_app = len(self.apps)-1
                    self.print_arrow_app()
                elif event.type == Event.ROT_PUSH:
                    if self.radio_on:
                        self.setting_volume = True
                elif event.type == Event.ROT_REL:
                    if self.setting_volume:
                        self.setting_volume = False
                    else:
                        #switch app
                        self.selected_app = self.apps[self.pre_app]
                        self.selected_app.selected = True
                        self.print_arrow_app(clear_all=True)
                        self.selected_app.print_mini()
                        self.selected_app.print_active()
            event = self.events.pop()

    def ko_handler(self, pin):
        state = pin.value()
        if state == 0:
            print("KO button pressed")
            self.events.push(Event(Event.KO_PUSH))
            # Implement KO button functionality here
        else:
            print("KO button released")
            self.events.push(Event(Event.KO_REL))
            # Implement KO button release functionality here

    def tuned_handler(self, frequency, rssi):
        print("Tuned to frequency: {:.1f} MHz, RSSI: {}".format(frequency, rssi))
        self.events.push(RadioTunedEvent(frequency, rssi))
        self.radio.enable_rds(True)  # Enable RDS when tuned

    def basic_tuning_handler(self, text):
        print("RDS Basic Tuning Text: {}".format(text))
        self.events.push(BasicTuningEvent(text))
        self.display.text(vga2_bold_16x32, text, 50, 100, st7789.WHITE, st7789.BLACK)

    def radio_text_handler(self, text):
        print("RDS Radio Text: {}".format(text))
        self.events.push(RadioTextEvent(text))

    def start_radio(self):
        self.radio.power_cristal(True)
        self.radio.enable(True)
        self.radio.set_tuned_irq(self.tuned_handler)
        self.radio.set_basic_tuning_handler(self.basic_tuning_handler)
        self.radio.set_radio_text_irq(self.radio_text_handler)
        self.radio.set_frequency(98.2)   # Set frequency to 98.2 MHz
        self.radio.set_volume(1)         # Set volume to lowest level
        self.radio.mute(False)           # Unmute the audio

    async def event_task(self):
        while True:
            await self.event_flag.wait()
            self.handle_events()

    async def main(self):
        asyncio.create_task(self.clock.update_time())
        asyncio.create_task(self.event_task())

        while True:
            await asyncio.sleep(1)

app = ApplicationHandler()
app.start_radio()

asyncio.run(app.main())
