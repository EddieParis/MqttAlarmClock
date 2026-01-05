import json
import gc
from si4703 import SI4703
from rotary import RotaryEncoder
from event import *

from machine import I2C, Pin, SPI

import st7789
import vga2_bold_16x32
import vga2_8x8
import vga2_8x16
import ntptime
import utime
import uasyncio as asyncio
import micropython as upy

# display
# BLK 19
# A 26
# B 25
# push 33
# KO 32

SCREEN_WIDTH = const(320)
SCREEN_HEIGHT = const(240)

MINI_SPLIT_X = const(240)
MINI_APP_X_MARGIN = const(4)
MINI_APP_Y_MARGIN = const(4)
MINI_APP_HEIGHT = const(40)
MINI_APP_INNER_HEIGHT = const(MINI_APP_HEIGHT - 2*MINI_APP_Y_MARGIN)

MAIN_AREA_X = const(0)
MAIN_AREA_Y = const(32)
MAIN_AREA_WIDTH = const(MINI_SPLIT_X)
MAIN_AREA_HEIGHT = const(6*18)

RADIO_NAME_X = const(120-2*16)
RADIO_NAME_Y = const(SCREEN_HEIGHT-32-32-32)
RADIO_TEXT_X = const(0)
RADIO_TEXT_Y = const(SCREEN_HEIGHT-32-32)

class RadioManager:
    def __init__(self, radio):
        self.radio = radio
        self.radio_on = False
        self.delay_task = None
        self.setting_volume = False
        self.volume_set = False

        self.scroll_timer = None
        self.scroll_text = ""
        self.scroll_pos = 0

    def set_main_app(self, main_app):
        self.main_app = main_app
        self.radio_app = main_app.radio_app

    def set_volume(self, volume):
        self.radio.set_volume(volume)
        self.radio_app.display_mini()

    def set_radio_on(self, on):
        if self.delay_task is not None:
            self.delay_task.cancel()
            self.delay_task = None
        self.radio_app.sleep_time = None
        if on:
            self.radio.enable_rds(True)
            self.radio.mute(False)
            self.radio_on = True
        else:
            self.radio.enable_rds(False)
            self.radio.mute(True)
            self.clean_and_stop_scroll()
            self.radio_on = False
        self.radio_app.display_mini()

    def clean_and_stop_scroll(self):
        if self.scroll_timer is not None:
            self.scroll_timer.cancel()
        self.main_app.display.fill_rect(0, RADIO_NAME_Y, MINI_SPLIT_X, 64, st7789.BLACK)

    def tune_to(self, frequency):
        self.radio.enable_rds(False)
        self.radio.set_frequency(frequency)

    def seek(self, up):
        self.clean_and_stop_scroll()
        if up:
            self.radio.seek_up()
        else:
            self.radio.seek_down()

    def delayed_off(self, delay_minutes):
        self.radio_app.display_mini()
        if self.delay_task is not None:
            self.delay_task.cancel()
            self.delay_task = None
        async def delayed_task():
            while self.radio_app.sleep_time is None or self.radio_app.sleep_time > 0:
                await asyncio.sleep(60)
                if self.radio_app.sleep_time is not None:
                    self.radio_app.sleep_time -= 1
                    self.radio_app.display_mini()
            self.delay_task = None
            self.radio_app.sleep_time = None
            self.radio_app.display_mini()
            self.set_radio_on(False)
        self.radio_app.sleep_time = delay_minutes
        self.delay_task = asyncio.create_task(delayed_task())

    def do_scroll_text(self, first=False):
        async def scroll_timer_handler(self, first):
            self.main_app.display.text(vga2_bold_16x32, self.scroll_text[self.scroll_pos:self.scroll_pos+14], RADIO_TEXT_X, RADIO_TEXT_Y, st7789.WHITE, st7789.BLACK)
            await asyncio.sleep(2 if first else .250)
            self.scroll_pos +=1
            if self.scroll_pos > len(self.scroll_text)-14:
                self.scroll_pos = 0
                self.do_scroll_text(True)
            else:
                self.do_scroll_text(False)
        self.scroll_timer = asyncio.create_task(scroll_timer_handler(self, first))

    def handle_event(self, event):
        if self.radio_on:
            if event.type == Event.TUNED:
                self.radio.enable_rds(True)  # Enable RDS when tuned
                freq_str = "{:>5.1f} MHz".format(event.frequency)
                rssi_str = "{}".format(event.rssi)
                self.main_app.display.fill_rect(0, RADIO_NAME_Y, RADIO_NAME_X, 32, st7789.BLACK)
                self.main_app.display.text(vga2_8x16, freq_str, 0, RADIO_NAME_Y, st7789.WHITE)
                ctr = 0
                levels = [10, 20, 30, 40]
                while ctr < 4 and event.rssi >= levels[ctr]:
                    self.main_app.display.vline(24+2*ctr, RADIO_NAME_Y+32-4-4*ctr, 4*ctr+4, Application.foreground)
                    ctr += 1
                self.main_app.display.text(vga2_8x16, rssi_str, 0, RADIO_NAME_Y + 16, st7789.WHITE)
            elif event.type == Event.RDS_Basic_Tuning:
                self.main_app.display.text(vga2_bold_16x32, event.text, RADIO_NAME_X, RADIO_NAME_Y, st7789.WHITE, st7789.BLACK)
            elif event.type == Event.RDS_Radio_Text:
                if self.scroll_timer is not None:
                    self.scroll_timer.cancel()
                if len(event.text) > 14:
                    self.scroll_text = event.text.strip()+" "*14
                    self.scroll_pos = 0
                    self.do_scroll_text(True)
            # volume setting handling when radio is on
            # priority over app handling
            # pushing rotary button without rotation is considered as a normal click.
            elif event.type == Event.ROT_PUSH:
                if self.radio_on:
                    self.setting_volume = True
                    return None
            elif self.setting_volume:
                if event.type == Event.ROT_REL and self.volume_set:
                    self.setting_volume = False
                    self.volume_set = False
                    return None
                elif event.type == Event.ROT_REL:
                    # volume was not set, so consider as normal click
                    self.setting_volume = False
                elif event.type == Event.ROT_CW :
                    # volume adjustment
                    self.set_volume(self.radio.get_volume() + (1 if not event.fast else 5))
                    self.volume_set = True
                    return None
                elif event.type == Event.ROT_CCW:
                    # volume adjustment
                    self.set_volume(self.radio.get_volume() - (1 if not event.fast else 5))
                    self.volume_set = True
                    return None
        return event


