import json
from si4703 import SI4703
from rotary import RotaryEncoder
from event import *

from machine import I2C, Pin, SPI

import st7789
import vga2_bold_16x32
import vga2_8x8
import ntptime
import utime
import uasyncio as asyncio

# display
# BLK 19
# A 26
# B 25
# push 33
# KO 32

SCREEN_WIDTH = 320
SCREEN_HEIGHT = 240

MINI_SPLIT_X = 240
MINI_APP_X_MARGIN = 4
MINI_APP_Y_MARGIN = 4
MINI_APP_HEIGHT = 40
MINI_APP_INNER_HEIGHT = MINI_APP_HEIGHT - 2*MINI_APP_Y_MARGIN

MAIN_AREA_X = 0
MAIN_AREA_Y = 20
MAIN_AREA_WIDTH = MINI_SPLIT_X
MAIN_AREA_HEIGHT = 64

class RadioHolder:
    def __init__(self, radio, radio_app):
        self.radio = radio
        self.radio_app = radio_app
        self.radio_on = False
        self.delay_task = None

    def set_volume(self, volume):
        self.radio.set_volume(volume)
        self.radio_app.print_mini()

    def set_radio_on(self, on):
        if self.delay_task is not None:
            self.delay_task.cancel()
            self.delay_task = None
        self.radio_app.sleep_time = None
        if on:
            self.radio.mute(False)
            self.radio_on = True
        else:
            self.radio.enable_rds(False)
            self.radio.mute(True)
            self.radio_on = False
        self.radio_app.print_mini()

    def delayed_off(self, delay_minutes):
        self.radio_app.print_mini()
        if self.delay_task is not None:
            self.delay_task.cancel()
            self.delay_task = None
        async def delayed_task():
            while self.radio_app.sleep_time is None or self.radio_app.sleep_time > 0:
                await asyncio.sleep(60)
                if self.radio_app.sleep_time is not None:
                    self.radio_app.sleep_time -= 1
                    self.radio_app.print_mini()
            self.delay_task = None
            self.radio_app.sleep_time = None
            self.radio_app.print_mini()
            self.set_radio_on(False)
        self.radio_app.sleep_time = delay_minutes
        self.delay_task = asyncio.create_task(delayed_task())

class Clock:
    def __init__(self, display, radio_holder, alarms, clock_app):
        self.display = display
        self.radio_holder = radio_holder
        self.alarms = alarms
        self.clock_app = clock_app

    async def update_time(self):
        while True:
            curr_time = utime.time()
            tm = utime.localtime()
            for alarm in self.alarms:
                if alarm.active and alarm.wakeup is not None:
                    if (tm[3], tm[4]) == alarm.wakeup and not alarm.ringing:
                        alarm.ringing = True
                        self.radio_holder.set_radio_on(True)
                        asyncio.create_task(self.volume_ramp_up_and_ring(alarm))
                        print("Alarm ringing!")
                        # Here you would implement the logic to start the radio or sound the alarm
            self.show_time(tm)
            await asyncio.sleep(1)

    def show_time(self, tm):
        time_str = "{:02}:{:02}:{:02}".format(tm[3]+self.clock_app.zone, tm[4], tm[5])
        self.display.text(vga2_bold_16x32, time_str, 50, 200, st7789.WHITE, st7789.BLACK)

    async def volume_ramp_up_and_ring(self, alarm):
        # Let it ring for 60 minutes
        self.radio_holder.delayed_off(60)
        for vol in range(1, alarm.volume + 1):
            if not self.radio_holder.radio_on:
                alarm.ringing = False
                return
            self.radio_holder.set_volume(vol)
            await asyncio.sleep(5)

class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

