import time
from machine import Pin
from event import Event, EventRotCwEvent, EventRotCcwEvent

class RotaryEncoder:
    # Rotary encoder handling code would go here
    def __init__(self, pin_a, pin_b, pin_button, event_queue):
        self.pin_a = pin_a
        self.pin_b = pin_b
        self.pin_button = pin_button
        self.event_queue = event_queue
        self.last_rotation_ts = 0
        self.last_button_state = 1
        # Initialize GPIO pins and interrupts
        self.pin_a.irq(self._handle_rotation, Pin.IRQ_FALLING)
        self.pin_button.irq(self._handle_button, Pin.IRQ_RISING | Pin.IRQ_FALLING)

    def _handle_rotation(self, pin):
        # Logic to determine rotation direction and generate events
        a_state = pin.value()
        b_state = self.pin_b.value()
        now = time.ticks_ms()
        if a_state == 0 and b_state == 1:
            if time.ticks_diff(now, self.last_rotation_ts) < 50:
                self.event_queue.push(EventRotCwEvent(fast=True))
            else:
                self.event_queue.push(EventRotCwEvent())
            self.last_rotation_ts = now
        elif a_state == 0 and b_state == 0:
            if time.ticks_diff(now, self.last_rotation_ts) < 50:
                self.event_queue.push(EventRotCcwEvent(fast=True))
            else:
                self.event_queue.push(EventRotCcwEvent())
            self.last_rotation_ts = now

    def _handle_button(self, pin):
        # Logic to handle button press and generate event
        state = pin.value()
        if self.last_button_state == state:
            return
        self.last_button_state = state
        if state == 0:
            self.event_queue.push(Event(Event.ROT_PUSH))
        else:
            self.event_queue.push(Event(Event.ROT_REL))