class Clock:
    def __init__(self, main_app, radio_mgr, alarms, settings_app):
        self.display = main_app.display
        self.radio_mgr = radio_mgr
        self.alarms = alarms
        self.settings_app = settings_app

    async def update_time(self):
        while True:
            # print (upy.mem_info())
            tm = utime.localtime()
            tm = self.apply_tz(tm)
            for alarm in self.alarms:
                if alarm.active and alarm.wakeup is not None:
                    if [tm[3], tm[4]] == alarm.wakeup and alarm.last_ring_date != tm[:3] and not alarm.ringing:
                        alarm.last_ring_date = tm[:3]
                        alarm.ringing = True
                        self.radio_mgr.set_radio_on(True)
                        asyncio.create_task(self.volume_ramp_up_and_ring(alarm))
                        print("Alarm ringing!")
            self.show_time(tm)
            await asyncio.sleep_ms(1000-(utime.ticks_ms()%1000))

    def apply_tz(self, tm):
        tm = list(tm)
        tm[3] = (tm[3]+self.settings_app.zone)%24
        return tm

    def show_time(self, tm):
        self.display.text(vga2_8x16, "{:02}/{:02}".format(tm[2], tm[1]), 16, 240-32, st7789.WHITE, st7789.BLACK)
        self.display.text(vga2_8x16, " {:04}".format(tm[0]), 16, 240-16, st7789.WHITE, st7789.BLACK)
        time_str = "{:02}:{:02}:{:02}".format(tm[3], tm[4], tm[5])
        self.display.text(vga2_bold_16x32, time_str, MINI_SPLIT_X-8*16-32, 240-32, st7789.WHITE, st7789.BLACK)

    async def volume_ramp_up_and_ring(self, alarm):
        # Let it ring for 60 minutes
        self.radio_mgr.delayed_off(60)
        for vol in range(1, alarm.volume + 1):
            if not self.radio_mgr.radio_on:
                alarm.ringing = False
                return
            self.radio_mgr.set_volume(vol)
            await asyncio.sleep(5)

    def handle_event(self, event):
        ringing_alarms = list(filter(lambda x: x.ringing, self.alarms))
        if len(ringing_alarms):
            if event.type == Event.KO_REL:
                return None
            elif event.tpye == Event.ROT_REL:
                for alarm in ringing_alarms:
                    alarm.ringing = False
                self.radio_mgr.set_radio_on(False)
                return None
        return event