class Application:
    background = st7789.BLACK
    foreground = st7789.WHITE

    def __init__(self, name, display, radio_holder, main_coords, mini_coords, modes=[]):
        self.name = name
        self.display = display
        self.radio_holder = radio_holder
        self.main_coords = main_coords
        self.mini_coords = mini_coords
        self.selected = False
        self.modes = modes
        self.mode_index = 0
        self.selected_mode = None
        self.need_save = False

    def get_fg_bg_color(self, alt=None):
        if (alt is not None and alt) or (alt is None and self.selected):
            return Application.background, Application.foreground
        else:
            return Application.foreground, Application.background

    def print_mini(self):
        fg, bg = self.get_fg_bg_color()
        self.display.fill_rect(self.mini_coords.x, self.mini_coords.y, 320-self.mini_coords.x-MINI_APP_X_MARGIN, MINI_APP_INNER_HEIGHT, bg)
        self.display.text(vga2_8x8, self.name, self.mini_coords.x, self.mini_coords.y, fg, bg)

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
                self.display.fill_rect(self.main_coords.x, self.main_coords.y, MAIN_AREA_WIDTH, MAIN_AREA_HEIGHT, Application.background)
                self.print_mini()
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
                self.display.fill_rect(0, 0, 238, 16, Application.background)
                self.selected = False
                self.print_mini()
                self.print_arrow_mode(clear_all=True)
                return None
        return self

    def __setattr__(self, name, value):
        if name in self.__dict__.get("saved_attributes", []):
            self.need_save = True
        return super().__setattr__(name, value)

    def save_state(self):
        return { attr: self.__dict__.get(attr) for attr in self.saved_attributes }

    def load_state(self, state):
        for key in state:
            self.__setattr__(key, state.get(key, None))
        self.need_save = False

class Mode:
    def __init__(self, name):
        self.name = name

    def handle_event(self, event):
        if event.type == Event.KO_PUSH:
            return None
        return self

class RadioOnOff(Mode):
    def __init__(self, radio_app):
        super().__init__("on ")
        self.radio_app = radio_app

    def handle_event(self, event):
        if self.radio_app.radio_holder.radio_on:
            self.name = "on "
            self.radio_app.radio_holder.set_radio_on(False)
        else:
            self.name = "off"
            self.radio_app.radio_holder.set_radio_on(True)
        return None

class RadioSeekMode(Mode):
    def __init__(self, radio_app):
        super().__init__("seek")
        self.radio_app = radio_app

    def handle_event(self, event):
        if event.type == Event.ROT_CW:
            self.radio_app.radio_holder.radio.seek_up()
        elif event.type == Event.ROT_CCW:
            self.radio_app.radio_holder.radio.seek_down()
        elif event.type == Event.KO_PUSH:
            return None
        return self    

class RadioManualMode(Mode):
    def __init__(self, radio_app):
        super().__init__("manual")
        self.radio_app = radio_app

    def handle_event(self, event):
        if event.type == Event.ROT_CW:
            self.radio_app.radio_holder.radio.set_frequency((int(10*self.radio_app.radio_holder.radio.get_frequency())+1)/10)
        elif event.type == Event.ROT_CCW:
            self.radio_app.radio_holder.radio.set_frequency((int(10*self.radio_app.radio_holder.radio.get_frequency())-1)/10)
        elif event.type == Event.KO_PUSH:
            return None
        return self

class RadioFavMode(Mode):
    def __init__(self, radio_app):
        super().__init__("fav")

class RadioSleepMode(Mode):
    def __init__(self, radio_app):
        super().__init__("sleep")
        self.radio_app = radio_app
        self.sleep_times = [5, 10, 15, 30, 45, 60] # in minutes
        self.sleep_index = 0

    def handle_event(self, event):
        if event.type == Event.MODE_ENTER:
            self.print_sleep_time()
        elif event.type == Event.ROT_CW:
            self.sleep_index += 1
            if self.sleep_index >= len(self.sleep_times):
                self.sleep_index = 0
            self.print_sleep_time()
        elif event.type == Event.ROT_CCW:
            self.sleep_index -= 1
            if self.sleep_index < 0:
                self.sleep_index = len(self.sleep_times)-1
            self.print_sleep_time()
        elif event.type == Event.ROT_REL:
            # set sleep time
            sleep_minutes = self.sleep_times[self.sleep_index]
            # Here you would implement the logic to start a sleep timer
            print("Radio will sleep in {} minutes".format(sleep_minutes))
            self.radio_app.radio_holder.delayed_off(sleep_minutes)
            return None
        elif event.type == Event.KO_PUSH:
            return None
        return self

    def print_sleep_time(self):
        self.radio_app.display.text(vga2_bold_16x32, "Sleep:    min", self.radio_app.main_coords.x, self.radio_app.main_coords.y, Application.foreground)
        time_str = "{:02}".format(self.sleep_times[self.sleep_index])
        fg, bg = self.radio_app.get_fg_bg_color()
        self.radio_app.display.text(vga2_bold_16x32, time_str, self.radio_app.main_coords.x+7*16, self.radio_app.main_coords.y, fg, bg)