class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

class Application:
    background = st7789.BLACK
    foreground = st7789.WHITE

    def __init__(self, name, main_app, main_coords, mini_coords, modes=[]):
        self.name = name
        self.main_app = main_app
        self.display = main_app.display
        self.radio_mgr = main_app.radio_mgr
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

    def display_mini(self):
        fg, bg = self.get_fg_bg_color()
        self.display.fill_rect(self.mini_coords.x, self.mini_coords.y, 320-self.mini_coords.x-MINI_APP_X_MARGIN, MINI_APP_INNER_HEIGHT, bg)
        self.display.text(vga2_8x8, self.name, self.mini_coords.x, self.mini_coords.y, fg, bg)

    def display_arrow_mode(self, clear_all=False):
        x = 8
        for ctr, mode in enumerate(self.modes):
            if ctr == self.mode_index and not clear_all:
                self.display.text(vga2_8x8, "\x1e", x, 8, Application.foreground)
            else:
                self.display.text(vga2_8x8, " ", x, 8, Application.foreground)
            x += len(mode.name)*8 + 16

    def display_modes(self, selected=None):
        x = 0
        for ctr, mode in enumerate(self.modes):
            mode.pre_display_mode()
            if selected is not None and ctr == selected:
                self.display.text(vga2_8x8, mode.name, x, 0, Application.background, Application.foreground)
            else:
                self.display.text(vga2_8x8, mode.name, x, 0, Application.foreground)
            x += len(mode.name)*8 + 16
        self.display_arrow_mode()

    def handle_event(self, event):
        if self.selected_mode is not None:
            self.selected_mode = self.selected_mode.handle_event(event)
            if self.selected_mode is None:
                self.display.fill_rect(self.main_coords.x, self.main_coords.y, MAIN_AREA_WIDTH, MAIN_AREA_HEIGHT, Application.background)
                self.display_mini()
                self.display_modes()
        else:
            if event.type == Event.ROT_CW:
                self.mode_index += 1
                if self.mode_index > len(self.modes)-1:
                    self.mode_index = 0
                self.display_arrow_mode()
            elif event.type == Event.ROT_CCW:
                self.mode_index -= 1
                if self.mode_index < 0:
                    self.mode_index = len(self.modes)-1
                self.display_arrow_mode()
            elif event.type == Event.ROT_REL:
                #switch mode
                self.selected_mode = self.modes[self.mode_index]
                self.selected_mode.selected = True
                self.display_modes(selected=self.mode_index)
                self.display_arrow_mode(clear_all=True)
                self.handle_event(Event(Event.MODE_ENTER))
                return None
            elif event.type == Event.KO_PUSH:
                self.display.fill_rect(0, 0, MINI_SPLIT_X, 16, Application.background)
                self.selected_mode = None
                self.display_mini()
                self.display_arrow_mode(clear_all=True)
                self.main_app.post_exit_event()
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
            self.__setattr__(key, state[key])
        self.need_save = False

class Mode:
    def __init__(self, name):
        self.name = name

    def pre_display_mode(self):
        pass

    def handle_event(self, event):
        if event.type == Event.KO_PUSH:
            return None
        return self

class RadioOnOff(Mode):
    def __init__(self, radio_app):
        super().__init__("on ")
        self.radio_app = radio_app

    def pre_display_mode(self):
        if self.radio_app.radio_mgr.radio_on:
            self.name = "off"
        else:
            self.name = "on "

    def handle_event(self, event):
        if self.radio_app.radio_mgr.radio_on:
            self.name = "on "
            self.radio_app.radio_mgr.set_radio_on(False)
        else:
            self.name = "off"
            self.radio_app.radio_mgr.set_radio_on(True)
        return None

class RadioSeekMode(Mode):
    def __init__(self, radio_app):
        super().__init__("seek")
        self.radio_app = radio_app

    def handle_event(self, event):
        if event.type == Event.MODE_ENTER:
            self.print_arrows()
        if event.type == Event.ROT_CW:
            self.print_arrows(big_right=True)
            self.radio_app.radio_mgr.seek(True)
        elif event.type == Event.ROT_CCW:
            self.print_arrows(big_left=True)
            self.radio_app.radio_mgr.seek(False)
        elif event.type == Event.TUNED:
            self.print_arrows()
        elif event.type == Event.KO_PUSH:
            return None
        return self    

    def print_arrows(self, big_left=False, big_right=False):
        self.radio_app.display.fill_rect(self.radio_app.main_coords.x+102, self.radio_app.main_coords.y, 50, 32, Application.background)
        if big_left:
            self.radio_app.display.text(vga2_bold_16x32, "\x11", self.radio_app.main_coords.x+110-8, self.radio_app.main_coords.y, Application.foreground)
        else:
            self.radio_app.display.text(vga2_8x16, "\x11", self.radio_app.main_coords.x+110, self.radio_app.main_coords.y+8, Application.foreground)
        if big_right:
            self.radio_app.display.text(vga2_bold_16x32, "\x10", self.radio_app.main_coords.x+130, self.radio_app.main_coords.y, Application.foreground)
        else:
            self.radio_app.display.text(vga2_8x16, "\x10", self.radio_app.main_coords.x+130, self.radio_app.main_coords.y+8, Application.foreground)

class RadioManualMode(Mode):
    def __init__(self, radio_app):
        super().__init__("manual")
        self.radio_app = radio_app

    def handle_event(self, event):
        if event.type == Event.ROT_CW:
            self.radio_app.radio_mgr.radio.set_frequency((int(10*self.radio_app.radio_mgr.radio.get_frequency())+1)/10)
        elif event.type == Event.ROT_CCW:
            self.radio_app.radio_mgr.radio.set_frequency((int(10*self.radio_app.radio_mgr.radio.get_frequency())-1)/10)
        elif event.type == Event.KO_PUSH:
            return None
        return self

class RadioFavMode(Mode):
    def __init__(self, radio_app):
        super().__init__("fav")
        self.radio_app = radio_app
        self.stations = []
        self.start = 0
        self.highlight = 0

    def handle_event(self, event):
        if event.type == Event.MODE_ENTER:
            self.stations = list(self.radio_app.main_app.favorites_app.stations)
            filter(lambda x: x[2], self.stations)
            display_stations(self.stations, self.start, self.radio_app.display, self.radio_app.main_coords.x, self.radio_app.main_coords.y, self.highlight, False)
        elif event.type == Event.ROT_CW:
            self.highlight += 1
            if self.highlight > len(self.stations)-1:
                self.highlight = len(self.stations)-1
            display_stations(self.stations, self.start, self.radio_app.display, self.radio_app.main_coords.x, self.radio_app.main_coords.y, self.highlight, False)
        elif event.type == Event.ROT_CCW:
            self.highlight -= 1
            if self.highlight < 0:
                self.highlight = 0
            display_stations(self.stations, self.start, self.radio_app.display, self.radio_app.main_coords.x, self.radio_app.main_coords.y, self.highlight, False)
        elif event.type == Event.ROT_REL:
            self.radio_app.radio_mgr.tune_to(self.stations[self.highlight][0])
        elif event.type == Event.KO_REL:
            return None
        return self