class RadioApp(Application):

    def __init__(self, name, display, radio_holder, main_coords, mini_coords):
        super().__init__(name, display, radio_holder, main_coords, mini_coords)
        self.modes = [ RadioOnOff(self),
                  RadioFavMode(self),
                  RadioSeekMode(self),
                  RadioManualMode(self),
                  RadioSleepMode(self)
                ]
        self.sleep_time = None

    def print_mini(self):
        super().print_mini()
        status = "on vol:{:>2}".format(self.radio_holder.radio.get_volume()) if self.radio_holder.radio_on else "off"

        fg, bg = self.get_fg_bg_color()
        self.display.text(vga2_8x8, status, self.mini_coords.x, self.mini_coords.y+12, fg, bg)

        if self.sleep_time is not None:
            sleep_str = " sleep:{:>2}m".format(self.sleep_time)
            self.display.text(vga2_8x8, sleep_str, self.mini_coords.x, self.mini_coords.y+24, fg, bg)

class AlarmOn(Mode):
    def __init__(self, alarm_app):
        super().__init__("on")
        self.alarm_app = alarm_app

    def handle_event(self, event):
        if self.alarm_app.wakeup is None:
            return None
        self.alarm_app.active = True
        self.alarm_app.print_mini()
        return None

class AlarmOff(Mode):
    def __init__(self, alarm_app):
        super().__init__("off")
        self.alarm_app = alarm_app  

    def handle_event(self, event):
        self.alarm_app.active = False
        self.alarm_app.print_mini()
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
        if event.type == Event.MODE_ENTER:
            self.hour, self.minute = self.alarm_app.wakeup
        elif event.type == Event.ROT_CW:
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
                self.setting_hour = True
                self.alarm_app.print_mini()
                return None
        elif event.type == Event.KO_PUSH:
            return None
        self.print_time()
        return self

    def print_time(self):
        self.alarm_app.display.text(vga2_bold_16x32, "Alarm: xx:xx", self.alarm_app.main_coords.x, self.alarm_app.main_coords.y, Application.foreground)
        time_str = "{:02}".format(self.hour)
        fg, bg = self.alarm_app.get_fg_bg_color(self.setting_hour)
        self.alarm_app.display.text(vga2_bold_16x32, time_str, self.alarm_app.main_coords.x+7*16, self.alarm_app.main_coords.y, fg, bg)
        time_str = "{:02}".format(self.minute)
        fg, bg = self.alarm_app.get_fg_bg_color(not self.setting_hour)
        self.alarm_app.display.text(vga2_bold_16x32, time_str, self.alarm_app.main_coords.x+10*16, self.alarm_app.main_coords.y, fg, bg)

class AlarmSetVolume(Mode):
    def __init__(self, alarm_app):
        super().__init__("volume")
        self.alarm_app = alarm_app
        self.volume = 0

    def handle_event(self, event):
        if event.type == Event.MODE_ENTER:
            self.volume = self.alarm_app.volume
        elif event.type == Event.ROT_CW:
            self.volume += 1 if not event.fast else 5
            if self.volume > 30:
                self.volume = 30
        elif event.type == Event.ROT_CCW:
            self.volume -= 1 if not event.fast else 5
            if self.volume < 1:
                self.volume = 1
        elif event.type == Event.ROT_REL:
            #finish setting
            self.alarm_app.volume = self.volume
            self.alarm_app.print_mini()
            return None
        elif event.type == Event.KO_PUSH:
            return None
        self.print_volume()
        return self
    
    def print_volume(self):
        self.alarm_app.display.text(vga2_bold_16x32, "Volume: ", self.alarm_app.main_coords.x, self.alarm_app.main_coords.y, Application.foreground)
        vol_str = "{:>2}".format(self.volume)
        fg, bg = self.alarm_app.get_fg_bg_color(True)
        self.alarm_app.display.text(vga2_bold_16x32, vol_str, self.alarm_app.main_coords.x+8*16, self.alarm_app.main_coords.y, fg, bg)