class RadioSleepMode(Mode):
    def __init__(self, radio_app):
        super().__init__("sleep")
        self.radio_app = radio_app
        self.sleep_times = [5, 10, 15, 30, 45, 60] # in minutes
        self.sleep_index = 0

    def handle_event(self, event):
        if event.type == Event.MODE_ENTER:
            self.display_sleep_time()
        elif event.type == Event.ROT_CW:
            self.sleep_index += 1
            if self.sleep_index >= len(self.sleep_times):
                self.sleep_index = 0
            self.display_sleep_time()
        elif event.type == Event.ROT_CCW:
            self.sleep_index -= 1
            if self.sleep_index < 0:
                self.sleep_index = len(self.sleep_times)-1
            self.display_sleep_time()
        elif event.type == Event.ROT_REL:
            # set sleep time
            sleep_minutes = self.sleep_times[self.sleep_index]
            # Here you would implement the logic to start a sleep timer
            print("Radio will sleep in {} minutes".format(sleep_minutes))
            self.radio_app.radio_mgr.delayed_off(sleep_minutes)
            return None
        elif event.type == Event.KO_PUSH:
            return None
        return self

    def display_sleep_time(self):
        self.radio_app.display.text(vga2_bold_16x32, "Sleep:    min", self.radio_app.main_coords.x, self.radio_app.main_coords.y, Application.foreground)
        time_str = "{:02}".format(self.sleep_times[self.sleep_index])
        fg, bg = self.radio_app.get_fg_bg_color()
        self.radio_app.display.text(vga2_bold_16x32, time_str, self.radio_app.main_coords.x+7*16, self.radio_app.main_coords.y, fg, bg)

class RadioApp(Application):

    def __init__(self, name, main_app, main_coords, mini_coords):
        super().__init__(name, main_app, main_coords, mini_coords)
        self.modes = [ RadioOnOff(self),
                  RadioFavMode(self),
                  RadioSeekMode(self),
                  RadioManualMode(self),
                  RadioSleepMode(self)
                ]
        self.sleep_time = None

    def display_mini(self):
        super().display_mini()
        status = "on vol:{:>2}".format(self.radio_mgr.radio.get_volume()) if self.radio_mgr.radio_on else "off"

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
        if event.type == Event.MODE_ENTER:
            self.setting_hour = True
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
                self.alarm_app.wakeup = [self.hour, self.minute]
                self.alarm_app.last_ring_date = [0,0,0] # reset last ring date
                return None
        elif event.type == Event.KO_PUSH:
            return None
        self.display_time()
        return self

    def display_time(self):
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
            return None
        elif event.type == Event.KO_PUSH:
            return None
        self.display_volume()
        return self
    
    def display_volume(self):
        self.alarm_app.display.text(vga2_bold_16x32, "Volume: ", self.alarm_app.main_coords.x, self.alarm_app.main_coords.y, Application.foreground)
        vol_str = "{:>2}".format(self.volume)
        fg, bg = self.alarm_app.get_fg_bg_color(True)
        self.alarm_app.display.text(vga2_bold_16x32, vol_str, self.alarm_app.main_coords.x+8*16, self.alarm_app.main_coords.y, fg, bg)

class AlarmApp(Application):

    def __init__(self, name, main_app, main_coords, mini_coords):
        modes = [AlarmOn(self),
                 AlarmOff(self),
                 AlarmStation(self),
                 AlarmSet(self),
                 AlarmSetVolume(self)]
        super().__init__(name, main_app, main_coords, mini_coords, modes=modes)
        self.wakeup = [0,0]
        self.active = False
        self.volume = 12
        self.last_ring_date = [0,0,0]
        self.ringing = False
        self.saved_attributes = ["wakeup", "active", "volume", "last_ring_date"]

    def display_mini(self):
        super().display_mini()
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

MAX_STATIONS = const(12)

def display_stations(favorites, start, display, x, y, highlight_index = None, show_hearts=True):

    def display_half(fav, x, y, highlight, show_hearts):
        station = fav[1] if fav[1] is not None else "{:>4.1f}".format(fav[0])
        left_is_fav = fav[2] and show_hearts
        if highlight:
            display.text(vga2_8x16, "{} {:>8}".format("\x03" if left_is_fav else " ", station), x, y, Application.background, Application.foreground)
        else:
            display.text(vga2_8x16, "{} {:>8}".format("\x03" if left_is_fav else " ", station), x, y, Application.foreground)

    x += 16

    ctr = 0
    iter_fav = iter(favorites)
    while ctr != start:
        fav = next(iter_fav)
        ctr += 1
    x_offset = 0
    y_offset = 0
    while (ctr-start) < MAX_STATIONS:
        try:
            fav = next(iter_fav)
            display_half(fav, x+x_offset, y+y_offset, ctr==highlight_index, show_hearts)
        except StopIteration:
            display.text(vga2_8x8, " "*11, x+x_offset, y+y_offset, Application.foreground)
        if x_offset != 0:
            x_offset = 0
            y_offset += 18
        else:
            x_offset = 12*8
        ctr += 1

class FavSelectMode(Mode):
    def __init__(self, favorites_app):
        super().__init__("select")
        self.radio = favorites_app.radio_mgr.radio
        self.favorites_app = favorites_app
        self.timer = None
        self.highlight = 0
        self.start = 0
        self.stations = []

    def handle_event(self, event):
        if event.type == Event.MODE_ENTER:
            # shall set radio to off (mute)
            self.start = 0
            self.highlight = 0
            self.stations = list(self.favorites_app.stations)
            display_stations(self.stations, self.start, self.favorites_app.display, 0, 32, self.highlight)
        elif event.type == Event.ROT_CW:
            self.highlight += 1
            if self.highlight >= len(self.stations):
                self.highlight = 0
            self.radio.enable_rds(False)
            if len(self.stations):
                self.radio.set_frequency(self.stations[self.highlight][0])
            if self.highlight > MAX_STATIONS / 2 and self.highlight % 2 == 0 and not (len(self.stations) - self.highlight < MAX_STATIONS / 2):
                self.start = (self.highlight-6)
            display_stations(self.stations, self.start, self.favorites_app.display, 0, 32, self.highlight)
        elif event.type == Event.ROT_CCW:
            self.highlight -= 1
            if self.highlight < 0:
                self.highlight = len(self.stations) - 1
            self.radio.enable_rds(False)
            if len(self.stations):
                self.radio.set_frequency(self.stations[self.highlight][0])
            if self.highlight > MAX_STATIONS / 2 and self.highlight % 2 == 0:
                self.start = (self.highlight-6)
            display_stations(self.stations, self.start, self.favorites_app.display, 0, 32, self.highlight)
        elif event.type == Event.ROT_REL:
            if len(self.stations):
                self.stations[self.highlight][2] = not self.stations[self.highlight][2]
            display_stations(self.stations, self.start, self.favorites_app.display, 0, 32, self.highlight)
        elif event.type == Event.KO_REL:
            self.favorites_app.stations = self.stations
            return None
        elif event.type == Event.TUNED:
            self.radio.enable_rds(True)
        elif event.type == Event.RDS_Basic_Tuning:
            if self.radio.get_frequency() == self.stations[self.highlight][0] and event.text != self.stations[self.highlight][1]:
                self.stations[self.highlight][1] = event.text
        return self

    def tune(self, frequency):
        self.radio.set_frequency(frequency)

class FavScanMode(Mode):
    def __init__(self, favorites_app):
        super().__init__("scan")
        self.radio = favorites_app.radio_mgr.radio
        self.favorites_app = favorites_app
        self.timer = None
        self.stations = []
        self.start = 0
        self.seek_done = False

    def handle_event(self, event):
        if event.type == Event.MODE_ENTER:
            # shall set radio to off (mute)
            self.start = 0
            self.seek_done = False
            self.radio.seek_all()
        elif event.type == Event.TUNED:
            if not event.valid:
                self.scan_continue()
            else:
                self.radio.enable_rds(True)
                self.timer = self.favorites_app.main_app.set_timer(1)
        elif event.type == Event.RDS_Basic_Tuning:
            if self.timer is not None:
                self.timer.cancel()
                self.timer = None
            self.stations.append([self.radio.get_frequency(), event.text, False])
            self.scan_continue()
        elif event.type == Event.TIMEOUT:
            self.stations.append([self.radio.get_frequency(), None, False])
            self.scan_continue()
        elif event.type == Event.KO_REL:
            self.radio.seek_stop()
            return None
        elif event.type == Event.SEEK_COMPLETE:
            for station in self.stations:
                print(station)
            self.seek_done = True
            display_stations(self.stations, 0, self.favorites_app.display, 0, 32)
        elif event.type == Event.ROT_REL:
            self.favorites_app.stations = self.stations
        return self

    def scan_continue(self):
        if len(self.stations) >= 12 and len(self.stations) % 2:
            self.start += 2
        display_stations(self.stations, self.start, self.favorites_app.display, 0, 32)
        self.radio.enable_rds(False)
        self.radio.seek_up(False)