class AlarmApp(Application):

    def __init__(self, name, display, radio_holder, main_coords, mini_coords):
        modes = [AlarmOn(self),
                 AlarmOff(self),
                 AlarmStation(self),
                 AlarmSet(self),
                 AlarmSetVolume(self)]
        super().__init__(name, display, radio_holder, main_coords, mini_coords, modes=modes)
        self.wakeup = (0,0)
        self.active = False
        self.volume = 12

        self.ringing = False
        self.saved_attributes = ["wakeup", "active", "volume"]

    def print_mini(self):
        super().print_mini()
        status = "--:--"
        if self.wakeup:
            status = "{:02}:{:02}".format(self.wakeup[0], self.wakeup[1])
        fg, bg = self.get_fg_bg_color()
        self.display.text(vga2_8x8, status, self.mini_coords.x, self.mini_coords.y+12, fg, bg)

        if self.active:
            status = "on"
            fg = st7789.RED
        else:
            status = "off"
        self.display.text(vga2_8x8, status, self.mini_coords.x+8*6, self.mini_coords.y+12, fg, bg)


class ClockZoneMode(Mode):
    def __init__(self, clock_app):
        super().__init__("zone")
        self.clock_app = clock_app

    def handle_event(self, event):
        if event.type == Event.MODE_ENTER:
            self.zone = self.clock_app.zone
        elif event.type == Event.ROT_CW:
            self.zone += 1
            if self.zone > 12:
                self.zone = 12
        elif event.type == Event.ROT_CCW:
            self.zone -= 1
            if self.zone < -12:
                self.zone = -12
        elif event.type == Event.ROT_REL:
            self.clock_app.zone = self.zone
            return None
        elif event.type == Event.KO_PUSH:
            return None
        self.print_zone()
        return self

    def print_zone(self):
        self.clock_app.display.text(vga2_bold_16x32, "Time zone: ", self.clock_app.main_coords.x, self.clock_app.main_coords.y, Application.foreground)
        vol_str = "{:>+3d}".format(self.zone)
        fg, bg = self.clock_app.get_fg_bg_color(True)
        self.clock_app.display.text(vga2_bold_16x32, vol_str, self.clock_app.main_coords.x+11*16, self.clock_app.main_coords.y, fg, bg)
       