class FavoritesApp(Application):
    def __init__(self, name, main_app, main_coords, mini_coords):
        super().__init__(name, main_app, main_coords, mini_coords)
        self.modes = [FavSelectMode(self), FavScanMode(self)]
        self.stations = []
        self.saved_attributes = ["stations"]

class ClockZoneMode(Mode):
    def __init__(self, settings_app):
        super().__init__("zone")
        self.settings_app = settings_app

    def handle_event(self, event):
        if event.type == Event.MODE_ENTER:
            self.zone = self.settings_app.zone
        elif event.type == Event.ROT_CW:
            self.zone += 1
            if self.zone > 12:
                self.zone = 12
        elif event.type == Event.ROT_CCW:
            self.zone -= 1
            if self.zone < -12:
                self.zone = -12
        elif event.type == Event.ROT_REL:
            self.settings_app.zone = self.zone
            return None
        elif event.type == Event.KO_PUSH:
            return None
        self.display_zone()
        return self

    def display_zone(self):
        self.settings_app.display.text(vga2_bold_16x32, b"Time zone: ", self.settings_app.main_coords.x, self.settings_app.main_coords.y, Application.foreground)
        vol_str = "{:>+3d}".format(self.zone)
        fg, bg = self.settings_app.get_fg_bg_color(True)
        self.settings_app.display.text(vga2_bold_16x32, vol_str, self.settings_app.main_coords.x+11*16, self.settings_app.main_coords.y, fg, bg)
       

class SettingsApp(Application):
    def __init__(self, name, main_app, main_coords, mini_coords):
        super().__init__(name, main_app, main_coords, mini_coords)
        self.modes = [ClockZoneMode(self)]
        self.zone = 0
        self.saved_attributes = ["zone"]

class ApplicationHandler:
    def __init__(self):
        self.event_flag = asyncio.ThreadSafeFlag()
        self.events = EventsQueue(self.event_flag)

        pin_a = Pin(26, Pin.IN)
        pin_b = Pin(25, Pin.IN)
        rotary_button = Pin(33, Pin.IN)
        self.rotary = RotaryEncoder(pin_a, pin_b, rotary_button, self.events)

        self.pin_ko = Pin(32, Pin.IN)
        self.pin_ko.irq(trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, handler=self.ko_handler)

        spi = SPI(2, baudrate=4000000, polarity=1, phase=1, sck=Pin(16), mosi=Pin(17))
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


        self.radio_mgr = RadioManager(self.radio)

        main_coords = Point(MAIN_AREA_X, MAIN_AREA_Y)

        self.radio_app = RadioApp("Radio", self, main_coords, Point(MINI_SPLIT_X+MINI_APP_X_MARGIN, MINI_APP_Y_MARGIN))
        self.radio_mgr.set_main_app(self)
        alarm_app1 = AlarmApp("Alarm1", self, main_coords, Point(MINI_SPLIT_X+MINI_APP_X_MARGIN, MINI_APP_Y_MARGIN + MINI_APP_HEIGHT))
        alarm_app2 = AlarmApp("Alarm2", self, main_coords, Point(MINI_SPLIT_X+MINI_APP_X_MARGIN, MINI_APP_Y_MARGIN + 2*MINI_APP_HEIGHT))
        self.favorites_app = FavoritesApp("Favorites", self, main_coords, Point(MINI_SPLIT_X+MINI_APP_X_MARGIN, MINI_APP_Y_MARGIN + 3*MINI_APP_HEIGHT))
        settings_app = SettingsApp("Settings", self, main_coords, Point(MINI_SPLIT_X+MINI_APP_X_MARGIN, MINI_APP_Y_MARGIN + 4*MINI_APP_HEIGHT))

        self.clock = Clock(self, self.radio_mgr, [alarm_app1, alarm_app2], settings_app)

        self.apps = [ self.radio_app,
                      alarm_app1,
                      alarm_app2,
                      self.favorites_app,
                      settings_app
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

        self.last_ko_state = 1

        # Initial display of apps with framing
        self.display.vline(MINI_SPLIT_X, 0, SCREEN_HEIGHT, st7789.WHITE)
        x = 0
        for app in self.apps:
            self.display.hline(MINI_SPLIT_X, x, SCREEN_WIDTH - MINI_SPLIT_X, st7789.WHITE)
            app.display_mini()
            x += MINI_APP_HEIGHT
        self.display.hline(MINI_SPLIT_X, x, SCREEN_WIDTH - MINI_SPLIT_X, st7789.WHITE)

        self.display_arrow_app()

    def display_arrow_app(self, clear_all=False):
        y = 10
        for ctr, app in enumerate(self.apps):
            if ctr == self.pre_app and not clear_all:
                self.display.text(vga2_8x8, "\x10", MINI_SPLIT_X-10, y, Application.foreground)
            else:
                self.display.text(vga2_8x8, " ", MINI_SPLIT_X-10, y, Application.foreground)
            y += MINI_APP_HEIGHT

    def set_timer(self, delay):
        async def async_delay_task(self, delay):
            await asyncio.sleep(delay)
            self.events.push(Event(Event.TIMEOUT))
        return asyncio.create_task(async_delay_task(self, delay))

    def post_exit_event(self):
        self.events.push(Event(Event.EXIT))

    def handle_events(self):
        event = self.events.pop()
        while event is not None:
            if self.radio_mgr.handle_event(event) is None:
                event = self.events.pop()
                continue
            if self.clock.handle_event(event) is None:
                event = self.events.pop()
                continue
            if self.selected_app is not None:
                if event.type == Event.EXIT:
                    if self.selected_app.need_save:
                        with open("{}.json".format(self.selected_app.name), "wt") as file:
                            json.dump(self.selected_app.save_state(), file)
                        self.selected_app.need_save = False
                    self.selected_app.selected = False
                    self.selected_app.display_mini()
                    self.selected_app = None
                    self.display_arrow_app()
                else:
                    self.selected_app.handle_event(event)
            else:
                if event.type == Event.ROT_CW:
                    self.pre_app += 1
                    if self.pre_app > len(self.apps)-1:
                        self.pre_app = 0
                    self.display_arrow_app()
                elif event.type == Event.ROT_CCW:
                    self.pre_app -= 1
                    if self.pre_app < 0:
                        self.pre_app = len(self.apps)-1
                    self.display_arrow_app()
                elif event.type == Event.ROT_REL:
                    #switch app
                    self.selected_app = self.apps[self.pre_app]
                    self.selected_app.selected = True
                    self.display_arrow_app(clear_all=True)
                    self.selected_app.display_mini()
                    self.selected_app.display_modes()
            event = self.events.pop()

    def ko_handler(self, pin):
        state = pin.value()
        if state == self.last_ko_state:
            return
        self.last_ko_state = state
        if state == 0:
            print("KO button pressed")
            self.events.push(Event(Event.KO_PUSH))
            # Implement KO button functionality here
        else:
            print("KO button released")
            self.events.push(Event(Event.KO_REL))
            # Implement KO button release functionality here

    def tuned_handler(self, frequency, rssi, valid):
        print("Tuned to frequency: {:.1f} MHz, RSSI: {}, Valid {}".format(frequency, rssi, valid))
        self.events.push(RadioTunedEvent(frequency, rssi, valid))

    def basic_tuning_handler(self, text):
        print("RDS Basic Tuning Text: {}".format(text))
        self.events.push(BasicTuningEvent(text))

    def radio_text_handler(self, text):
        print("RDS Radio Text: {}".format(text))
        self.events.push(RadioTextEvent(text))

    def seek_complete_handler(self):
        print("seek complete")
        self.events.push(Event(Event.SEEK_COMPLETE))

    def start_radio(self):
        self.radio.power_cristal(True)
        self.radio.enable(True)
        self.radio.set_tuned_irq(self.tuned_handler)
        self.radio.set_basic_tuning_handler(self.basic_tuning_handler)
        self.radio.set_radio_text_irq(self.radio_text_handler)
        self.radio.set_seek_complete_irq(self.seek_complete_handler)
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

gc.collect()

asyncio.run(app.main())