class ClockApp(Application):
    def __init__(self, name, display, radio_holder, main_coords, mini_coords):
        modes = [ClockZoneMode(self)]
        super().__init__(name, display, radio_holder, main_coords, mini_coords, modes=modes)
        self.zone = 0

        self.saved_attributes = ["zone"]

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
        # H W inverted, screen is rotated
        self.display = st7789.ST7789(spi, 240, 320, reset=Pin(5, Pin.OUT), dc=Pin(18, Pin.OUT), backlight=Pin(19, Pin.OUT), rotation=1, color_order=st7789.RGB)
        self.display.inversion_mode(False)
        self.display.init()

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
        utime.sleep_ms(200)
        reset_pin.value(1)
        utime.sleep_ms(100)

        sda.value(1)
        i2c = I2C(1, scl=scl, sda=sda, freq=400000)

        self.radio = SI4703(i2c, reset_pin, sen_pin, irq_pin)

        try:
            ntptime.host = "fr.pool.ntp.org"
            ntptime.settime()
        except Exception as e:
            print("Failed to sync time: {}".format(e))


        self.radio_holder = RadioHolder(self.radio, None)

        main_coords = Point(MAIN_AREA_X, MAIN_AREA_Y)

        self.radio_app = RadioApp("Radio", self.display, self.radio_holder, main_coords, Point(MINI_SPLIT_X+MINI_APP_X_MARGIN, MINI_APP_Y_MARGIN))
        self.radio_holder.radio_app = self.radio_app
        alarm_app1 = AlarmApp("Alarm1", self.display, self.radio_holder, main_coords, Point(MINI_SPLIT_X+MINI_APP_X_MARGIN, MINI_APP_Y_MARGIN + MINI_APP_HEIGHT))
        alarm_app2 = AlarmApp("Alarm2", self.display, self.radio_holder, main_coords, Point(MINI_SPLIT_X+MINI_APP_X_MARGIN, MINI_APP_Y_MARGIN + 2*MINI_APP_HEIGHT))
        clock_app = ClockApp("Clock", self.display, self.radio_holder, main_coords, Point(MINI_SPLIT_X+MINI_APP_X_MARGIN, MINI_APP_Y_MARGIN + 3*MINI_APP_HEIGHT))

        self.clock = Clock(self.display, self.radio_holder, [alarm_app1, alarm_app2], clock_app)
        
        self.apps = [ self.radio_app,
                      alarm_app1,
                      alarm_app2,
                      clock_app
                    ]

        for app in self.apps:
            try:
                with open("{}.json".format(app.name), "rt") as file:
                    state = json.load(file)
                    app.load_state(state)
            except OSError as excp:
                pass

        self.pre_app = 0
        self.selected_app = None

        self.setting_volume = False
        self.volume_set = False

        # Initial display of apps with framing
        self.display.vline(MINI_SPLIT_X, 0, SCREEN_HEIGHT, st7789.WHITE)
        x = 0
        for app in self.apps:
            self.display.hline(MINI_SPLIT_X, x, SCREEN_WIDTH - MINI_SPLIT_X, st7789.WHITE)
            app.print_mini()
            x += MINI_APP_HEIGHT
        self.display.hline(MINI_SPLIT_X, x, SCREEN_WIDTH - MINI_SPLIT_X, st7789.WHITE)

        self.print_arrow_app()

    def print_arrow_app(self, clear_all=False):
        y = 10
        for ctr, app in enumerate(self.apps):
            if ctr == self.pre_app and not clear_all:
                self.display.text(vga2_8x8, "\x10", MINI_SPLIT_X-10, y, Application.foreground)
            else:
                self.display.text(vga2_8x8, " ", MINI_SPLIT_X-10, y, Application.foreground)
            y += MINI_APP_HEIGHT

    def handle_events(self):
        event = self.events.pop()
        while event is not None:
            if self.radio_holder.radio_on:
                if event.type == Event.TUNED:
                    self.radio.enable_rds(True)  # Enable RDS when tuned
                    freq_str = "{:.1f} MHz".format(event.frequency)
                    rssi_str = "RSSI: {}".format(event.rssi)
                    self.display.fill_rect(50, 150, 200, 16, st7789.BLACK)
                    self.display.text(vga2_8x8, freq_str, 50, 150, st7789.WHITE)
                    self.display.fill_rect(50, 170, 200, 16, st7789.BLACK)
                    self.display.text(vga2_8x8, rssi_str, 50, 170, st7789.WHITE)
                elif event.type == Event.RDS_Basic_Tuning:
                    self.display.text(vga2_bold_16x32, event.text, 20, 130, st7789.WHITE, st7789.BLACK)
                elif event.type == Event.RDS_Radio_Text:
                    self.display.text(vga2_bold_16x32, event.text[:14], 0, 100, st7789.WHITE, st7789.BLACK)
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
                        # volume was not set, so consider as normal click
                        self.setting_volume = False
                    elif event.type == Event.ROT_CW :
                        # volume adjustment
                        self.radio_holder.set_volume(self.radio.get_volume() + (1 if not event.fast else 5))
                        self.volume_set = True
                        event = self.events.pop()
                        continue
                    elif event.type == Event.ROT_CCW:
                        # volume adjustment
                        self.radio_holder.set_volume(self.radio.get_volume() - (1 if not event.fast else 5))
                        self.volume_set = True
                        event = self.events.pop()
                        continue
            if self.selected_app is not None:
                app = self.selected_app # save app
                self.selected_app = self.selected_app.handle_event(event)
                if self.selected_app is None:
                    if app.need_save:
                        with open("{}.json".format(app.name), "wt") as file:
                            json.dump(app.save_state(), file)
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
                    if self.radio_holder.radio_on:
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

    def basic_tuning_handler(self, text):
        print("RDS Basic Tuning Text: {}".format(text))
        self.events.push(BasicTuningEvent(text))

    def radio_text_handler(self, text):
        print("RDS Radio Text: {}".format(text))
        self.events.push(RadioTextEvent(text))

    def start_radio(self):
        self.radio.power_cristal(True)
        self.radio.enable(True)
        self.radio.set_tuned_irq(self.tuned_handler)
        self.radio.set_basic_tuning_handler(self.basic_tuning_handler)
        self.radio.set_radio_text_irq(self.radio_text_handler)
        self.radio.mute(True)           # Mute the audio
        self.radio.set_frequency(98.2)   # Set frequency to 98.2 MHz
        self.radio.set_volume(1)         # Set volume to lowest level

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
